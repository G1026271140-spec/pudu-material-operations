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
    for image in images or []:
        if not isinstance(image,dict):continue
        token=image.get('file_token')
        if not token and image.get('local_media_id'):
            row=conn.execute('SELECT feishu_file_token FROM material_ops.media WHERE id=%s',(image['local_media_id'],)).fetchone()
            token=(row[0] if row else None) or image['local_media_id']
        if token:keys.append(str(token))
    return keys


def content(conn,fields):
    import app
    from .shipping_calendar import date_text,TEXT,IMAGES
    return {'text':app.feishu_text(fields,TEXT).strip(),'images':image_keys(conn,fields.get(IMAGES)),
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
    data=client._request('GET','/approval/v4/instances/'+quote(code,safe=''),params={'locale':'zh-CN','user_id_type':'open_id'})['data']
    form=json.loads(data.get('form') or '[]')
    rows=[row for field in form if field.get('type')=='fieldList' for row in field.get('value',[])]
    detail=[{f.get('name'):f.get('value') for f in row} for row in rows]
    numbers=[str(row.get('明细编号') or '') for row in detail]
    return {'status':data.get('status'),'code':code,'checked_at':time.time(),'end_time':data.get('end_time'),
            'request_no':next((f.get('value') for f in form if f.get('name') in {'申请单号','物料申请单号'}),None),'line_nos':numbers,
            'lines':[{'line_no':str(row.get('明细编号') or ''),'quantity':row.get('实际发放数量',row.get('审批通过数量',row.get('申请数量')))} for row in detail]}


def ready(state,native,number):
    if native.get('status')!='APPROVED':return False,'审批尚未通过。'
    if state['source_status']!='已发放' or not state['ready_lines']:return False,'审批明细尚未完整回写，暂不自动发货。'
    expected={r[0] for r in state['lines']}
    if native.get('request_no')!=number or set(native.get('line_nos') or [])!=expected:
        return False,'当前明细与已通过的审批不一致，需要核对。'
    quantities={r['line_no']:int(repo.number(r.get('quantity'))) for r in native.get('lines',[])}
    if any(quantities.get(no)!=quantity for no,_,quantity in state['lines']):
        return False,'实际发放数量与审批结果不一致，需要核对。'
    if not state['content']['text'] and not state['content']['images']:return False,'请填写发货文字信息或上传发货图片。'
    return True,''


def process_one(key,client):
    import app
    import backend_runtime as runtime
    from . import shipping_calendar as shipping,jobs,effects
    with connection() as conn:
        if not enabled(conn):return {'state':'disabled'}
        info,lines=graph(conn)
        try:old=repo.raw_record(conn,info,key)
        except ValueError:return {'state':'missing'}
        fields=repo.feishu_record(info,old)['fields']
        if not shipping.eligible(fields):return {'state':'ineligible'}
        current=snapshot(conn,fields,lines.get(old['record_id'],[]));previous=document(conn,old['record_id'])
        cached=previous.get('native') or {}
        changed=current['fingerprint']!=previous.get('fingerprint') or previous.get('dirty')
        poll_native=current['code'] and (not cached or cached.get('code')!=current['code'] or (cached.get('status')=='PENDING' and time.time()-cached.get('checked_at',0)>=POLL_SECONDS))
        if not changed and not poll_native:return {'state':'unchanged'}
        pending=conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state NOT IN ('done','cancelled'))",(info['table_id'],old['record_id'])).fetchone()[0]
        dependencies=shipping.schedule_outbox_dependencies(conn,old['record_id'])
        if pending or dependencies:return {'state':'syncing'}
        from .approval_sync import line_snapshot
        review=next(f['field_id'] for f in info['fields'] if f['field_name']=='库存审查状态')
        line_snapshot(conn,info,old,{'operation':'update','patch':{review:'已核实库存'}})
    native=native_details(client,current['code']) if current['code'] and (changed or poll_native) else cached
    allowed,reason=ready(current,native,app.feishu_text(fields,'申请单号'))
    meaningful=(previous.get('dirty') or previous.get('content')!=current['content']
        or (previous.get('source_status')!='已发放' and current['source_status']=='已发放')
        or (not previous.get('ready_lines') and current['ready_lines'])
        or (previous.get('state')=='waiting_approval' and cached.get('status')=='PENDING' and native.get('status')=='APPROVED'))
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:ordinary',0))")
        latest=repo.raw_record(conn,info,old['record_id'],lock=True)
        if latest['version']!=old['version']:return {'state':'changed_during_check'}
        saved=document(conn,old['record_id'],lock=True)
        # Another callback may already have handled this exact version.
        if saved.get('fingerprint')==current['fingerprint'] and not saved.get('dirty') and saved.get('notice_signature')==digest(current['content']) and not meaningful:
            saved['native']=native;put(conn,old['record_id'],saved)
            return {'state':'unchanged'}
        next_state={**current,'native':native,'dirty':False,'notice_signature':saved.get('notice_signature'),'state':'blocked','error':reason,'announced':saved.get('announced',False)}
        if not allowed or not meaningful:
            if allowed:next_state.update(state='baseline',error='')
            elif native.get('status')!='APPROVED':next_state['state']='waiting_approval'
            elif current['ready_lines'] and not current['content']['text'] and not current['content']['images']:next_state['state']='waiting_information'
            put(conn,old['record_id'],next_state)
            return {'state':next_state['state'],'reason':reason}
        recipients=app.feishu_person_open_ids(fields,['申请人'])
        if len(recipients)!=1 or not recipients[0].startswith('ou_'):
            next_state.update(state='blocked',error='申请人账号无效，不能发送发货通知。');put(conn,old['record_id'],next_state)
            return {'state':'blocked'}
        number=app.feishu_text(fields,'申请单号');notice_signature=digest(current['content'])
        task,created=jobs.enqueue('发货信息同步','automatic-shipping:'+old['record_id']+':'+str(old['version'])+':'+notice_signature,
            {'request_id':old['record_id'],'request_no':number,'automatic':True},conn=conn)
        if not created:return {'state':'duplicate'}
        conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
        runtime.request_state.update(_write_conn=conn,_write_actor='system:automatic-shipping',_write_lane='ordinary',_job_id=task.task_id,_effect_ordinal=0)
        from .client import DatabaseWriteClient
        DatabaseWriteClient(conn).update_record(info['table_id'],old['record_id'],{shipping.SHIPPED:True})
        latest=repo.raw_record(conn,info,old['record_id'])
        outbox=[str(r[0]) for r in conn.execute("SELECT id FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state IN ('pending','retry','processing')",(info['table_id'],old['record_id']))]
        from .shipping_card import card,date_change_card
        origin=os.environ.get('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work')
        before_date=(saved.get('content') or {}).get('ship_date')
        date_changed=bool(before_date) and before_date!=current['content']['ship_date'] and saved.get('announced',False)
        message=(date_change_card(number,old['record_id'],before_date,current['content']['ship_date'],True,origin) if date_changed
            else card(number,old['record_id'],True,current['content']['ship_date'],current['content']['arrival_start'],current['content']['text'],len(current['content']['images']),origin))
        conn.execute("UPDATE material_ops.effects SET state='done',completed_at=now(),last_error='已被最新发货信息替代，未发送旧通知' WHERE kwargs->>'_shipping_request'=%s AND state IN ('pending','retry') AND first_attempt_at IS NULL",(old['record_id'],))
        alias=effects.defer('primary','send_interactive_message',[recipients[0],message],{
            'receive_id_type':'open_id','_outbox_ids':outbox,'_shipping_request':old['record_id'],'_shipping_version':latest['version'],
            '_automatic_shipping_signature':notice_signature,**({'_shipping_date_change':True,'_shipping_date_before':before_date,'_shipping_date_after':current['content']['ship_date']} if date_changed else {})})
        result={'request_id':old['record_id'],'request_no':number,'automatic':True,'effect_id':alias[len(effects.PREFIX):],'outbox_ids':outbox}
        conn.execute("UPDATE material_ops.jobs SET state='done',result=%s,completed_at=now() WHERE id=%s",(Jsonb(result),task.task_id))
        from .admin_completion import register
        register(conn,task.task_id,'发货信息同步',{'request_no':number},{'entries':[result]},'系统')
        next_state.update(notice_signature=notice_signature,state='pending',error='',effect_id=result['effect_id'])
        put(conn,old['record_id'],next_state)
        return {'state':'queued',**result}


def process_changed(record_id=None,client=None):
    import app
    with connection() as conn:
        if not enabled(conn):return {'state':'disabled'}
        info,by_request=graph(conn)
        if record_id is not None:keys=[record_id]
        else:
            from .shipping_calendar import eligible
            keys=[]
            for row in repo.rows(conn,info):
                if not eligible(row['fields']):continue
                old=document(conn,row['record_id']);native=old.get('native') or {}
                current=snapshot(conn,row['fields'],by_request.get(row['record_id'],[]))
                if current['fingerprint']!=old.get('fingerprint') or old.get('dirty') or (current['code'] and (not native or native.get('code')!=current['code'] or (native.get('status')=='PENDING' and time.time()-native.get('checked_at',0)>=POLL_SECONDS))):
                    keys.append(row['record_id'])
    if client is None:client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    results=[]
    def inspect(key):
        try:return process_one(key,client)
        except Exception as exc:
            logging.warning('Automatic shipping check needs retry: %s',type(exc).__name__)
            return {'state':'retry','error_type':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(inspect,keys))
    return {'checked':len(results),'queued':sum(r['state']=='queued' for r in results),'retry':sum(r['state']=='retry' for r in results)}


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
