"""HR catalog management and claims backed by the administrative source table."""
from __future__ import annotations
import hashlib,json,re
from uuid import uuid4
from urllib.parse import quote
from psycopg.types.json import Jsonb
from . import repository as repo
from .client import DatabaseWriteClient
from .db import connection

KEY='申领款式编号'
LABEL='申领显示名称'
VISIBLE='申领页显示'
LIMIT='每人累计领取上限'
SOURCE_MARKER='企业文化衫行政源记录ID'
STYLE_MARKER='企业文化衫款式编号'

def integer(value,label,*,minimum=None):
    if isinstance(value,bool):raise ValueError(label+'须为整数。')
    amount=repo.number(value)
    if amount!=int(amount) or (minimum is not None and amount<minimum):raise ValueError(label+'数值无效。')
    return int(amount)

def source_info(conn):
    import app
    info=repo.table(conn,app.CORPORATE_APPAREL_SOURCE_TABLE_ID)
    if info['source']!='apparel_admin':raise ValueError('行政源表配置无效。')
    return info

def group_rows(rows):
    import app
    legacy={source:product for product,source in app.CORPORATE_APPAREL_STYLE_MAP.items()}
    groups={}
    for row in rows:
        f=row['fields'];style=app.feishu_text(f,'款式').strip()
        if app.feishu_text(f,'物品分类')!='文化衫' or not style or style.startswith('【说明】'):continue
        key=app.feishu_text(f,KEY).strip() or legacy.get(style) or 'apparel_'+hashlib.sha256(style.encode()).hexdigest()[:20]
        groups.setdefault(key,[]).append(row)
    result=[]
    for key,records in groups.items():
        records.sort(key=lambda row:(bool(app.feishu_text(row['fields'],'码数')),row['record_id']))
        def configured(name,default=''):
            return next((app.feishu_text(row['fields'],name).strip() for row in records if app.feishu_text(row['fields'],name).strip()),default)
        fallback=app.CORPORATE_APPAREL_QUOTA_FIELDS.get(key,((),1))[1]
        try:limit=integer(configured(LIMIT,str(fallback)),LIMIT,minimum=1)
        except ValueError:limit=0
        result.append({'key':key,'source_style':app.feishu_text(records[0]['fields'],'款式'),
            'label':configured(LABEL,key if key in app.CORPORATE_APPAREL_STYLE_MAP else app.feishu_text(records[0]['fields'],'款式')),
            'visible':limit>0 and configured(VISIBLE,'是' if key in app.CORPORATE_APPAREL_STYLE_MAP else '否')=='是',
            'limit':limit,'records':records})
    return sorted(result,key=lambda item:(not item['visible'],item['label']))

def live_groups():
    import app
    return group_rows(app.corporate_apparel_source_client().list_records(app.CORPORATE_APPAREL_SOURCE_TABLE_ID))

def display_name(key):
    return next((g['label'] for g in live_groups() if g['key']==key),key)

def image_items(row):
    result=[]
    for item in row['fields'].get('图片') or []:
        if not isinstance(item,dict):continue
        local=item.get('local_media_id');token=item.get('file_token')
        if not local and not token:continue
        result.append({**item,'name':item.get('name') or '图片',
            'path':'/api/apparel-local-image/'+str(local) if local else '/api/apparel-image/'+quote(row['record_id'],safe='')+'/'+quote(token,safe='')})
    return result

def catalog(synced_rows,source_rows):
    import app
    aliases={app.corporate_apparel_source_record_id(row['fields'].get('SourceID')):row['record_id'] for row in synced_rows}
    items=[];products=[];labels={};limits={}
    for group in group_rows(source_rows):
        if not group['visible']:continue
        key=group['key'];products.append(key);labels[key]=group['label'];limits[key]=group['limit']
        images=next((image_items(row) for row in group['records'] if image_items(row)),[])
        sized=[row for row in group['records'] if app.feishu_text(row['fields'],'码数')]
        for row in sized or group['records']:
            f=row['fields'];pictures=image_items(row) or images
            latest=app.feishu_int(f,'最新库存') if '最新库存' in f else stock_value(f)
            items.append({'record_id':aliases.get(row['record_id'],row['record_id']),'source_record_id':row['record_id'],
                'product':key,'product_label':group['label'],'source_style':group['source_style'],
                'size':app.feishu_text(f,'码数') or '标品','code':app.feishu_text(f,'编码'),
                'latest_inventory':latest,'system_redeemed':app.feishu_int(f,'系统兑换数量'),
                'available':latest,'quota_limit':group['limit'],'images':[image['path'] for image in pictures]})
    items.sort(key=lambda item:(products.index(item['product']),app.cultural_size_sort_key(item['size'])))
    return {'products':products,'items':items,'productLabels':labels,'productLimits':limits}

def stock_value(fields):
    import app
    return app.feishu_int(fields,'原始库存数量')+app.feishu_int(fields,'入库/纠正')-app.feishu_int(fields,'表格兑换数量')-app.feishu_int(fields,'系统兑换数量')

def manager_catalog(conn):
    import app
    info=source_info(conn);rows=repo.rows(conn,info);styles=[]
    for group in group_rows(rows):
        records=[];versions={}
        for row in group['records']:
            raw=repo.raw_record(conn,info,row['record_id']);versions[row['record_id']]=raw['version'];f=row['fields']
            records.append({'record_id':row['record_id'],'version':raw['version'],'sync_state':raw['sync_state'],
                'size':app.feishu_text(f,'码数'),'code':app.feishu_text(f,'编码'),
                'original':app.feishu_int(f,'原始库存数量'),'correction':app.feishu_int(f,'入库/纠正'),
                'external_redeemed':app.feishu_int(f,'表格兑换数量'),'system_redeemed':app.feishu_int(f,'系统兑换数量'),
                'available':stock_value(f),'remark':app.feishu_text(f,'备注')})
        sizes=[item for item in records if item['size']]
        styles.append({k:v for k,v in group.items() if k!='records'}|{'rows':sizes or records,
            'expected_versions':versions,'images':next((image_items(row) for row in group['records'] if image_items(row)),[]),
            'total_stock':sum(item['available'] for item in sizes or records)})
    sizes=next(f for f in info['fields'] if f['field_name']=='码数')
    return {'styles':styles,'sizes':[option['name'] for option in sizes['property']['options']],
        'schema_ready':{KEY,LABEL,VISIBLE,LIMIT}<={f['field_name'] for f in info['fields']}}

def markers(note):
    return {line.split(':',1)[0]:line.split(':',1)[1].strip() for line in str(note or '').splitlines() if ':' in line}

def historical_source_ids(conn):
    import app
    aliases={row['record_id']:app.corporate_apparel_source_record_id(row['fields'].get('SourceID')) for row in repo.rows(conn,repo.named_table(conn,app.CORPORATE_APPAREL_TABLE_NAME))}
    result=set()
    for row in repo.rows(conn,repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)):
        f=row['fields']
        if app.feishu_text(f,'明细业务类型')!=app.CORPORATE_APPAREL_LINE_TYPE:continue
        note=markers(app.feishu_text(f,'备注'));old=note.get(app.CORPORATE_APPAREL_LINE_MARKER,'')
        result.add(note.get(SOURCE_MARKER) or aliases.get(old) or old)
    return result

def save(actor,body):
    import app,backend_runtime as runtime
    runtime.release_database_snapshot()
    key=str(body.get('idempotency_key') or '')
    if not 8<=len(key)<=150:raise ValueError('缺少保存标识。')
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:cultural',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('apparel-management',0))")
        prior=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',('apparel-management:'+key,)).fetchone()
        if prior:
            if prior[0]['hash']!=digest or prior[0]['actor']!=actor:raise repo.VersionConflict('保存标识已用于其他修改。')
            return prior[0]['result']
        info=source_info(conn)
        if not {KEY,LABEL,VISIBLE,LIMIT}<={f['field_name'] for f in info['fields']}:raise ValueError('行政源表的申领设置字段尚未配置。')
        runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane='cultural')
        client=DatabaseWriteClient(conn,'apparel_admin');rows=client.list_records(info['table_id'])
        groups=group_rows(rows);operation=body.get('operation');style_key=str(body.get('style_key') or '')
        old=next((g for g in groups if g['key']==style_key),None)
        if operation not in {'create','edit','delete'}:raise ValueError('不支持的管理操作。')
        if operation!='create' and old is None:raise ValueError('款式不存在，请刷新后重试。')
        old_rows=old['records'] if old else []
        raw_rows={row['record_id']:repo.raw_record(conn,info,row['record_id'],lock=True) for row in old_rows}
        expected=body.get('expected_versions') or {}
        if operation!='create' and expected!={rid:row['version'] for rid,row in raw_rows.items()}:raise repo.VersionConflict('款式或库存已被其他操作修改，请刷新后重新核对。')
        fields_by_id={row['record_id']:row['fields'] for row in rows}
        history=historical_source_ids(conn)
        def removable(rid):
            raw=raw_rows[rid];f=fields_by_id[rid]
            if {rid,raw['remote_id']}&history or app.feishu_int(f,'系统兑换数量') or app.feishu_int(f,'表格兑换数量'):
                raise ValueError('该尺码已有领用历史，不能删除；请下架款式或保留规格。')
            return rid
        if operation=='delete':
            if body.get('confirm_delete')!=old['label']:raise ValueError('请输入款式显示名称确认删除。')
            for rid in raw_rows:removable(rid)
            for rid in raw_rows:client.delete_record(info['table_id'],rid)
            result={'saved':True,'deleted':True,'style_key':style_key}
        else:
            source_style=str(body.get('source_style') or '').strip();label=str(body.get('label') or '').strip()
            if not source_style or not label or len(source_style)>200 or len(label)>120:raise ValueError('请填写有效的行政源表款式名称和申领页显示名称。')
            if type(body.get('visible')) is not bool:raise ValueError('请设置是否在申领页显示。')
            limit=integer(body.get('limit'),LIMIT,minimum=1)
            if limit>9999:raise ValueError('每人累计领取上限不能超过 9999 件。')
            if any(g['key']!=style_key and (g['source_style']==source_style or g['label']==label) for g in groups):raise ValueError('款式或申领页显示名称已存在。')
            if old and source_style!=old['source_style'] and any(app.feishu_int(row['fields'],'表格兑换数量') for row in old_rows):
                raise ValueError('该款式已有行政表兑换记录，不能改动匹配库存的源表款式名称；可修改申领页显示名称。')
            if operation=='create':style_key='apparel_'+uuid4().hex
            size_options={o['name'] for f in info['fields'] if f['field_name']=='码数' for o in f['property']['options']}
            inputs=body.get('rows');prepared=[];seen=set();kept=set()
            if not isinstance(inputs,list) or not inputs:raise ValueError('请至少保留一个尺码。')
            codes={app.feishu_text(row['fields'],'编码'):row['record_id'] for row in rows if app.feishu_text(row['fields'],'编码')}
            for item in inputs:
                rid=str(item.get('record_id') or '');size=str(item.get('size') or '').strip()
                if size not in size_options or size in seen:raise ValueError('请选择有效且不重复的尺码。')
                seen.add(size)
                if rid and rid not in raw_rows:raise ValueError('库存规格不属于当前款式。')
                if rid:
                    before=fields_by_id[rid]
                    if size!=app.feishu_text(before,'码数') and (rid in history or raw_rows[rid]['remote_id'] in history or app.feishu_int(before,'系统兑换数量') or app.feishu_int(before,'表格兑换数量')):
                        raise ValueError('该规格已有领用记录，不能更改尺码；请新增一个尺码规格。')
                    kept.add(rid)
                original=integer(item.get('original'),'原始库存数量',minimum=0);correction=integer(item.get('correction'),'入库/纠正')
                code=str(item.get('code') or '').strip() or 'CF-'+uuid4().hex[:12].upper()
                if len(code)>80 or (code in codes and codes[code]!=rid):raise ValueError('编码已存在或过长。')
                codes[code]=rid or 'new'
                prepared.append((rid,{'物品分类':'文化衫','款式':source_style,'编码':code,'码数':size,
                    '原始库存数量':original,'入库/纠正':correction,'备注':str(item.get('remark') or '')[:20000]}))
            # Parent/header records remain intact when editing their size rows.
            headers={row['record_id'] for row in old_rows if not app.feishu_text(row['fields'],'码数')}
            removed=set(raw_rows)-kept-headers
            for rid in removed:removable(rid)
            config={KEY:style_key,LABEL:label,VISIBLE:'是' if body['visible'] else '否',LIMIT:limit}
            images=None
            if 'images' in body:
                images=[];allowed={item.get('file_token') for row in old_rows for item in row['fields'].get('图片') or [] if isinstance(item,dict)}
                attached_local={item.get('local_media_id') for row in old_rows for item in row['fields'].get('图片') or [] if isinstance(item,dict)}
                if not isinstance(body['images'],list) or len(body['images'])>12:raise ValueError('图片最多 12 张。')
                from .media import load_image
                for item in body['images']:
                    if item.get('local_media_id') and not item.get('file_token'):
                        identity=str(item['local_media_id']);image=load_image(identity,conn=conn)
                        owner=conn.execute('SELECT owner_open_id FROM material_ops.media WHERE id=%s',(identity,)).fetchone()[0]
                        if owner!=actor and identity not in attached_local:raise ValueError('图片不属于当前上传人。')
                        images.append({'local_media_id':identity,'name':image['name'],'type':image['type']})
                    elif item.get('file_token') in allowed:
                        images.append(next(a for row in old_rows for a in row['fields'].get('图片') or [] if a.get('file_token')==item['file_token']))
                    else:raise ValueError('图片附件无效。')
            inherited=next((row['fields'].get('图片') for row in old_rows if row['fields'].get('图片')),[])
            for rid,fields in prepared:
                patch={**fields,**config}
                if images is not None:patch['图片']=images
                if rid:client.update_record(info['table_id'],rid,patch)
                else:
                    patch.update({'系统兑换数量':0,'表格兑换数量':0,'最新库存':fields['原始库存数量']+fields['入库/纠正']})
                    patch.setdefault('图片',inherited)
                    client.batch_create_records(info['table_id'],[patch])
            for rid in headers:client.update_record(info['table_id'],rid,{**config,'款式':source_style,**({'图片':images} if images is not None else {})})
            for rid in removed:client.delete_record(info['table_id'],rid)
            result={'saved':True,'style_key':style_key,'row_count':len(prepared),'sync_status':'pending'}
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',('apparel-management:'+key,Jsonb({'hash':digest,'actor':actor,'result':result})))
        return result

def claim_used(actor,style_key):
    import app
    request_ids={row['record_id'] for row in app.fresh_feishu_rows(app.REQUEST_TABLE_NAME)
        if actor in app.feishu_person_open_ids(row['fields'],['申请人','申请人姓名'])}
    used=0
    for row in app.fresh_feishu_rows(app.REQUEST_LINE_TABLE_NAME):
        f=row['fields']
        if app.feishu_text(f,'明细业务类型')!=app.CORPORATE_APPAREL_LINE_TYPE:continue
        if not request_ids.intersection(app.feishu_link_ids_any(f,['所属申请单','申请单'])):continue
        if markers(app.feishu_text(f,'备注')).get(STYLE_MARKER)!=style_key:continue
        if app.feishu_text(f,'明细状态')==app.CULTURAL_REQUEST_STATUS_REJECTED:continue
        used+=app.feishu_int(f,'实际发放数量') if '实际发放数量' in f else app.feishu_int(f,'申请数量')
    return used

def request_plan(payload,lines):
    import app
    actor=str(payload.get('requester_open_id') or '')
    if not actor.startswith('ou_'):raise ValueError('请选择已关联飞书账号的申请人。')
    app.ensure_requester_sales_permission(payload);app.ensure_corporate_apparel_quota_fields()
    permission=next((row for row in app.fresh_feishu_rows(app.USER_PERMISSION_TABLE_NAME) if actor in app.feishu_person_open_ids(row['fields'],['用户账号','用户','成员'])),None)
    if not permission:raise ValueError('未找到申请人的用户权限记录。')
    groups={g['key']:g for g in live_groups()}
    catalog_items=catalog(app.fresh_feishu_rows(app.CORPORATE_APPAREL_TABLE_NAME),app.corporate_apparel_source_client().list_records(app.CORPORATE_APPAREL_SOURCE_TABLE_ID))['items']
    items={(item['product'],item['size']):item for item in catalog_items};seen=set();totals={};prepared=[]
    for line in lines:
        key=str(line.get('product') or '');size=str(line.get('size') or line.get('model') or '')
        quantity=integer(line.get('quantity'),'领取数量',minimum=1);group=groups.get(key)
        if not group or not group['visible'] or (key,size) in seen:raise ValueError('款式已下架或申领明细无效，请刷新后重试。')
        seen.add((key,size));item=items.get((key,size))
        if not item or item['available']<quantity:raise ValueError(group['label']+' / '+size+' 可领取库存不足。')
        prepared.append({**item,'quantity':quantity,'target_system_redeemed':item['system_redeemed']+quantity})
        totals[key]=totals.get(key,0)+quantity
    if not prepared:raise ValueError('请至少选择一件企业文化衫。')
    quota=[]
    for key,quantity in totals.items():
        if key in app.CORPORATE_APPAREL_QUOTA_FIELDS:
            field,_=app._corporate_apparel_quota_field(key);current=app.feishu_int(permission['fields'],field)
        else:field='';current=claim_used(actor,key)
        quota.append({'product':groups[key]['label'],'field':field,'current':current,'requested':quantity,'target':current+quantity,'limit':groups[key]['limit']})
    exceeded=[item for item in quota if item['target']>item['limit']]
    return {'permission_record_id':permission['record_id'],'quota_allowed':not exceeded,'quota_exceeded':exceeded,'quota_targets':quota,'items':prepared if not exceeded else []}

def rejection_plan(request_no,operator):
    import app
    if operator not in set(app.enabled_role_open_ids('HR'))|set(app.enabled_admin_open_ids()):raise PermissionError('仅 HR 和管理员可驳回企业文化衫申领。')
    context=app.corporate_apparel_request_context(request_no);request=context['request']
    if request['status']==app.CULTURAL_REQUEST_STATUS_REJECTED:return {'already_rejected':True,'context':context,'stock_targets':[],'quota_targets':[]}
    source_rows=app.corporate_apparel_source_client().list_records(app.CORPORATE_APPAREL_SOURCE_TABLE_ID)
    source={row['record_id']:row for row in source_rows}
    aliases={row['record_id']:app.corporate_apparel_source_record_id(row['fields'].get('SourceID')) for row in app.fresh_feishu_rows(app.CORPORATE_APPAREL_TABLE_NAME)}
    targets=[];totals={}
    for item in context['lines']:
        source_id=item.get('source_record_id') or aliases.get(item['record_id']) or item['record_id']
        row=source.get(source_id)
        if not row:raise ValueError('申领记录对应的行政源库存不存在。')
        group=group_rows([row])[0];key=item.get('style_key') or group['key'];quantity=int(item['quantity'])
        totals[key]=totals.get(key,0)+quantity
        targets.append({**item,'source_record_id':source_id,'target_system_redeemed':max(0,app.feishu_int(row['fields'],'系统兑换数量')-quantity)})
    permission=next((row for row in app.fresh_feishu_rows(app.USER_PERMISSION_TABLE_NAME) if request['requester_open_id'] in app.feishu_person_open_ids(row['fields'],['用户账号','用户','成员'])),None)
    if not permission:raise ValueError('未找到申请人权限记录。')
    quota=[]
    for key,quantity in totals.items():
        if key not in app.CORPORATE_APPAREL_QUOTA_FIELDS:continue
        field,_=app._corporate_apparel_quota_field(key)
        quota.append({'field':field,'target':max(0,app.feishu_int(permission['fields'],field)-quantity)})
    return {'already_rejected':False,'context':context,'permission_record_id':permission['record_id'],'stock_targets':targets,'quota_targets':quota}
