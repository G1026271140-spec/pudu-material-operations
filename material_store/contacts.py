"""Refresh directory metadata into PostgreSQL without a page-cache dependency."""
import json
from psycopg.types.json import Jsonb
from .db import connection

NAME='contact_departments_cache.json'
REFRESH_TASK='公司通讯录实时刷新'

def publish(conn,payload):
    users=payload.get('users');departments=payload.get('departments')
    if not isinstance(users,list) or not users or not isinstance(departments,list) or not departments:
        raise ValueError('通讯录读取结果不完整，保留原数据。')
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-contacts',0))")
        conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",(NAME,Jsonb(payload)))
        summary={'users':len(users),'departments':len(departments)}
        conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value) VALUES ('contacts',%s,'worker',%s)",(NAME,Jsonb(summary)))
    return summary

def refresh_now():
    """Fetch complete Feishu directory outside a SQL transaction, then publish."""
    import app,backend_runtime as runtime
    # A session lock shares the refresh with the scheduled contact service.
    # Waiting does not hold a SQL transaction or block business table writes.
    with connection() as guard:
        started=guard.execute('SELECT clock_timestamp()').fetchone()[0]
        guard.execute("SELECT pg_advisory_lock(hashtextextended('pudu-contacts-refresh',0))")
        try:
            recent=guard.execute('SELECT payload,updated_at FROM material_ops.documents WHERE name=%s',(NAME,)).fetchone()
            if recent and recent[1]>=started:
                return {'users':len(recent[0].get('users') or []),'departments':len(recent[0].get('departments') or []),'updated_at':str(recent[1])}
            with runtime.request_scope():payload=app.build_live_contact_department_cache()
            with connection() as conn:
                result=publish(conn,payload)
                result['updated_at']=str(conn.execute('SELECT updated_at FROM material_ops.documents WHERE name=%s',(NAME,)).fetchone()[0])
            from .jobs import heartbeat
            heartbeat('contacts')
            return result
        finally:guard.execute("SELECT pg_advisory_unlock(hashtextextended('pudu-contacts-refresh',0))")

def enqueue_refresh(actor):
    from . import jobs
    from .portal_records import roles_for
    from uuid import uuid4
    with connection() as conn,conn.transaction():
        if '管理员' not in roles_for(conn,actor):raise PermissionError('仅管理员可以刷新公司通讯录。')
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-contacts-refresh-enqueue',0))")
        pending=conn.execute("SELECT id FROM material_ops.jobs WHERE task_type=%s AND state IN ('pending','retry') ORDER BY created_at LIMIT 1",(REFRESH_TASK,)).fetchone()
        if pending:return {'job_id':str(pending[0])}
        task,_=jobs.enqueue(REFRESH_TASK,'contacts-refresh:'+uuid4().hex,{'operator_open_id':actor},conn=conn)
        return {'job_id':task.task_id}

def refresh_status(job_id):
    with connection() as conn:
        row=conn.execute('SELECT state,result,last_error FROM material_ops.jobs WHERE id=%s AND task_type=%s',(job_id,REFRESH_TASK)).fetchone()
        if not row:raise ValueError('通讯录刷新任务不存在。')
        return {'job_id':str(job_id),'state':row[0],'result':row[1],'error':'通讯录刷新失败，已保留原数据，请重试。' if row[2] else ''}

def main():
    import backend_runtime as runtime
    if not runtime.database_reads():raise RuntimeError('PostgreSQL mode required')
    result=refresh_now()
    print(json.dumps({'directory_updated':True,**result}))

if __name__=='__main__':main()
