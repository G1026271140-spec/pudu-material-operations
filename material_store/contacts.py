"""Refresh directory metadata into PostgreSQL without a page-cache dependency."""
import json
from psycopg.types.json import Jsonb
from .db import connection

NAME='contact_departments_cache.json'

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

def main():
    import app,backend_runtime as runtime
    if not runtime.database_reads():raise RuntimeError('PostgreSQL mode required')
    # Fetch all departments and users before opening the publishing transaction.
    # The builder fails if even one department cannot be read completely.
    with runtime.request_scope():payload=app.build_live_contact_department_cache()
    with connection() as conn:result=publish(conn,payload)
    from .jobs import heartbeat
    heartbeat('contacts')
    print(json.dumps({'directory_updated':True,**result}))

if __name__=='__main__':main()
