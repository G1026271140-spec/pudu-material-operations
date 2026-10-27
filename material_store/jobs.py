"""Local domain jobs. Business writes and deferred effects commit atomically.

No Feishu call is allowed within a business transaction. A process crash rolls
back the job, its writes and its effects together; another worker can resume.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import time
from uuid import UUID
from psycopg.types.json import Jsonb
from .db import connection
import backend_runtime as runtime

LOG=logging.getLogger(__name__)
LANES=('ordinary','cultural','admin','card')

def lane_for(task_type):
    if task_type in {'飞书申请变更回调','兑换数据回调'}:return 'admin'
    if task_type=='card_action':return 'card'
    if '企业文化衫' in task_type or '文化周边' in task_type:return 'cultural'
    if task_type in {'普通申请通知','文化申请通知'}:return 'ordinary' if task_type=='普通申请通知' else 'cultural'
    return 'admin'

def _task(row):
    from submission_queue import SubmissionTask
    return SubmissionTask(record_id=str(row[0]),task_id=str(row[0]),task_type=row[1],idempotency_key=row[2],
        status={'done':'已完成','failed':'失败'}.get(row[4],'待处理'),payload=row[3],submitted_at=0,started_at=0,
        completed_at=0,lease_expires_at=0,retry_count=0,next_retry_at=0,worker_id='postgresql',result=row[5],error='')

def enqueue(task_type,key,payload,*,conn=None):
    if not str(key).strip():raise ValueError('缺少业务提交标识。')
    if conn is None:
        with connection() as opened,opened.transaction():
            return enqueue(task_type,key,payload,conn=opened)
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('job:'+key,))
    prior=conn.execute('SELECT id,task_type,idempotency_key,payload,state,result FROM material_ops.jobs WHERE idempotency_key=%s',(key,)).fetchone()
    if prior:
        if prior[1]!=task_type or prior[3]!=payload:raise ValueError('同一提交标识不能用于不同的业务数据。')
        return _task(prior),False
    row=conn.execute('INSERT INTO material_ops.jobs(task_type,idempotency_key,payload,lane) VALUES (%s,%s,%s,%s) RETURNING id,task_type,idempotency_key,payload,state,result',
                     (task_type,key,Jsonb(payload),lane_for(task_type))).fetchone()
    return _task(row),True

def dispatch(task,checkpoint):
    import app
    if task.task_type=='card_action':
        from scripts.feishu_card_worker import process_card_action_async
        process_card_action_async(**task.payload)
        return {'accepted':True}
    if task.task_type in {'普通申请通知','文化申请通知'}:
        existing=app.submission_token_rows(task.payload['request_payload']['submission_token'])
        if not existing:return {'cancelled':'申请已撤回'}
    if task.task_type=='普通申请通知':
        payload=task.payload
        return {'admins':app.notify_enabled_admins_of_material_request(payload['request_no'],payload['request_payload'],payload['lines']),
                'applicant':app.notify_sales_request_received(payload['request_no'],payload['request_payload'],payload['lines'])}
    if task.task_type=='文化申请通知':
        payload=task.payload
        client=app.feishu_client()
        ids={}
        for target in app.cultural_request_notification_targets(payload['request_no'],payload['request_payload'],payload['lines']):
            ids[target['key']]=app.send_feishu_interactive_message(client,str(target['recipient_id']),dict(target['card']))
        request=app.submission_token_rows(payload['request_payload']['submission_token'])[0]
        app.feishu_update_record_fields(app.REQUEST_TABLE_NAME,app.feishu_record_id(request),
            {'文化周边通知状态':'已发送',app.CULTURAL_REQUEST_MESSAGE_IDS_FIELD:json.dumps(ids,ensure_ascii=False)})
        return {'queued':len(ids)}
    from scripts.submission_worker import process_task
    return process_task(task,checkpoint)

def _run(conn,row):
    from request_web.live_data import LiveReader
    task=_task(row)
    conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
    lane=lane_for(task.task_type)
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('business-lane:'+lane,))
    # Request submissions also take this lock, protecting shared quota rows.
    payload=task.payload
    requester=str((payload.get('request_payload') or payload.get('draft') or payload).get('requester_open_id') or '')
    if requester:conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('user-permission:'+requester,))
    conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
    runtime.request_state.update({'_write_conn':conn,'_write_lane':'cultural' if lane=='cultural' else 'admin',
        '_write_actor':str((payload.get('draft') or payload.get('request_payload') or payload).get('operator_open_id') or requester or 'system'),
        '_job_id':task.task_id,'_effect_ordinal':0})
    runtime.request_state['_live_reader']=LiveReader()
    def checkpoint(progress):
        conn.execute('UPDATE material_ops.jobs SET result=%s WHERE id=%s',(Jsonb(progress),UUID(task.task_id)))
    result=dispatch(task,checkpoint) or {}
    conn.execute("UPDATE material_ops.jobs SET state='done',result=%s,completed_at=now(),last_error=NULL,attempts=attempts+1 WHERE id=%s",(Jsonb(result),UUID(task.task_id)))
    return result

def run_one(lane=None,job_id=None,*,raise_errors=False):
    from .inbound import run_one as run_inbound
    inbound=run_inbound(lane,job_id)
    if inbound is not None:return inbound
    selected=None
    try:
        # Each worker owns a fresh scope; stale HTTP snapshots cannot leak in.
        with runtime.request_scope(),connection() as conn,conn.transaction():
            if job_id:
                row=conn.execute("SELECT id,task_type,idempotency_key,payload,state,result FROM material_ops.jobs WHERE id=%s AND state IN ('pending','retry') AND task_type NOT IN ('飞书申请变更回调','兑换数据回调') FOR UPDATE",(UUID(str(job_id)),)).fetchone()
            else:
                row=conn.execute("SELECT id,task_type,idempotency_key,payload,state,result FROM material_ops.jobs WHERE lane=%s AND state IN ('pending','retry') AND available_at<=now() AND task_type NOT IN ('飞书申请变更回调','兑换数据回调') ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",(lane,)).fetchone()
            if row is None:return None
            selected=row[0]
            return {'id':str(selected),'result':_run(conn,row),'state':'done'}
    except Exception as exc:
        if selected:
            with connection() as conn:
                conn.execute("UPDATE material_ops.jobs SET attempts=attempts+1,state=CASE WHEN attempts>=9 OR %s THEN 'failed' ELSE 'retry' END,last_error=%s,available_at=now()+interval '30 seconds' WHERE id=%s AND state<>'done'",
                    (isinstance(exc,(ValueError,PermissionError)) or (isinstance(exc,RuntimeError) and row[1]!='审批回写管理员通知'),type(exc).__name__+': '+str(exc)[:500],selected))
        if raise_errors:raise
        LOG.exception('Local job failed: %s',selected)
        return {'id':str(selected),'state':'retry'}

def submit(task_type,key,payload):
    runtime.release_database_snapshot()
    task,created=enqueue(task_type,key,payload)
    if task.status=='失败':raise ValueError('这笔操作此前未能保存，请刷新后重新提交。')
    if task.status!='已完成':
        import psycopg
        try:run_one(job_id=task.task_id,raise_errors=True)
        except (psycopg.errors.DeadlockDetected,psycopg.errors.SerializationFailure,psycopg.errors.LockNotAvailable):
            # The durable job will retry. Return its identity so an HTTP retry
            # cannot create another business operation with a different token.
            return task,created
    with connection() as conn:
        state,result,error=conn.execute('SELECT state,result,last_error FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()
    if state!='done':raise RuntimeError(error or '这笔操作尚未完成，请稍后重试。')
    from dataclasses import replace
    task=replace(task,status='已完成',result=result)
    # Invalidate the HTTP response snapshot so subsequent builders see commits.
    runtime.request_state.pop('_live_reader',None)
    return task,created

def heartbeat(name):
    import app
    with connection() as conn:
        conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",
            ('worker:'+name,Jsonb({'version':app.APP_VERSION,'worker':name})))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--lane',choices=(*LANES,'all'),default='all');args=parser.parse_args()
    if not runtime.database_reads():raise RuntimeError('PostgreSQL mode required')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    def loop(lane):
        beat=0
        while True:
            result=run_one(lane)
            if time.monotonic()-beat>10:heartbeat('business:'+lane);beat=time.monotonic()
            if result is None:time.sleep(1)
    if args.lane!='all':return loop(args.lane)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4,thread_name_prefix='business') as pool:
        futures=[pool.submit(loop,lane) for lane in LANES]
        for future in futures:future.result()

if __name__=='__main__':main()
