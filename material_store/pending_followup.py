"""Administrator follow-up labels; never confirm, approve or change inventory."""
from psycopg import sql
from psycopg.types.json import Jsonb
import backend_runtime as runtime
from .db import connection
from . import repository as repo,jobs
from .client import DatabaseWriteClient
from .concurrency import check_version

LABEL='待核实标签'
NOTE='待核实备注'


def fields(info):
    result={f['field_name']:f for f in info['fields'] if f['field_name'] in {LABEL,NOTE}}
    if set(result)!={LABEL,NOTE} or any(f['type']!=1 for f in result.values()):
        raise ValueError('待核实标签字段尚未准备好，请联系管理员。')
    return result


def summary(info,row):
    import app
    values=repo.feishu_record(info,row)['fields']
    return {'requestId':row['record_id'],'recordVersion':row['version'],
        'reviewLabel':app.feishu_text(values,LABEL),'reviewNote':app.feishu_text(values,NOTE)}


def decorate(conn,requests):
    import app
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    keys=[r['requestId'] for r in requests]
    rows=conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields,_local_version FROM material_data.{} '
        'WHERE NOT _deleted AND (_record_key=ANY(%s) OR _remote_id=ANY(%s))').format(sql.Identifier(info['sql_table'])),(keys,keys)).fetchall() if keys else []
    details={}
    for key,remote,values,version in rows:
        item=summary(info,{'record_id':key,'fields':values,'version':version})
        details[key]=item
        if remote:details[remote]=item
    return [{**r,**details.get(r['requestId'],{})} for r in requests]


def save(actor,request_id,body):
    import app
    if not runtime.database_business_writes_enabled():raise ValueError('当前环境未启用数据库业务写入。')
    if not isinstance(body,dict) or set(body)-{'label','note','expected_version','idempotency_key'}:raise ValueError('标签提交格式无效。')
    label,note=body.get('label',''),body.get('note','')
    if not isinstance(label,str) or not isinstance(note,str):raise ValueError('标签和备注须为文字。')
    label,note=label.strip(),note.strip()
    if len(label)>40 or len(note)>1000:raise ValueError('标签最多 40 字，备注最多 1000 字。')
    key=body.get('idempotency_key')
    if not actor or not request_id or not isinstance(key,str) or not 8<=len(key)<=150:raise ValueError('缺少操作人、申请单或提交标识。')
    payload={'request_id':request_id,'operator_open_id':actor,'label':label,'note':note,'expected_version':body.get('expected_version')}
    runtime.release_database_snapshot()
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:admin',0))")
        task,created=jobs.enqueue('待核实标签备注','pending-followup:'+key,payload,conn=conn)
        if not created:
            if task.status!='已完成':raise ValueError('该标签保存仍在处理，请稍后查看。')
            return task.result
        info=repo.named_table(conn,app.REQUEST_TABLE_NAME);fields(info)
        old=repo.raw_record(conn,info,request_id,lock=True)
        check_version(body.get('expected_version'),old['version'],'申请已更新，请刷新后再保存标签。')
        original=repo.feishu_record(info,old)
        if not app.pending_inventory_review_summaries([original]):raise ValueError('该申请已不属于待核实列表，请刷新后查看。')
        conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
        runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane='admin',_job_id=task.task_id)
        named=original['fields'];changed=named.get(LABEL,'')!=label or named.get(NOTE,'')!=note
        if changed:DatabaseWriteClient(conn).update_record(info['table_id'],old['record_id'],{LABEL:label,NOTE:note})
        latest=repo.raw_record(conn,info,old['record_id'])
        outbox=[str(r[0]) for r in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s',(task.task_id,))]
        result={'request':summary(info,latest),'taskId':task.task_id,'local_saved':True,'changed':changed,'outbox_ids':outbox}
        conn.execute("UPDATE material_ops.jobs SET state='done',completed_at=now(),result=%s WHERE id=%s",(Jsonb(result),task.task_id))
        return result
