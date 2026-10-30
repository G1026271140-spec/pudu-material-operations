"""Admin inventory lookup and atomic corrections using existing source fields."""
from datetime import datetime,timezone
import hashlib,json
from psycopg import sql
from psycopg.types.json import Jsonb
from . import repository as repo
from .db import connection

KINDS={'ordinary':('普通物料','物料主数据','primary'),
       'cultural':('文化周边','文化周边管理库存','primary'),
       'apparel':('企业文化衫','文化周边编码及库存数量','apparel_admin')}
MAX_QUANTITY=1000000000


def integer(value):
    if isinstance(value,bool):raise ValueError('库存必须为整数。')
    amount=repo.number(value)
    if amount!=int(amount) or abs(amount)>MAX_QUANTITY:raise ValueError('库存必须为范围内的整数。')
    return int(amount)


def info_for(conn,kind):
    if kind not in KINDS:raise ValueError('库存类型无效。')
    _,name,source=KINDS[kind];info=repo.named_table(conn,name,source)
    required={'入库/纠正':2,'原始库存数量':2,'系统兑换数量':2,'最新库存':20} if kind=='apparel' else {'当前库存':2}
    actual={f['field_name']:int(f['type']) for f in info['fields']}
    if any(actual.get(k)!=v for k,v in required.items()):raise ValueError('库存字段定义已变化，请先核对来源。')
    return info


def quantity(fields,kind):
    if kind!='apparel':return integer(fields.get('当前库存'))
    return integer(repo.number(fields.get('原始库存数量'))+repo.number(fields.get('入库/纠正'))
                   -repo.number(fields.get('表格兑换数量'))-repo.number(fields.get('系统兑换数量')))


def row_view(raw,info,kind,regions):
    import app
    f=repo.feishu_record(info,raw)['fields']
    if kind=='apparel':
        if app.feishu_text(f,'物品分类')!='文化衫' or not app.feishu_text(f,'码数') or app.feishu_text(f,'款式').startswith('【说明】'):return None
        category=app.feishu_text(f,'申领显示名称') or app.feishu_text(f,'款式')
        model=app.feishu_text(f,'码数');language='';zone=[];code=app.feishu_text(f,'编码')
    else:
        category=app.feishu_text(f,'物料品类');model=app.feishu_text(f,'产品型号')
        language=app.feishu_text(f,'语种') if kind=='ordinary' else ''
        zone=([app.feishu_text(f,'战区管理')] if kind=='cultural' else [regions.get(key,key) for key in repo.link_ids(f.get('战区管理'))])
        zone=[z for z in zone if z];code=app.feishu_text(f,'物料编码' if kind=='ordinary' else '文化周边编码')
    if not category:return None
    error=''
    try:stock=quantity(f,kind)
    except (ValueError,ArithmeticError):stock=None;error='库存来源数值无效，请先核对源数据。'
    if raw['sync_state']=='conflict':error='此记录存在同步冲突，请先校验来源。'
    return {'kind':kind,'kind_label':KINDS[kind][0],'record_id':raw['record_id'],'table_id':info['table_id'],
            'table_name':info['name'],'source':info['source'],'version':raw['version'],'sync_state':raw['sync_state'],
            'code':code,'category':category,'model':model,'language':language,'regions':zone,
            'quantity':stock,'in_transit':integer(f.get('在途库存')) if kind=='ordinary' else None,
            'editable':not bool(error),'read_only_reason':error}


def region_names(conn):
    import app
    info=repo.named_table(conn,app.REGION_TABLE_NAME);regions={}
    for key,remote,fields in conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields FROM material_data.{} WHERE NOT _deleted').format(sql.Identifier(info['sql_table']))):
        name=app.feishu_text(repo.feishu_record(info,{'record_id':key,'fields':fields})['fields'],'战区名称')
        regions[key]=name
        if remote:regions[remote]=name
    return regions


def all_rows(conn,kind):
    regions=region_names(conn)
    result=[]
    for family in KINDS if kind=='all' else [kind]:
        info=info_for(conn,family)
        # One projection per source, not a separate record/version query per row.
        for key,remote,fields,version,state in conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields,_local_version,_sync_state FROM material_data.{} WHERE NOT _deleted ORDER BY _record_key').format(sql.Identifier(info['sql_table']))):
            row=row_view({'record_id':key,'remote_id':remote,'fields':fields,'version':version,'sync_state':state},info,family,regions)
            if row:result.append(row)
    return result


def catalog(conn,*,kind='all',category='',model='',language='',region='',q='',page=0,limit=50):
    if kind not in {'all',*KINDS}:raise ValueError('库存类型无效。')
    rows=all_rows(conn,kind)
    filters={'category':category,'model':model,'language':language,'region':region}
    def match(row,skip=None):
        return all(not value or key==skip or (value in row['regions'] if key=='region' else row[key]==value) for key,value in filters.items())
    facets={field:sorted({value for row in rows if match(row,field) for value in (row['regions'] if field=='region' else [row[field]]) if value}) for field in filters}
    needle=q.strip().casefold()
    selected=[row for row in rows if match(row) and (not needle or needle in ' '.join([row['code'],row['category'],row['model'],row['language'],*row['regions']]).casefold())]
    selected.sort(key=lambda r:(list(KINDS).index(r['kind']),r['category'],r['model'],r['language'],r['regions'],r['code'],r['record_id']))
    return {'records':selected[page*limit:(page+1)*limit],'count':len(selected),'facets':facets,'page':page,
            'kinds':[{'value':k,'label':v[0]} for k,v in KINDS.items()],'source':'postgresql'}


def save(actor,body):
    import backend_runtime as runtime
    from .client import DatabaseWriteClient
    from .portal_records import roles_for
    from . import jobs
    from .concurrency import check_version
    runtime.release_database_snapshot()
    if not isinstance(body,dict) or set(body)!={'kind','record_id','expected_version','quantity','note','idempotency_key'}:raise ValueError('库存修改数据不完整。')
    kind=body['kind'];key=body['idempotency_key'];record_id=body['record_id']
    if kind not in KINDS or not isinstance(record_id,str) or not 1<=len(record_id)<=150:raise ValueError('库存记录无效。')
    if not isinstance(key,str) or not 8<=len(key)<=150 or type(body['expected_version']) is not int:raise ValueError('缺少有效保存标识或版本。')
    if not isinstance(body['note'],str) or len(body['note'])>1000:raise ValueError('调整说明最多 1000 字。')
    if type(body['quantity']) not in {int,float}:raise ValueError('库存必须为整数。')
    target=integer(body['quantity']);digest=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        lane='ordinary' if kind=='ordinary' else 'cultural'
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('business-lane:'+lane,))
        if '管理员' not in roles_for(conn,actor):raise PermissionError('仅已启用的管理员可以修改库存。')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('stock-adjust:'+key,))
        prior=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',('stock-adjust:'+key,)).fetchone()
        if prior:
            if prior[0]['hash']!=digest or prior[0]['actor']!=actor:raise repo.VersionConflict('保存标识已用于其他修改。')
            return prior[0]['result']
        if kind=='apparel':conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('apparel-management',0))")
        info=info_for(conn,kind);raw=repo.raw_record(conn,info,record_id,lock=True)
        check_version(body['expected_version'],raw['version'],'库存记录版本无效，请刷新后重试。')
        regions=region_names(conn);view=row_view(raw,info,kind,regions)
        if view is None or not view['editable']:raise repo.VersionConflict((view or {}).get('read_only_reason') or '该行不是可编辑的库存规格。')
        before=view['quantity'];delta=target-before
        task,_=jobs.enqueue('库存查询调整','stock-adjust:'+key,{'actor':actor,'kind':kind,'record_id':record_id,'target':target,'hash':digest},conn=conn)
        conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
        runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane=lane,_job_id=task.task_id)
        ledger_id=None
        if delta:
            fields=repo.feishu_record(info,raw)['fields']
            patch={'入库/纠正':integer(repo.number(fields.get('入库/纠正'))+delta)} if kind=='apparel' else {'当前库存':target}
            if kind=='cultural':
                import app
                # Keep the existing manual claimability switch when positive.
                patch=app.cultural_stock_fields(target)
            DatabaseWriteClient(conn,info['source']).update_record(info['table_id'],record_id,patch)
            ledger=repo.named_table(conn,'库存流水')
            values={'发生时间':int(datetime.now(timezone.utc).timestamp()*1000),'流水类型':'库存修正','物料品类':view['category'],
                    '产品型号':view['model'],'语种':view['language'],'数量':delta,'变更前数量':before,'变更后数量':target,
                    '库存变化':delta,'幂等键':'stock-adjust:'+key,'操作人':[{'id':actor}],'操作状态':'有效',
                    '备注':(body['note'].strip() or '虚拟数据库库存调整')+'\n来源：'+info['source']+' / '+info['table_id']+' / '+record_id}
            if kind=='ordinary':values.update({'流水业务类型':'营销物料','物料编码':[record_id]})
            if kind=='cultural':values.update({'流水业务类型':'文化周边','文化周边物料':[record_id],'文化周边战区快照':'、'.join(view['regions'])})
            ledger_id=DatabaseWriteClient(conn).batch_create_records(ledger['table_id'],[values])[0]['record_id']
        latest=repo.raw_record(conn,info,record_id)
        result={'saved':True,'changed':bool(delta),'before':before,'after':target,'delta':delta,'record':row_view(latest,info,kind,regions),
                'task_id':task.task_id,'ledger_id':ledger_id,'outbox_ids':[str(r[0]) for r in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s',(task.task_id,))]}
        conn.execute("UPDATE material_ops.jobs SET state='done',completed_at=now(),result=%s WHERE id=%s",(Jsonb(result),task.task_id))
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',('stock-adjust:'+key,Jsonb({'actor':actor,'hash':digest,'result':result})))
        return result
