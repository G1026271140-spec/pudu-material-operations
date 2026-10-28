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
        if not group['visible']:continue
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
        eligible=(admin or hr) and kind in TYPES[1:] and not row['deleted'] and status==app.CULTURAL_REQUEST_STATUS_ISSUED
        for line in lines:line['can_reject']=bool(eligible and line['status']!=app.CULTURAL_REQUEST_STATUS_REJECTED and line['issued']>0)
        if kind in TYPES[1:] and any(line['status']==app.CULTURAL_REQUEST_STATUS_REJECTED for line in lines) and any(line['status']!=app.CULTURAL_REQUEST_STATUS_REJECTED for line in lines):status='部分驳回'
        items.append({'id':row['record_id'],'number':number,'type':kind,'requester':r['requester'],'department':r['department'],
            'submitted_at':r['submitted_at'],'submitted_date':date_text(f.get('提交时间')),'status':'已撤回 / 已删除' if row['deleted'] else status,
            'review_status':app.feishu_text(f,'库存审查状态'),'ship_date':date_text(f.get('物料发货时间')),
            'arrival_start':date_text(f.get('要求达到开始日期')),'arrival_end':date_text(f.get('要求到达结束日期')),
            'shipped':f.get('是否发货') is True,'shipping_text':app.feishu_text(f,'发货单号及文字信息'),
            'usage':r['material_usage'],'reason':r['request_reason'],'customer':r['customer_name'],'country':r['country'],
            'recipient':r['recipient_info'],'total_rmb':r['request_total_rmb'],'lines':lines,
            'detail_text':app.feishu_text(f,'物料明细文字信息'),'deleted':row['deleted'],
            'can_reject':any(line['can_reject'] for line in lines)})
    notices={number:states for number,states in conn.execute("""SELECT DISTINCT ON (j.payload->'draft'->>'request_no')
        j.payload->'draft'->>'request_no',ARRAY(SELECT e.state FROM material_ops.effects e WHERE e.job_id=j.id)
        FROM material_ops.jobs j WHERE j.task_type=ANY(%s)
        ORDER BY j.payload->'draft'->>'request_no',j.created_at DESC,j.id DESC""",
        ([app.QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,app.QUEUE_TASK_TYPE_CULTURAL_REQUEST_REJECT],))}
    for item in items:
        states=notices.get(item['number'])
        if item['type'] in TYPES[1:] and states is not None:
            item['card_sync']='failed' if 'failed' in states else 'done' if states and all(state=='done' for state in states) else 'pending'
    items.sort(key=lambda row:(row['submitted_date'],row['number']),reverse=True)
    return {'requests':items,'quotas':entitlements(conn,actor,request_rows,line_rows,permission_rows(conn)),
        'mode':'admin' if admin else 'hr' if hr else 'personal','scope':scope,'types':[kind for kind in TYPES if kind in allowed]}


def reject_apparel(actor,body):
    return _reject(actor,body,TYPES[2])


def reject_cultural(actor,body):
    return _reject(actor,body,TYPES[1])


def _reject(actor,body,kind):
    import app,backend_runtime as runtime,hashlib,json
    from . import jobs
    runtime.release_database_snapshot()
    allowed={'request_id','confirmed'}
    if not isinstance(body,dict) or set(body) not in (allowed,allowed|{'line_ids'}) or body['confirmed'] is not True or not isinstance(body['request_id'],str):
        raise ValueError('请先确认要驳回的申领明细。')
    ids=body.get('line_ids')
    if ids is not None and (not isinstance(ids,list) or not 1<=len(ids)<=200 or any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids)):
        raise ValueError('请至少选择一条有效且不重复的明细。')
    with connection() as conn,conn.transaction():
        if not {'HR','管理员'}.intersection(roles_for(conn,actor)):raise PermissionError('仅已启用 HR 或管理员可驳回申领。')
        info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
        raw=repo.raw_record(conn,info,body['request_id']);f=repo.feishu_record(info,raw)['fields']
        if app.feishu_text(f,'申请类型')!=kind:raise ValueError('此操作仅适用于'+kind+'。')
        number=app.feishu_text(f,'申请单号')
        if not number:raise ValueError('申请单缺少单号。')
        if ids is not None:
            keys={raw['record_id'],raw['remote_id']}
            expected_type=app.CORPORATE_APPAREL_LINE_TYPE if kind==TYPES[2] else '文化周边'
            available={row['record_id'] for row in repo.rows(conn,repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME))
                if app.feishu_text(row['fields'],'明细业务类型')==expected_type and keys.intersection(app.feishu_link_ids_any(row['fields'],['所属申请单','申请单']))}
            if not set(ids)<=available:raise ValueError('所选明细不属于当前申请单，请刷新后重试。')
        key=('corporate-apparel-reject:' if kind==TYPES[2] else 'cultural-request-reject:')+number
        if ids is not None:key+=':'+hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('job:'+key,))
        prior=conn.execute('SELECT id,state FROM material_ops.jobs WHERE idempotency_key=%s',(key,)).fetchone()
        if prior:
            job_id=str(prior[0])
            if prior[1]=='failed':raise ValueError('此前的驳回任务失败，请先在系统任务中核对后重试。')
        else:
            status=app.feishu_text(f,'文化周边处理状态')
            if status==app.CULTURAL_REQUEST_STATUS_REJECTED:return {'rejected':True,'already_rejected':True}
            if status!=app.CULTURAL_REQUEST_STATUS_ISSUED:raise ValueError('仅已发放的申领可以驳回。')
            task_type=app.QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT if kind==TYPES[2] else app.QUEUE_TASK_TYPE_CULTURAL_REQUEST_REJECT
            draft={'request_no':number,'operator_open_id':actor,'requester_open_id':next(iter(app.feishu_person_open_ids(f,['申请人'])), '')}
            if ids is not None:draft['line_ids']=sorted(ids)
            task,_=jobs.enqueue(task_type,key,{'draft':draft},conn=conn);job_id=task.task_id
    # The shared worker drains older intents first when another admin submits.
    for _ in range(32):
        processed=jobs.run_one(job_id=job_id,raise_errors=True)
        if processed is None or processed.get('id')==job_id:break
    with connection() as conn:
        state,result=conn.execute('SELECT state,result FROM material_ops.jobs WHERE id=%s',(job_id,)).fetchone()
    return {'job_id':job_id,'state':state,'rejected':state=='done','partial_rejected':bool(result.get('partial_rejected')),'result':result}
