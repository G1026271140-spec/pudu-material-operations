"""Durable inbound callbacks and reconciliation of external approval results.

Event refreshes never overwrite a row with active outbound writes or a local
commit newer than the fetch. Daily reconciliation remains the full authority.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import time
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .db import connection
from . import repository as repo

TYPES=('飞书申请变更回调','兑换数据回调','公司通讯录实时刷新')

def enqueue(kind,record_id):
    from .jobs import enqueue as add
    task,created=add(kind,'inbound:'+kind+':'+record_id+':'+str(int(time.time()//5)),{'record_id':record_id})
    if created:
        with connection() as conn:conn.execute("UPDATE material_ops.jobs SET available_at=now()+interval '8 seconds' WHERE id=%s",(task.task_id,))
    return task.task_id

def refresh(names,clients=None):
    import app
    from .reconcile import _local_links
    from .outbox_worker import _canonical
    started=datetime.now(timezone.utc)
    if clients is None:
        clients={'primary':app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())}
    with connection() as conn:
        infos=[repo.named_table(conn,name) for name in names]
    def fetch(info):return info,clients[info['source']].list_records(info['table_id'])
    with ThreadPoolExecutor(max_workers=3) as pool:fetched=list(pool.map(fetch,infos))
    stats={'changed':0,'created':0,'skipped':0}
    with connection() as conn,conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-reconciliation',0))")
        for info,records in fetched:
            for source in records:
                rid=source['record_id']
                old=conn.execute(sql.SQL('SELECT _record_key,_fields,_baseline,_local_version,_updated_at,_deleted FROM material_data.{} WHERE _remote_id=%s OR _record_key=%s FOR UPDATE').format(sql.Identifier(info['sql_table'])),(rid,rid)).fetchone()
                if old and (old[4]>started or conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND (state IN ('pending','processing','retry') OR completed_at>%s))",(info['table_id'],old[0],started)).fetchone()[0]):
                    stats['skipped']+=1;continue
                values=_local_links(conn,info,repo.source_values(info,source.get('fields') or {}))
                if not old:
                    repo.insert_source_records(conn,info,[repo.feishu_record(info,{'record_id':rid,'fields':values})]);stats['created']+=1
                    conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value) VALUES (%s,%s,'feishu_event',%s)",(info['table_id'],rid,Jsonb(values)))
                    continue
                if old[5]:continue # A pending/failed local deletion is reviewed by the daily reconciliation.
                definitions={f['field_id']:f for f in info['fields']}
                changed=any(_canonical(definitions[fid],values.get(fid))!=_canonical(definitions[fid],(old[2] or {}).get(fid)) for fid in values.keys()|(old[2] or {}).keys())
                if not changed:continue
                repo.replace_values(conn,info,old[0],values,version=old[3]+1,state='synced')
                conn.execute(sql.SQL('UPDATE material_data.{} SET _baseline=%s,_synced_version=%s,_source_seen_at=now() WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(Jsonb(values),old[3]+1,old[0]))
                conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,before_value,after_value,local_version) VALUES (%s,%s,'feishu_event',%s,%s,%s)",(info['table_id'],old[0],Jsonb(old[1]),Jsonb(values),old[3]+1))
                stats['changed']+=1
    return stats

def exchange_sync():
    import app,backend_runtime as runtime
    from scripts.reconcile_corporate_apparel_quotas import build_plan,EXCHANGE_SOURCE_BASE_TOKEN,EXCHANGE_SOURCE_TABLE_ID,EXCHANGE_SOURCE_TABLE
    remote=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),EXCHANGE_SOURCE_BASE_TOKEN)
    tables=remote.list_tables()
    if not any(t['table_id']==EXCHANGE_SOURCE_TABLE_ID and t['name']==EXCHANGE_SOURCE_TABLE for t in tables):raise ValueError('兑换源表身份不匹配。')
    records=remote.list_records(EXCHANGE_SOURCE_TABLE_ID)
    class Snapshot:
        def list_tables(self):return tables
        def list_records(self,table_id):
            if table_id!=EXCHANGE_SOURCE_TABLE_ID:raise ValueError('未知兑换来源。')
            return records
    with runtime.request_scope(),connection() as conn,conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-exchange-quota',0))")
        runtime.request_state.update({'_write_conn':conn,'_write_lane':'cultural','_write_actor':'exchange-webhook'})
        from .client import DatabaseWriteClient
        client=DatabaseWriteClient(conn)
        plan=build_plan(client,Snapshot())
        info=repo.table(conn,plan['table_id'])
        definitions={f['field_name']:f['field_id'] for f in info['fields']}
        for row in plan['updates']:
            current=repo.raw_record(conn,info,row['record_id'],lock=True)
            fields={name:max(int(repo.number(current['fields'].get(definitions[name]))),int(value)) for name,value in row['fields'].items()}
            client.update_record(plan['table_id'],row['record_id'],fields)
        if plan['creates']:client.batch_create_records(plan['table_id'],plan['creates'])
        return {'updated':len(plan['updates']),'created':len(plan['creates'])}

def run_one(lane=None,job_id=None):
    if lane not in {None,'admin'}:return None
    with connection() as guard:
        if job_id:
            row=guard.execute("SELECT id,task_type FROM material_ops.jobs WHERE id=%s AND task_type=ANY(%s) AND state IN ('pending','retry') AND available_at<=now()",(UUID(str(job_id)),list(TYPES))).fetchone()
        else:
            row=guard.execute("SELECT id,task_type FROM material_ops.jobs WHERE task_type=ANY(%s) AND state IN ('pending','retry') AND available_at<=now() ORDER BY created_at LIMIT 1",(list(TYPES),)).fetchone()
        if not row:return None
        key='inbound:'+str(row[0])
        if not guard.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(key,)).fetchone()[0]:return {'state':'busy'}
        try:
            import app
            if row[1]==TYPES[0]:
                result=refresh([app.REQUEST_TABLE_NAME,app.REQUEST_LINE_TABLE_NAME,app.MATERIAL_TABLE_NAME,app.LEDGER_TABLE_NAME])
            elif row[1]==TYPES[1]:result=exchange_sync()
            else:
                from .contacts import refresh_now
                result=refresh_now()
            guard.execute("UPDATE material_ops.jobs SET state=%s,result=%s,attempts=attempts+1,available_at=now()+interval '15 seconds',completed_at=CASE WHEN %s THEN now() ELSE NULL END,last_error=NULL WHERE id=%s",
                ('retry' if result.get('skipped') else 'done',Jsonb(result),not bool(result.get('skipped')),row[0]))
            return {'state':'retry' if result.get('skipped') else 'done','id':str(row[0])}
        except Exception as exc:
            if row[1]==TYPES[2]:
                guard.execute("UPDATE material_ops.jobs SET state='failed',attempts=attempts+1,last_error=%s WHERE id=%s",(type(exc).__name__+': '+str(exc)[:400],row[0]))
                return {'state':'failed','id':str(row[0])}
            guard.execute("UPDATE material_ops.jobs SET state=CASE WHEN attempts>=39 THEN 'failed' ELSE 'retry' END,attempts=attempts+1,available_at=now()+interval '30 seconds',last_error=%s WHERE id=%s",(type(exc).__name__+': '+str(exc)[:400],row[0]))
            return {'state':'retry','id':str(row[0])}
        finally:guard.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))
