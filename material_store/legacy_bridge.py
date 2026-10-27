"""Receive existing Feishu workflow jobs while business state lives locally."""
import json
import logging
import time
from dataclasses import replace
from .db import connection
from . import jobs
import backend_runtime as runtime

def tick(client):
    import app
    from submission_queue import (claim_next_submission_task,complete_submission_task,fail_submission_task,
        QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY)
    task=claim_next_submission_task(client,'pudu-vm-postgresql-bridge',lease_seconds=180)
    if task is None:return None
    try:
        # The native approval automation updates Base first. Import the final
        # request/stock/ledger values before checking its completion locally.
        if task.task_type==QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY:
            from .inbound import refresh
            refresh([app.REQUEST_TABLE_NAME,app.REQUEST_LINE_TABLE_NAME,app.MATERIAL_TABLE_NAME,app.LEDGER_TABLE_NAME])
        local,created=jobs.enqueue(task.task_type,task.idempotency_key,task.payload)
        if created and task.result:
            from psycopg.types.json import Jsonb
            with connection() as conn:conn.execute('UPDATE material_ops.jobs SET result=%s WHERE id=%s',(Jsonb(task.result),local.task_id))
        if local.status!='已完成':jobs.run_one(job_id=local.task_id,raise_errors=True)
        with connection() as conn:
            row=conn.execute('SELECT state,result,last_error FROM material_ops.jobs WHERE id=%s',(local.task_id,)).fetchone()
            if row[0]=='failed':raise RuntimeError(row[2] or '本地业务任务失败')
            pending=conn.execute("SELECT count(*) FROM material_ops.effects WHERE job_id=%s AND state<>'done'",(local.task_id,)).fetchone()[0]
            pending+=conn.execute("SELECT count(*) FROM material_ops.outbox WHERE job_id=%s AND state NOT IN ('done','cancelled')",(local.task_id,)).fetchone()[0]
        if row[0]=='done' and not pending:
            complete_submission_task(client,task,{**row[1],'postgresql_job_id':local.task_id})
            return {'task':task.task_id,'state':'done'}
        return {'task':task.task_id,'state':'processing'}
    except Exception as exc:
        fail_submission_task(client,task,exc)
        logging.warning('Legacy workflow transfer failed: %s',type(exc).__name__)
        return {'task':task.task_id,'state':'retry'}

def main():
    if not runtime.database_reads():raise RuntimeError('PostgreSQL mode required')
    import app
    client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    logging.basicConfig(level=logging.INFO)
    beat=0
    while True:
        try:
            result=tick(client)
            if time.monotonic()-beat>60:
                with runtime.request_scope():
                    try:app.enqueue_inventory_review_scheduled_tasks()
                    finally:runtime.release_database_snapshot()
                jobs.heartbeat('legacy-bridge');beat=time.monotonic()
        except Exception as exc:
            logging.warning('Feishu workflow bridge unavailable: %s',type(exc).__name__)
        time.sleep(15)

if __name__=='__main__':main()
