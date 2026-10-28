"""Publish permission creates in bounded batches; retries match accounts, never names."""
import os
from uuid import uuid4
import psycopg
from .db import connection
from . import repository as repo,outbox_worker as worker
from .company_permissions import TABLE

def claim_batch(worker_id,limit):
    with connection() as conn,conn.transaction():
        rows=conn.execute("""SELECT id,record_key,local_version,patch,attempts FROM material_ops.outbox o
          WHERE table_id=%s AND lane='admin' AND operation='create'
          AND ((state IN ('pending','retry') AND available_at<=now()) OR (state='processing' AND lease_until<now()))
          AND NOT EXISTS(SELECT 1 FROM material_ops.outbox p WHERE p.table_id=o.table_id AND p.record_key=o.record_key
            AND p.local_version<o.local_version AND p.state IN ('pending','retry','processing'))
          ORDER BY ordinal LIMIT %s FOR UPDATE OF o SKIP LOCKED""",(TABLE,limit)).fetchall()
        tasks=[]
        for identity,key,version,patch,attempts in rows:
            token=uuid4()
            conn.execute("UPDATE material_ops.outbox SET state='processing',claim_token=%s,claimed_by=%s,lease_until=now()+interval '3 minutes',attempts=attempts+1 WHERE id=%s",(token,worker_id,identity))
            tasks.append({'id':identity,'table_id':TABLE,'record_key':key,'version':version,'patch':patch,'attempts':attempts+1,'claim_token':token,'operation':'create'})
        return tasks

def run_once(client,worker_id='permission-batch-worker',limit=100):
    if not 1<=limit<=100:raise ValueError('Permission batch size must be between 1 and 100')
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as guard:
        guard.execute("SELECT pg_advisory_lock_shared(hashtextextended('pudu-reconciliation',0))")
        if not guard.execute("SELECT pg_try_advisory_lock(hashtextextended('pudu-permission-batch',0))").fetchone()[0]:return None
        tasks=claim_batch(worker_id,limit)
        if not tasks:return None
        complete=set();results=[]
        try:
            with connection() as conn:info=repo.table(conn,TABLE)
            account=next(f for f in info['fields'] if f['field_name']=='用户账号')
            definitions={f['field_name']:f for f in info['fields']}
            def identity(fields):
                ids=worker._canonical(account,fields.get('用户账号'))
                if len(ids)!=1:raise worker.SourceConflict('权限创建缺少唯一用户账号。')
                return ids[0]
            def indexed(rows):
                result={}
                for row in rows:
                    ids=worker._canonical(account,(row.get('fields') or {}).get('用户账号'))
                    if len(ids)==1:result.setdefault(ids[0],[]).append(row)
                return result
            remote=indexed(client.list_records(TABLE));prepared=[];missing=[];seen=set()
            for task in tasks:
                named=worker._remote_fields(info,task['patch'],client)
                actor=identity(named)
                if actor in seen:raise worker.SourceConflict('同一批次不能重复创建同一用户。')
                seen.add(actor);prepared.append((task,named,actor))
                rows=remote.get(actor,[])
                if len(rows)>1:raise worker.SourceConflict('飞书存在该账号的重复权限。')
                if rows and any(worker._canonical(definitions[name],rows[0]['fields'].get(name))!=worker._canonical(definitions[name],value) for name,value in named.items()):
                    raise worker.SourceConflict('飞书已有账号内容不同，不能批量覆盖。')
                if not rows:missing.append(named)
            if missing:
                created=client.batch_create_records(TABLE,missing)
                created_index=indexed(created)
                # Never assume response order. Re-read if the service omitted
                # account fields or returned an incomplete batch response.
                if set(created_index)!={identity(fields) for fields in missing}:
                    remote=indexed(client.list_records(TABLE))
                else:
                    for actor,rows in created_index.items():remote.setdefault(actor,[]).extend(rows)
            for task,named,actor in prepared:
                rows=remote.get(actor,[])
                if len(rows)!=1:raise worker.SourceConflict('批量创建后的账号无法唯一核对。')
                row=rows[0]
                if any(worker._canonical(definitions[name],row['fields'].get(name))!=worker._canonical(definitions[name],value) for name,value in named.items()):
                    raise worker.SourceConflict('飞书已有账号的权限或额度与本地创建内容不一致。')
                worker.finish(task,row['record_id']);complete.add(task['id'])
                results.append({'id':str(task['id']),'state':'done'})
            return {'state':'done','records':len(results),'created':len(missing)}
        except Exception as exc:
            for task in tasks:
                if task['id'] not in complete:worker.fail(task,exc)
            return {'state':'conflict' if isinstance(exc,worker.SourceConflict) else 'retry','records':len(complete),'error_type':type(exc).__name__}
