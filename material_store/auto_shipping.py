"""Event-driven shipment completion with a periodic source reconciliation fallback.

Activation takes a baseline, so historical shipments do not get new receipts.
Native approval and source reads occur outside all write transactions.
"""
from __future__ import annotations
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from urllib.parse import quote
from psycopg import sql
from psycopg.types.json import Jsonb
from .db import connection
from . import repository as repo

FLAG='automatic-shipping:enabled'
PREFIX='automatic-shipping:request:'
POLL_SECONDS=15
_last_poll=0.0


def enabled(conn):
    return conn.execute('SELECT EXISTS(SELECT 1 FROM material_ops.documents WHERE name=%s)',(FLAG,)).fetchone()[0]


def document(conn,key,*,lock=False):
    row=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s'+(' FOR UPDATE' if lock else ''),(PREFIX+key,)).fetchone()
    return row[0] if row else {}


def put(conn,key,value):
    conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()',
                 (PREFIX+key,Jsonb(value)))


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def image_keys(conn,images):
    keys=[]
    from .shipping_defaults import real_images
    from .approval_shipping import image_key
    for image in real_images(conn,images):
        stable=image_key(conn,image)
        if stable:
            keys.append(stable);continue
        token=image.get('file_token')
        if not token and image.get('local_media_id'):
            row=conn.execute('SELECT feishu_file_token FROM material_ops.media WHERE id=%s',(image['local_media_id'],)).fetchone()
            token=(row[0] if row else None) or image['local_media_id']
        if token:keys.append(str(token))
    return keys


def content(conn,fields):
    import app
    from .shipping_calendar import date_text,TEXT,IMAGES
    from .shipping_defaults import real_text
    return {'text':real_text(app.feishu_text(fields,TEXT)),'images':image_keys(conn,fields.get(IMAGES)),
            'ship_date':date_text(fields.get('物料发货时间')),'arrival_start':date_text(fields.get('要求达到开始日期'))}


def snapshot(conn,fields,lines):
    import app
    details=sorted((app.feishu_text(r['fields'],'明细编号'),app.feishu_text(r['fields'],'明细状态'),
                    app.feishu_int(r['fields'],'实际发放数量')) for r in lines)
    body=content(conn,fields)
    value={'content':body,'source_status':app.feishu_text(fields,'审批状态'),
           'code':app.feishu_text(fields,'审批实例Code'),'review':app.feishu_text(fields,'库存审查状态'),'lines':details}
    return {**value,'fingerprint':digest(value),'ready_lines':bool(details) and all(no and state=='已发放' for no,state,_ in details)}


def graph(conn):
    import app
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME);line_info=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    aliases={}
    for key,remote in conn.execute(sql.SQL('SELECT _record_key,_remote_id FROM material_data.{} WHERE NOT _deleted').format(sql.Identifier(info['sql_table']))):
        aliases[key]=key
        if remote:aliases[remote]=key
    by_request={}
    for row in repo.rows(conn,line_info):
        for linked in app.feishu_link_ids_any(row['fields'],['所属申请单','申请单']):
            if linked in aliases:by_request.setdefault(aliases[linked],[]).append(row)
    return info,by_request


def activate(client=None,seed_native=None):
    """Create an idempotent, source-based baseline without business writes/messages."""
    import app
    with connection() as conn:
        if enabled(conn):return {'already_enabled':True}
        info,lines=graph(conn)
    if client is None:client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    source={r['record_id']:r['fields'] for r in client.list_records(info['table_id'])}
    now=time.time();count=0
    with connection() as conn,conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('automatic-shipping-activate',0))")
        if enabled(conn):return {'already_enabled':True}
        for key,remote,values in conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields FROM material_data.{} WHERE NOT _deleted').format(sql.Identifier(info['sql_table']))):
            fields=source.get(remote) or repo.feishu_record(info,{'record_id':key,'fields':values})['fields']
            if app.feishu_text(fields,'申请类型')!='普通物料申请':continue
            state=snapshot(conn,fields,lines.get(key,[]))
            cached=(seed_native or {}).get(state['code']) or {}
            if cached.get('status') and not cached.get('error_type'):
                state['native']={**cached,'code':state['code'],'checked_at':now if cached['status']!='PENDING' else 0}
            state.update(notice_signature=digest(state['content']),state='baseline',dirty=False,announced=fields.get('是否发货') is True)
            put(conn,key,state);count+=1
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',(FLAG,Jsonb({'activated_at':now,'baseline_requests':count,'poll_seconds':POLL_SECONDS})))
    return {'enabled':True,'baseline_requests':count,'business_writes':0,'notifications':0}


def stage(conn,key):
    state=document(conn,key,lock=True)
    state.update(dirty=True,state='pending',error='满足审批和物流信息条件后自动同步发货。')
    put(conn,key,state)


def native_details(client,code):
    from .approval_shipping import extract
    data=client._request('GET','/approval/v4/instances/'+quote(code,safe=''),params={'locale':'zh-CN','user_id_type':'open_id'})['data']
    form=json.loads(data.get('form') or '[]')
    rows=[row for field in form if field.get('type')=='fieldList' for row in field.get('value',[])]
    detail=[{f.get('name'):f.get('value') for f in row} for row in rows]
    numbers=[str(row.get('明细编号') or '') for row in detail]
    return {'status':data.get('status'),'code':code,'checked_at':time.time(),'end_time':data.get('end_time'),
            'request_no':next((f.get('value') for f in form if f.get('name') in {'申请单号','物料申请单号'}),None),'line_nos':numbers,
            'lines':[{'line_no':str(row.get('明细编号') or ''),'quantity':row.get('实际发放数量',row.get('审批通过数量',row.get('申请数量')))} for row in detail],
            'shipping':extract(form)}


def approval_passed(native,number):
    return native.get('status')=='APPROVED' and native.get('request_no')==number


def ready(state,native,number):
    if native.get('code')!=state['code'] or not approval_passed(native,number):return False,'审批尚未通过或审批实例与当前申请不匹配。'
    if not state['content']['text'] and not state['content']['images']:return False,'已发货，填写物流文字信息或上传发货图片后通知申请人。'
    return True,''


def flag_due(fields,native):
    import app
    return fields.get('是否发货') is not True and native.get('code')==app.feishu_text(fields,'审批实例Code') and approval_passed(native,app.feishu_text(fields,'申请单号'))


def process_one(key,client):
    import app
    import backend_runtime as runtime
    from . import shipping_calendar as shipping,jobs,effects,approval_shipping as approval
    with connection() as conn:
        if not enabled(conn):return {'state':'disabled'}
        info,lines=graph(conn)
        try:old=repo.raw_record(conn,info,key)
        except ValueError:return {'state':'missing'}
        fields=repo.feishu_record(info,old)['fields']
        if not shipping.eligible(fields):return {'state':'ineligible'}
        current=snapshot(conn,fields,lines.get(old['record_id'],[]));previous=document(conn,old['record_id'])
        cached=previous.get('native') or {}
        import_due=approval.due(previous,cached,current['code'],app.feishu_text(fields,'申请单号'))
        legacy_import=bool(import_due and 'shipping' not in cached)
        changed=current['fingerprint']!=previous.get('fingerprint') or previous.get('dirty')
        poll_native=current['code'] and (not cached or legacy_import or (import_due and previous.get('approval_import_error') and time.time()-cached.get('checked_at',0)>=60) or cached.get('code')!=current['code'] or (cached.get('status')=='PENDING' and time.time()-cached.get('checked_at',0)>=POLL_SECONDS))
        if not changed and not poll_native and not import_due and not flag_due(fields,cached):return {'state':'unchanged'}
        pending=conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state NOT IN ('done','cancelled'))",(info['table_id'],old['record_id'])).fetchone()[0]
        if pending:return {'state':'syncing'}
        dependencies=shipping.schedule_outbox_dependencies(conn,old['record_id'])
    native=native_details(client,current['code']) if current['code'] and (changed or poll_native) else cached
    number=app.feishu_text(fields,'申请单号');passed=approval_passed(native,number)
    import_due=approval.due(previous,native,current['code'],number)
    approval_patch,import_error=approval.prepare(native,fields) if import_due else ({},'')
    if approval_patch:
        fields={**fields,**approval_patch}
        with connection() as conn:current=snapshot(conn,fields,lines.get(old['record_id'],[]))
    allowed,reason=ready(current,native,number)
    # A flag-only historical correction must never generate a historical receipt.
    meaningful=(previous.get('dirty') or previous.get('content')!=current['content']
        or (cached.get('status')=='PENDING' and native.get('status')=='APPROVED')
        or (previous.get('code')!=current['code'] and passed))
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:ordinary',0))")
        latest=repo.raw_record(conn,info,old['record_id'],lock=True)
        if latest['version']!=old['version']:return {'state':'changed_during_check'}
        saved=document(conn,old['record_id'],lock=True)
        signature=digest(current['content'])
        same_notice=(saved.get('effect_id') and saved.get('notice_signature')==signature
                     and (saved.get('notice_approval_code') or (saved.get('native') or {}).get('code'))==native.get('code'))
        flag_needed=passed and fields.get(shipping.SHIPPED) is not True
        notice_needed=bool(allowed and meaningful and not same_notice)
        next_state={**current,'native':native,'dirty':False,'notice_signature':saved.get('notice_signature'),
                    'announced':saved.get('announced',False),'effect_id':saved.get('effect_id'),
                    'logistics_import_code':native.get('code') if import_due and not import_error else saved.get('logistics_import_code'),
                    'approval_import_error':import_error,
                    'notice_approval_code':saved.get('notice_approval_code') or ((saved.get('native') or {}).get('code') if saved.get('effect_id') else None)}
        if not passed:next_state.update(state='waiting_approval',error=reason)
        elif not allowed:next_state.update(state='waiting_information',error=reason)
        elif same_notice:next_state.update(state=saved.get('state','pending'),error=saved.get('error',''))
        else:next_state.update(state='baseline',error='')
        if import_error:next_state.update(error=import_error)
        recipients=app.feishu_person_open_ids(fields,['申请人'])
        if notice_needed and (len(recipients)!=1 or not recipients[0].startswith('ou_')):
            notice_needed=False;next_state.update(state='blocked',error='申请人账号无效，不能发送发货通知。')
        if not flag_needed and not notice_needed and not approval_patch:
            put(conn,old['record_id'],next_state)
            return {'state':next_state['state'],'reason':next_state.get('error','')}
        task,created=jobs.enqueue('发货信息同步','automatic-shipping:v2:'+old['record_id']+':'+str(old['version'])+':'+signature,
            {'request_id':old['record_id'],'request_no':number,'automatic':True,'notify':notice_needed},conn=conn)
        if not created:return {'state':'duplicate'}
        conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
        runtime.request_state.update(_write_conn=conn,_write_actor='system:automatic-shipping',_write_lane='ordinary',_job_id=task.task_id,_effect_ordinal=0)
        if flag_needed or approval_patch:
            from .client import DatabaseWriteClient
            DatabaseWriteClient(conn).update_record(info['table_id'],old['record_id'],{**approval_patch,**({shipping.SHIPPED:True} if flag_needed else {})})
        latest=repo.raw_record(conn,info,old['record_id'])
        outbox=list(dict.fromkeys([*dependencies,*[str(r[0]) for r in conn.execute("SELECT id FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state IN ('pending','retry','processing')",(info['table_id'],old['record_id']))]]))
        result={'request_id':old['record_id'],'request_no':number,'automatic':True,'flag_updated':flag_needed,'approval_import_fields':list(approval_patch),'approval_import_error':import_error,'effect_id':None,'outbox_ids':outbox}
        if notice_needed:
            from .shipping_card import card,date_change_card
            origin=os.environ.get('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work')
            before_date=(saved.get('content') or {}).get('ship_date')
            date_changed=bool(before_date) and before_date!=current['content']['ship_date'] and saved.get('announced',False)
            message=(date_change_card(number,old['record_id'],before_date,current['content']['ship_date'],True,origin) if date_changed
                else card(number,old['record_id'],True,current['content']['ship_date'],current['content']['arrival_start'],current['content']['text'],len(current['content']['images']),origin))
            conn.execute("UPDATE material_ops.effects SET state='done',completed_at=now(),last_error='已被最新发货信息替代，未发送旧通知' WHERE kwargs->>'_shipping_request'=%s AND state IN ('pending','retry') AND first_attempt_at IS NULL",(old['record_id'],))
            alias=effects.defer('primary','send_interactive_message',[recipients[0],message],{
                'receive_id_type':'open_id','_outbox_ids':outbox,'_shipping_request':old['record_id'],'_shipping_version':latest['version'],
                '_automatic_shipping_signature':signature,**({'_shipping_date_change':True,'_shipping_date_before':before_date,'_shipping_date_after':current['content']['ship_date']} if date_changed else {})})
            result['effect_id']=alias[len(effects.PREFIX):]
            next_state.update(notice_signature=signature,notice_approval_code=native.get('code'),state='pending',error='',effect_id=result['effect_id'])
        conn.execute("UPDATE material_ops.jobs SET state='done',result=%s,completed_at=now() WHERE id=%s",(Jsonb(result),task.task_id))
        from .admin_completion import register
        register(conn,task.task_id,'发货信息同步',{'request_no':number},{'entries':[result]},'系统')
        put(conn,old['record_id'],next_state)
        return {'state':'queued' if notice_needed else next_state['state'],**result}


def process_changed(record_id=None,client=None):
    import app
    with connection() as conn:
        if not enabled(conn):return {'state':'disabled'}
        info,by_request=graph(conn)
        if record_id is not None:keys=[record_id]
        else:
            from .shipping_calendar import eligible
            from .approval_shipping import due
            keys=[]
            for row in repo.rows(conn,info):
                if not eligible(row['fields']):continue
                old=document(conn,row['record_id']);native=old.get('native') or {}
                current=snapshot(conn,row['fields'],by_request.get(row['record_id'],[]))
                if due(old,native,current['code'],app.feishu_text(row['fields'],'申请单号')) or flag_due(row['fields'],native) or current['fingerprint']!=old.get('fingerprint') or old.get('dirty') or (current['code'] and (not native or native.get('code')!=current['code'] or (native.get('status')=='PENDING' and time.time()-native.get('checked_at',0)>=POLL_SECONDS))):
                    keys.append(row['record_id'])
    if client is None:client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    results=[]
    def inspect(key):
        try:return process_one(key,client)
        except Exception as exc:
            logging.warning('Automatic shipping check needs retry: %s',type(exc).__name__)
            return {'state':'retry','error_type':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(inspect,keys))
    return {'checked':len(results),'queued':sum(r['state']=='queued' for r in results),'marked':sum(bool(r.get('flag_updated')) for r in results),'retry':sum(r['state']=='retry' for r in results)}


def poll(client=None):
    global _last_poll
    with connection() as conn:
        if not enabled(conn):return {'state':'disabled'}
    if time.monotonic()-_last_poll<POLL_SECONDS:return {'state':'not_due'}
    _last_poll=time.monotonic()
    import app
    from .inbound import refresh
    if client is None:client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    started=time.monotonic()
    refreshed=refresh([app.REQUEST_TABLE_NAME,app.REQUEST_LINE_TABLE_NAME,app.MATERIAL_TABLE_NAME,app.LEDGER_TABLE_NAME],{'primary':client})
    result={'refresh':refreshed,**process_changed(client=client)}
    with connection() as conn:
        conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('automatic-shipping-poll',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",
                     (Jsonb({**result,'completed_at':datetime.now(timezone.utc).isoformat(),'duration_ms':round((time.monotonic()-started)*1000)}),))
    return result


def may_send(conn,key,signature,recipient=None):
    """Recheck current local content immediately before claiming a send effect."""
    import app
    from . import shipping_calendar as shipping
    if not enabled(conn):return False
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    try:row=repo.raw_record(conn,info,key)
    except ValueError:return False
    fields=repo.feishu_record(info,row)['fields'];state=document(conn,row['record_id'])
    _,lines=graph(conn)
    current=snapshot(conn,fields,lines.get(row['record_id'],[]))
    allowed,_=ready(current,state.get('native') or {},app.feishu_text(fields,'申请单号'))
    return (shipping.eligible(fields) and fields.get(shipping.SHIPPED) is True
            and allowed and (recipient is None or app.feishu_person_open_ids(fields,['申请人'])==[recipient])
            and bool(content(conn,fields)['text'] or content(conn,fields)['images'])
            and digest(content(conn,fields))==signature)


def mark_sent(conn,key,effect_id):
    state=document(conn,key,lock=True)
    state['announced']=True
    if state.get('effect_id')==effect_id.replace('-',''):state.update(state='done',error='')
    put(conn,key,state)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--activate',action='store_true');parser.add_argument('--seed-native',type=Path);parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.activate:
        print(json.dumps(activate(seed_native=json.loads(args.seed_native.read_text()) if args.seed_native else None),ensure_ascii=False));return
    if args.once:print(json.dumps(poll(),ensure_ascii=False))


if __name__=='__main__':main()
