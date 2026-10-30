"""Frozen, local-only order/packing exports. Never registers procurement or stock."""
from collections import defaultdict
from datetime import date,datetime,timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID,uuid4
import json,os
from psycopg import sql
from psycopg.types.json import Jsonb
from . import repository as repo
from .db import connection

TASK='下单分装表生成'
PREFIX='order-packing:'
MAX_REQUESTS=2000
MAX_ROWS=50000


def digest(value):return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def text(value,label,limit=1000,required=False):
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    if not isinstance(value,str) or len(value)>limit or ILLEGAL_CHARACTERS_RE.search(value):raise ValueError(label+'格式无效或过长。')
    value=value.strip()
    if required and not value:raise ValueError('请填写'+label+'。')
    return value


def quantity(value):
    if type(value) is not int or not 1<=value<=1000000:raise ValueError('数量必须为 1～1000000 的整数。')
    return value


def rows(conn,info):
    return [dict(repo.feishu_record(info,{'record_id':key,'fields':fields}),remote_id=remote,version=version)
        for key,remote,fields,version in conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields,_local_version FROM material_data.{} WHERE NOT _deleted ORDER BY _record_key').format(sql.Identifier(info['sql_table'])))]


def read_source(conn):
    import app
    from .shipping_calendar import date_text,eligible
    infos={name:repo.named_table(conn,name) for name in [app.REQUEST_TABLE_NAME,app.REQUEST_LINE_TABLE_NAME,app.MATERIAL_TABLE_NAME,app.CATEGORY_TABLE_NAME]}
    categories=rows(conn,infos[app.CATEGORY_TABLE_NAME]);material_raw=rows(conn,infos[app.MATERIAL_TABLE_NAME])
    material=repo.business_rows(conn,infos[app.MATERIAL_TABLE_NAME],material_raw)
    categories_by_key={app.normalize_category_match_key(app.feishu_text(r['fields'],'物料品类')):r for r in categories}
    categories_by_id={identity:r for r in categories for identity in [r['record_id'],r['remote_id']] if identity}
    stock={};products=defaultdict(list)
    for row in material:
        f=row['fields'];name=app.feishu_text(f,'物料品类')
        cat=next((categories_by_id[k] for k in repo.link_ids(f.get('品类关联')) if k in categories_by_id),categories_by_key.get(app.normalize_category_match_key(name)))
        if not cat or app.feishu_text(cat['fields'],'品类定义')!=app.CATEGORY_DEFINITION_PRINT:continue
        cf=cat['fields'];name=app.feishu_text(cf,'物料品类')
        item={'material_id':row['record_id'],'code':app.feishu_text(f,'物料编码'),'category':name,
              'category_display':app.feishu_text(cf,'中文页面名称') or name,'model':app.feishu_text(f,'产品型号') or app.NO_MODEL_TEXT,
              'language':app.feishu_text(f,'语种') or app.NO_LANGUAGE_TEXT}
        for identity in [row['record_id'],row.get('remote_id')]:
            if identity:stock[identity]=item
        products[cat['record_id']].append(item)
    product_list=[]
    for cid,items in products.items():
        cat=categories_by_id[cid];cf=cat['fields'];images=[]
        for image in cf.get(app.REQUEST_CATEGORY_IMAGE_FIELD) or []:
            if image.get('local_media_id'):images.append('/api/database-image/'+image['local_media_id'])
            elif image.get('file_token'):images.append('/api/live-image/'+app.CATEGORY_TABLE_NAME+'/'+cid+'/'+image['file_token'])
        product_list.append({'id':cid,'name':app.feishu_text(cf,'物料品类'),'display':app.feishu_text(cf,'中文页面名称') or app.feishu_text(cf,'物料品类'),'images':images,'options':sorted(items,key=lambda x:(x['model'],x['language'],x['code']))})
    request_rows=rows(conn,infos[app.REQUEST_TABLE_NAME]);line_rows=rows(conn,infos[app.REQUEST_LINE_TABLE_NAME])
    by_request={identity:r for r in request_rows for identity in [r['record_id'],r['remote_id']] if identity}
    by_number=defaultdict(list)
    for r in request_rows:by_number[app.feishu_text(r['fields'],'申请单号')].append(r)
    grouped=defaultdict(list);warnings=defaultdict(list);line_versions=defaultdict(list)
    for row in line_rows:
        f=row['fields'];parents={by_request[k]['record_id'] for k in app.feishu_link_ids_any(f,['所属申请单','申请单']) if k in by_request}
        if not parents:
            matches=by_number.get(app.feishu_text(f,'申请单号'),[])
            if len(matches)==1:parents={matches[0]['record_id']}
        if not parents:continue
        if len(parents)!=1:
            for parent in parents:warnings[parent].append('明细关联了多个申请单，需先核对。')
            continue
        parent=next(iter(parents));line_versions[parent].append((row['record_id'],row['version']))
        if app.feishu_text(f,'明细状态') in {'已驳回','已撤回','已取消','已删除'}:continue
        links=app.feishu_link_ids_any(f,['物料','物料编码']);item=stock.get(links[0]) if len(links)==1 else None
        product=app.feishu_text_any(f,['实际发放物料品类','品类名称','物料品类','品类'])
        cat=categories_by_key.get(app.normalize_category_match_key(product))
        if not item and (not cat or app.feishu_text(cat['fields'],'品类定义')!=app.CATEGORY_DEFINITION_PRINT):continue
        amount=app.feishu_int(f,'实际发放数量')
        if amount<=0:amount=app.feishu_int(f,'审批通过数量') if '审批通过数量' in f else app.feishu_int(f,'申请数量')
        if amount<=0:continue
        if not item:
            warnings[parent].append('印刷明细 '+(app.feishu_text(f,'明细编号') or row['record_id'])+' 缺少唯一有效物料关联。');continue
        grouped[parent].append({**item,'line_id':row['record_id'],'quantity':amount,'remark':app.feishu_text(f,'备注'),'source':'request'})
    requests=[]
    for row in request_rows:
        f=row['fields'];key=row['record_id'];number=app.feishu_text(f,'申请单号')
        if not number or not eligible(f):continue
        usage=app.feishu_text_any(f,['物料用途','用途/活动','用途|活动']) or app.request_note_values(f).get('物料用途','')
        lines=sorted(grouped[key],key=lambda x:(x['category'],x['model'],x['language'],x['line_id']))
        item={'request_id':key,'request_no':number,'requester':app.request_applicant_text(f),'usage':usage,
              'department':app.feishu_text_any(f,['申请部门','申请部门/区域']),'status':app.feishu_text(f,'审批状态'),
              'ship_date':date_text(f.get('物料发货时间')),'arrival_start':date_text(f.get('要求达到开始日期')),
              'order_date':date_text(f.get('需要下单日期')),'submitted_at':date_text(f.get('提交时间')),
              'lines':lines,'quantity':sum(x['quantity'] for x in lines),'warnings':warnings[key],
              'selectable':bool(lines) and not warnings[key]}
        item['fingerprint']=digest({'request':item,'header_version':row['version'],'line_versions':sorted(line_versions[key])})
        requests.append(item)
    requests.sort(key=lambda r:(r['submitted_at'],r['request_no']),reverse=True)
    return {'requests':requests,'products':sorted(product_list,key=lambda x:x['name'])},stock


def prepare(conn,body):
    allowed={'request_ids','fingerprints','extras','generation_date'}
    if not isinstance(body,dict) or set(body)!=allowed:raise ValueError('导出参数不完整。')
    day=body['generation_date']
    if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:raise ValueError('请选择有效生成日期。')
    ids=body['request_ids'];extras=body['extras'];versions=body['fingerprints']
    if not isinstance(ids,list) or len(ids)>MAX_REQUESTS or any(not isinstance(k,str) for k in ids) or len(set(ids))!=len(ids):raise ValueError('申请单选择无效或重复，一次最多选择 2000 张。')
    if not isinstance(versions,dict) or set(versions)!=set(ids):raise ValueError('申请单版本不完整，请刷新。')
    if not isinstance(extras,list) or len(extras)>2000:raise ValueError('额外物料最多 2000 条。')
    if not ids and not extras:raise ValueError('请先选择申请单或添加额外物料。')
    data,stock=read_source(conn);requests={r['request_id']:r for r in data['requests']};selected=[];flat=[]
    for key in ids:
        request=requests.get(key)
        if not request or not request['selectable']:raise repo.VersionConflict('所选申请已失效、没有印刷物料或明细需核对，请刷新后重新选择。')
        if versions[key]!=request['fingerprint']:raise repo.VersionConflict('申请 '+request['request_no']+' 已发生变化，请刷新后重新预览。')
        selected.append({k:request[k] for k in ['request_id','request_no','requester','usage','fingerprint']})
        for line in request['lines']:
            flat.append({**line,'group_id':key,'request_no':request['request_no'],'usage':request['usage'],
                         'group_label':request['request_no']+' / '+request['requester']+'\n'+(request['usage'] or '未填写用途')})
    seen=set()
    for item in extras:
        if not isinstance(item,dict) or set(item)!={'id','source','material_id','category','model','language','quantity','usage','remark'}:raise ValueError('额外物料字段无效。')
        identity=text(item['id'],'额外物料标识',100,True)
        if identity in seen:raise ValueError('额外物料标识重复。')
        seen.add(identity);amount=quantity(item['quantity']);usage=text(item['usage'],'用途',1000,True);remark=text(item['remark'],'制作备注',1000)
        if item['source']=='catalog':
            material_id=text(item['material_id'],'物料标识',150,True)
            if material_id not in stock:raise repo.VersionConflict('额外物料已失效或不属于印刷物料，请重新选择。')
            spec=stock[material_id]
        elif item['source']=='custom':
            spec={'category':text(item['category'],'自定义品类',200,True),'model':text(item['model'],'型号',200) or '无需型号',
                  'language':text(item['language'],'语种',200) or '无需语种','code':'','material_id':''}
            spec['category_display']=spec['category']
        else:raise ValueError('额外物料来源无效。')
        flat.append({**spec,'quantity':amount,'usage':usage,'remark':remark,'group_id':'extra:'+usage,
                     'group_label':'额外物料\n'+usage,'request_no':'','line_id':identity,'source':item['source']})
    if len(flat)>MAX_ROWS:raise ValueError('明细过多，请拆成多批生成。')
    snapshot={'generation_date':day,'requests':selected,'lines':flat,'request_count':len(selected),'extra_count':len(extras)}
    return snapshot


def views(snapshot):
    ordered={};groups={}
    for line in snapshot['lines']:
        key=(line['material_id'] or 'custom:'+digest([line['category'],line['model'],line['language']]),line['remark'])
        if key not in ordered:ordered[key]={'category':line.get('category_display') or line['category'],'model':line['model'],'language':line['language'],'parts':[]}
        row=ordered[key]
        row['parts'].append((line['quantity'],str(line['quantity'])+'件 '+(line['request_no']+' ' if line['request_no'] else '')+line['usage']))
        group=groups.setdefault(line['group_id'],{'label':line['group_label'],'rows':[]})
        group['rows'].append({'category':line.get('category_display') or line['category'],'model':line['model'],'language':line['language'],'quantity':line['quantity'],'remark':line['remark']})
    orders=[]
    for key,row in ordered.items():
        chunks=[];parts=[];length=0
        for amount,purpose in row['parts']:
            if parts and (len(parts)>=12 or length+len(purpose)>1800):chunks.append(parts);parts=[];length=0
            parts.append((amount,purpose));length+=len(purpose)
        if parts:chunks.append(parts)
        for chunk in chunks:
            orders.append({**{k:v for k,v in row.items() if k!='parts'},'quantity':sum(x[0] for x in chunk),
                           'usage':'\n'.join(x[1] for x in chunk)+ ('\n制作备注：'+key[1] if key[1] else '')})
    orders.sort(key=lambda x:(x['category'],x['model'],x['language'],x['usage']))
    packing=list(groups.values())
    left=sum(row['quantity'] for row in orders);right=sum(row['quantity'] for group in packing for row in group['rows'])
    if left!=right:raise ValueError('下单与分装数量核对失败。')
    return {'orders':orders,'packing':packing,'quantity':left,'specifications':len(ordered),'request_count':snapshot['request_count'],'extra_count':snapshot['extra_count'],'generation_date':snapshot['generation_date']}


def history(conn,limit=30):
    return [dict(zip(['id','state','created_at','completed_at','error','result'],[str(v) if i in {0,2,3} and v is not None else v for i,v in enumerate(row)]))
            for row in conn.execute('SELECT id,state,created_at,completed_at,last_error,result FROM material_ops.jobs WHERE task_type=%s ORDER BY created_at DESC LIMIT %s',(TASK,limit))]


def enqueue(actor,body):
    import backend_runtime as runtime
    from .portal_records import roles_for
    from . import jobs
    runtime.release_database_snapshot()
    if not isinstance(body,dict) or 'idempotency_key' not in body or 'preview_hash' not in body:raise ValueError('缺少生成标识，请重新预览。')
    if not isinstance(body['idempotency_key'],str) or not isinstance(body['preview_hash'],str):raise ValueError('生成标识无效。')
    token=str(UUID(body['idempotency_key']));content={k:v for k,v in body.items() if k not in {'idempotency_key','preview_hash'}};hash_value=digest(body)
    with connection() as conn:
        nested=conn.info.transaction_status.name!='IDLE'
        conn.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(PREFIX+token,))
        try:
            with conn.transaction():
                if not nested:conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
                if '管理员' not in roles_for(conn,actor):raise PermissionError('仅已启用管理员可生成下单分装表。')
                prior=conn.execute('SELECT id,payload FROM material_ops.jobs WHERE idempotency_key=%s',(PREFIX+token,)).fetchone()
                if prior:
                    if prior[1].get('actor')!=actor or prior[1].get('hash')!=hash_value:raise repo.VersionConflict('生成标识已用于其他内容。')
                    return {'task_id':str(prior[0]),'reused':True}
                # A single snapshot verifies all selected versions before freezing.
                snapshot=prepare(conn,content)
                if body['preview_hash']!=digest(snapshot):raise repo.VersionConflict('预览内容已变化，请重新预览后生成。')
                result=views(snapshot)
                task,_=jobs.enqueue(TASK,PREFIX+token,{'actor':actor,'hash':hash_value,'generation_date':snapshot['generation_date'],'request_count':len(snapshot['requests'])},conn=conn)
                conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',(PREFIX+task.task_id,Jsonb(snapshot)))
                return {'task_id':task.task_id,'reused':False,'summary':{k:result[k] for k in ['quantity','specifications','request_count','extra_count','generation_date']}}
        finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(PREFIX+token,))


def root():
    import backend_runtime as runtime
    media=Path(os.environ.get('PUDU_MEDIA_ROOT') or runtime.ROOT/'shared/media')
    return Path(os.environ.get('PUDU_ORDER_PACKING_EXPORT_ROOT') or media/'order-packing-exports').resolve()


def execute(conn,task_id,payload):
    from .order_packing_xlsx import workbook,template_sha256
    row=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(PREFIX+str(task_id),)).fetchone()
    if not row:raise ValueError('导出快照不存在。')
    snapshot=row[0];summary=views(snapshot)
    conn.execute('UPDATE material_ops.jobs SET result=%s WHERE id=%s',(Jsonb({'stage':'building','generation_date':snapshot['generation_date'],'request_count':snapshot['request_count']}),task_id))
    data=workbook(summary);folder=root();folder.mkdir(parents=True,exist_ok=True)
    path=folder/(str(UUID(str(task_id)))+'.xlsx');temporary=folder/(str(uuid4())+'.tmp')
    try:temporary.write_bytes(data);temporary.chmod(0o600);temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
    day=date.fromisoformat(snapshot['generation_date'])
    return {'filename':f'{day.month}月{day.day}日营销物料下单与分装.xlsx','generation_date':snapshot['generation_date'],
            'quantity':summary['quantity'],'specifications':summary['specifications'],'request_count':snapshot['request_count'],
            'extra_count':snapshot['extra_count'],'size':len(data),'sha256':sha256(data).hexdigest(),'template_sha256':template_sha256()}


def download(conn,task_id):
    identity=str(UUID(task_id));row=conn.execute('SELECT state,result FROM material_ops.jobs WHERE id=%s AND task_type=%s',(identity,TASK)).fetchone()
    if not row or row[0]!='done':raise LookupError('文件尚未生成或不存在。')
    path=root()/(identity+'.xlsx')
    if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=row[1].get('sha256'):raise LookupError('导出文件缺失或校验失败，请核对后台任务。')
    return path,row[1]['filename']
