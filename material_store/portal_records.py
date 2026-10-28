"""Owner/HR/admin history and apparel entitlements from PostgreSQL."""
from __future__ import annotations
from collections import Counter,defaultdict
from psycopg import sql
from . import repository as repo,apparel
from .shipping_calendar import date_text
from .db import connection

TYPES=('普通物料申请','文化周边申请','企业文化衫领取')

def records(conn,info,*,deleted=False):
    rows=conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields,_deleted,_local_version,_sync_state FROM material_data.{} {}').format(sql.Identifier(info['sql_table']),sql.SQL('' if deleted else 'WHERE NOT _deleted')) + sql.SQL(' ORDER BY _record_key')).fetchall()
    return [dict(repo.feishu_record(info,{'record_id':r[0],'fields':r[2]}),remote_id=r[1],deleted=r[3],version=r[4],sync_state=r[5]) for r in rows]

def permission_rows(conn):
    import app
    return records(conn,repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME))

def roles_for(conn,actor):
    import app
    roles=set()
    for row in permission_rows(conn):
        f=row['fields']
        if actor in app.feishu_person_open_ids(f,['用户账号']) and app.feishu_permission_enabled(f):
            roles.update(app.feishu_choice_values(f,'角色'))
    return roles

def entitlements(conn,actor,request_rows,line_rows,permissions):
    import app
    groups=apparel.group_rows(repo.rows(conn,apparel.source_info(conn)))
    own_ids={identity for row in request_rows if not row['deleted'] and actor in app.feishu_person_open_ids(row['fields'],['申请人']) for identity in (row['record_id'],row.get('remote_id')) if identity}
    used=Counter()
    for row in line_rows:
        f=row['fields']
        if row['deleted'] or app.feishu_text(f,'明细业务类型')!=app.CORPORATE_APPAREL_LINE_TYPE or not own_ids.intersection(app.feishu_link_ids_any(f,['所属申请单','申请单'])):continue
        if app.feishu_text(f,'明细状态')==app.CULTURAL_REQUEST_STATUS_REJECTED:continue
        key=apparel.markers(app.feishu_text(f,'备注')).get(apparel.STYLE_MARKER)
        if key:used[key]+=app.feishu_int(f,'实际发放数量') if '实际发放数量' in f else app.feishu_int(f,'申请数量')
    own_permission=next((row['fields'] for row in permissions if actor in app.feishu_person_open_ids(row['fields'],['用户账号'])),{})
    result=[]
    for group in groups:
        key=group['key'];current=used[key]
        if key in app.CORPORATE_APPAREL_QUOTA_FIELDS:
            aliases,_=app.CORPORATE_APPAREL_QUOTA_FIELDS[key]
            current=app.feishu_int(own_permission,next((name for name in aliases if name in own_permission),aliases[0]))
        result.append({'key':key,'name':group['label'],'limit':group['limit'],'used':current,'remaining':max(0,group['limit']-current),'visible':group['visible']})
    return result

def history(conn,actor,scope='mine'):
    import app
    if scope not in {'mine','all'}:raise ValueError('无效的查看范围。')
    roles=roles_for(conn,actor);admin='管理员' in roles;hr=not admin and 'HR' in roles
    if scope=='all' and not (admin or hr):raise PermissionError('只能查看本人的申请记录。')
    allowed=set(TYPES[1:] if hr else TYPES)
    request_rows=records(conn,repo.named_table(conn,app.REQUEST_TABLE_NAME),deleted=True)
    line_rows=records(conn,repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME),deleted=True)
    counts=Counter(app.feishu_text(row['fields'],'申请单号') for row in request_rows)
    by_link=defaultdict(list);by_no=defaultdict(list)
    for row in line_rows:
        f=row['fields'];links=app.feishu_link_ids_any(f,['所属申请单','申请单'])
        for key in links:by_link[key].append(row)
        number=app.feishu_text(f,'申请单号')
        if not links and number and counts[number]==1:by_no[number].append(row)
    items=[]
    for row in request_rows:
        f=row['fields'];kind=app.feishu_text(f,'申请类型')
        if kind not in allowed:continue
        if scope=='mine' and actor not in app.feishu_person_open_ids(f,['申请人']):continue
        parsed=app.load_feishu_request_records([row])
        if not parsed:continue
        r=parsed[0];number=r['request_no'];linked={item['record_id']:item for item in [*by_link[row['record_id']],*by_link[row.get('remote_id')],*by_no[number]]}
        lines=[]
        for line in linked.values():
            values=line['fields']
            lines.append({'id':line['record_id'],'product':app.feishu_text_any(values,['品类名称','实际发放物料品类','物料品类','品类']),
                'model':app.feishu_text_any(values,['产品型号名称','实际发放产品型号','产品型号']),
                'dimension':app.feishu_text_any(values,['语种名称','文化周边战区','实际发放语种','语种']),
                'quantity':app.feishu_int(values,'申请数量'),'approved':app.feishu_int(values,'审批通过数量'),
                'issued':app.feishu_int(values,'实际发放数量'),'status':app.feishu_text(values,'明细状态'),
                'remark':app.feishu_text(values,'备注') if kind!=TYPES[2] else ''})
        status=app.feishu_text(f,'文化周边处理状态') if kind in TYPES[1:] else r['status']
        items.append({'id':row['record_id'],'number':number,'type':kind,'requester':r['requester'],'department':r['department'],
            'submitted_at':r['submitted_at'],'submitted_date':date_text(f.get('提交时间')),'status':'已撤回 / 已删除' if row['deleted'] else status,
            'review_status':app.feishu_text(f,'库存审查状态'),'ship_date':date_text(f.get('物料发货时间')),
            'arrival_start':date_text(f.get('要求达到开始日期')),'arrival_end':date_text(f.get('要求到达结束日期')),
            'shipped':f.get('是否发货') is True,'shipping_text':app.feishu_text(f,'发货单号及文字信息'),
            'usage':r['material_usage'],'reason':r['request_reason'],'customer':r['customer_name'],'country':r['country'],
            'recipient':r['recipient_info'],'total_rmb':r['request_total_rmb'],'lines':lines,
            'detail_text':app.feishu_text(f,'物料明细文字信息'),'deleted':row['deleted'],
            'can_reject':(admin or hr) and kind==TYPES[2] and not row['deleted'] and status==app.CULTURAL_REQUEST_STATUS_ISSUED})
    notices={number:states for number,states in conn.execute("SELECT j.payload->'draft'->>'request_no',array_remove(array_agg(e.state),NULL) FROM material_ops.jobs j LEFT JOIN material_ops.effects e ON e.job_id=j.id WHERE j.task_type=%s GROUP BY j.id",(app.QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,))}
    for item in items:
        states=notices.get(item['number'])
        if item['type']==TYPES[2] and states is not None:
            item['card_sync']='failed' if 'failed' in states else 'done' if states and all(state=='done' for state in states) else 'pending'
    items.sort(key=lambda row:(row['submitted_date'],row['number']),reverse=True)
    return {'requests':items,'quotas':entitlements(conn,actor,request_rows,line_rows,permission_rows(conn)),
        'mode':'admin' if admin else 'hr' if hr else 'personal','scope':scope,'types':[kind for kind in TYPES if kind in allowed]}


def reject_apparel(actor,body):
    import app,backend_runtime as runtime
    from . import jobs
    runtime.release_database_snapshot()
    if not isinstance(body,dict) or set(body)!={'request_id','confirmed'} or body['confirmed'] is not True or not isinstance(body['request_id'],str):
        raise ValueError('请先确认要驳回的企业文化衫申领。')
    with connection() as conn,conn.transaction():
        if not {'HR','管理员'}.intersection(roles_for(conn,actor)):raise PermissionError('仅已启用 HR 或管理员可驳回企业文化衫申领。')
        info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
        raw=repo.raw_record(conn,info,body['request_id']);f=repo.feishu_record(info,raw)['fields']
        if app.feishu_text(f,'申请类型')!=TYPES[2]:raise ValueError('此操作仅适用于企业文化衫申领。')
        number=app.feishu_text(f,'申请单号');key='corporate-apparel-reject:'+number
        if not number:raise ValueError('申请单缺少单号。')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('job:'+key,))
        prior=conn.execute('SELECT id,state FROM material_ops.jobs WHERE idempotency_key=%s',(key,)).fetchone()
        if prior:
            job_id=str(prior[0])
            if prior[1]=='failed':raise ValueError('此前的驳回任务失败，请先在系统任务中核对后重试。')
        else:
            status=app.feishu_text(f,'文化周边处理状态')
            if status==app.CULTURAL_REQUEST_STATUS_REJECTED:return {'rejected':True,'already_rejected':True}
            if status!=app.CULTURAL_REQUEST_STATUS_ISSUED:raise ValueError('仅已发放的企业文化衫申领可以驳回。')
            task,_=jobs.enqueue(app.QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,key,{'draft':{'request_no':number,'operator_open_id':actor}},conn=conn)
            job_id=task.task_id
    jobs.run_one(job_id=job_id,raise_errors=True)
    with connection() as conn:
        state,result=conn.execute('SELECT state,result FROM material_ops.jobs WHERE id=%s',(job_id,)).fetchone()
    return {'job_id':job_id,'state':state,'rejected':state=='done','result':result}
