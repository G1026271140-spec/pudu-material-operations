"""Bounded line publication, with per-record leases, conflicts and audit retained."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import logging,time
from uuid import uuid4
from psycopg import sql
from psycopg.types.json import Jsonb
from .db import connection
from . import repository as repo,outbox_worker as worker

LIMIT=50
LOG=logging.getLogger(__name__)


def claim_more(first,lane,identity,info,limit,*,reconciliation_guard=None):
    if not 1<=limit<=LIMIT:raise ValueError('明细批量上限须为 1 至 50。')
    with connection() as conn,conn.transaction():
        if reconciliation_guard is None:
            conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        params=[lane,first['table_id'],first['operation'],first['id'],first['record_key'],first.get('job_id')]
        scope=sql.SQL('true')
        if first.get('job_id') is None:
            link=next((f for f in info['fields'] if f['field_name']=='所属申请单'),None)
            row=repo.raw_record(conn,info,first['record_key'],include_deleted=True)
            value=row['fields'].get(link['field_id']) if link else None
            if len(repo.link_ids(value))!=1:return []
            scope=sql.SQL('(r._fields->%s)=%s');params.extend([link['field_id'],Jsonb(value)])
        params.append(limit-1)
        rows=conn.execute(sql.SQL("""SELECT o.id,o.table_id,o.record_key,o.local_version,o.patch,o.operation,o.attempts,o.job_id
            FROM material_ops.outbox o JOIN material_data.{} r ON r._record_key=o.record_key
            WHERE o.lane=%s AND o.table_id=%s AND o.operation=%s AND o.id<>%s AND o.record_key<>%s
              AND o.job_id IS NOT DISTINCT FROM %s AND NOT r._deleted AND {}
              AND ((o.state IN ('pending','retry') AND o.available_at<=now()) OR (o.state='processing' AND o.lease_until<now()))
              AND NOT EXISTS(SELECT 1 FROM material_ops.outbox p WHERE p.table_id=o.table_id AND p.record_key=o.record_key
                AND p.local_version<o.local_version AND p.state IN ('pending','processing','retry'))
            ORDER BY o.ordinal LIMIT %s FOR UPDATE OF o SKIP LOCKED""").format(sql.Identifier(info['sql_table']),scope),params).fetchall()
        tasks=[];seen={first['record_key']}
        for oid,tid,key,version,patch,operation,attempts,job in rows:
            if key in seen:continue
            seen.add(key);token=uuid4()
            conn.execute("UPDATE material_ops.outbox SET state='processing',claim_token=%s,claimed_by=%s,lease_until=now()+interval '3 minutes',attempts=attempts+1 WHERE id=%s",(token,identity,oid))
            tasks.append({'id':oid,'table_id':tid,'record_key':key,'version':version,'patch':patch,'operation':operation,'attempts':attempts+1,'claim_token':token,'job_id':job})
        return tasks


def matches(info,named,remote):
    definitions={f['field_name']:f for f in info['fields']}
    values=remote.get('fields') or {}
    return all(worker._canonical(definitions[name],values.get(name))==worker._canonical(definitions[name],value) for name,value in named.items())


def indexed(rows,key):
    result=defaultdict(list)
    for row in rows:
        value=key(row)
        if value:result[value].append(row)
    return result


def run_claimed(first,lane,clients,identity,guard,limit=LIMIT):
    with connection() as conn:info=repo.table(conn,first['table_id'])
    if info['source']!='primary' or info['name']!='申请明细' or first['operation'] not in {'create','update'}:return None
    client=clients.get('primary') if isinstance(clients,dict) else clients
    if client is None:return None
    if first['operation']=='update' and not all(callable(getattr(client,n,None)) for n in ('batch_get_records','batch_update_records')):return None
    if first['operation']=='create':
        number=next((f for f in info['fields'] if f['field_name']=='明细编号'),None)
        if not number or not first['patch'].get(number['field_id']):return None
        if not all(callable(getattr(client,n,None)) for n in ('list_records','batch_create_records')):return None
    tasks=[first,*claim_more(first,lane,identity,info,limit,reconciliation_guard=guard)]
    batch_id=str(uuid4());started=time.monotonic();results={};operations=[];write_count=0
    def fail(task,exc):
        worker.fail(task,exc)
        state='conflict' if isinstance(exc,worker.SourceConflict) else 'retry';results[task['id']]=state
        (LOG.info if isinstance(exc,worker.DependencyPending) else LOG.warning)('Line batch %s record %s: %s',batch_id,task['id'],type(exc).__name__)
    def finish(task,remote):
        try:
            task['_batch']={'id':batch_id,'size':len(tasks)}
            worker.finish(task,remote['record_id']);results[task['id']]='done'
        except Exception as exc:fail(task,exc)
    prepared=[]
    try:
        for task in tasks:
            if task is not first:
                resource='outbox-record:'+task['table_id']+':'+task['record_key']
                if not guard.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(resource,)).fetchone()[0]:
                    fail(task,worker.DependencyPending('同一记录的同步仍在执行。'));continue
            try:
                with connection() as conn:
                    lease=conn.execute('SELECT state,claim_token FROM material_ops.outbox WHERE id=%s',(task['id'],)).fetchone()
                    row=repo.raw_record(conn,info,task['record_key'],include_deleted=True)
                if lease!=('processing',task['claim_token']):results[task['id']]='retry';continue
                named=worker._remote_fields(info,task['patch'],client)
                if not named:raise worker.SourceConflict('明细同步没有可写字段。')
                if task['operation']=='update' and not row['remote_id']:raise worker.DependencyPending('本地明细尚未取得飞书 ID。')
                prepared.append((task,row,named))
            except Exception as exc:fail(task,exc)
        if prepared and first['operation']=='create':
            number=next(f for f in info['fields'] if f['field_name']=='明细编号')
            def number_of(row):return worker._canonical(number,(row.get('fields') or {}).get('明细编号'))
            operations.append('list_records');remote=indexed(client.list_records(info['table_id']),number_of)
            duplicates=Counter(number_of({'fields':named}) for task,row,named in prepared);missing=[]
            for task,row,named in prepared:
                key=number_of({'fields':named});found=remote.get(key,[])
                if not key or duplicates[key]!=1 or len(found)>1:
                    fail(task,worker.SourceConflict('明细编号不唯一，不能批量创建。'));continue
                if found:
                    if not matches(info,named,found[0]):fail(task,worker.SourceConflict('飞书已有该明细编号的不同内容。'))
                    else:finish(task,found[0])
                else:missing.append((task,row,named))
            if missing:
                operations.append('batch_create_records');write_count+=len(missing)
                created=client.batch_create_records(info['table_id'],[named for task,row,named in missing])
                returned=indexed(created,number_of)
                if any(len(returned.get(number_of({'fields':named}),[]))!=1 or not matches(info,named,returned[number_of({'fields':named})][0]) for task,row,named in missing):
                    operations.append('list_records');returned=indexed(client.list_records(info['table_id']),number_of)
                for task,row,named in missing:
                    found=returned.get(number_of({'fields':named}),[])
                    if len(found)>1:fail(task,worker.SourceConflict('批量创建后的明细编号重复。'))
                    elif not found:fail(task,worker.DependencyPending('批量创建结果尚未完整可见，等待核对。'))
                    elif not matches(info,named,found[0]):fail(task,worker.SourceConflict('批量创建后的明细内容与本地不同。'))
                    else:finish(task,found[0])
        elif prepared:
            operations.append('batch_get_records')
            remote=indexed(client.batch_get_records(info['table_id'],[row['remote_id'] for task,row,named in prepared]),lambda row:row.get('record_id'))
            updates=[]
            for task,row,named in prepared:
                try:
                    found=remote.get(row['remote_id'],[])
                    if len(found)!=1:raise ValueError('飞书批量读取未返回唯一明细，等待核对权限或来源记录。')
                    if worker.update_needed(info,row['baseline'] or {},task['patch'],found[0],named,client):updates.append((task,row,named))
                    else:finish(task,found[0])
                except Exception as exc:fail(task,exc)
            if updates:
                operations.append('batch_update_records');write_count+=len(updates)
                updated=client.batch_update_records(info['table_id'],[{'record_id':row['remote_id'],'fields':named} for task,row,named in updates])
                returned=indexed(updated,lambda row:row.get('record_id'))
                unclear=[row['remote_id'] for task,row,named in updates if len(returned.get(row['remote_id'],[]))!=1 or not matches(info,named,returned[row['remote_id']][0])]
                if unclear:
                    operations.append('batch_get_records');checked=indexed(client.batch_get_records(info['table_id'],unclear),lambda row:row.get('record_id'))
                    for key in unclear:returned[key]=checked.get(key,[])
                for task,row,named in updates:
                    try:
                        found=returned.get(row['remote_id'],[])
                        if len(found)!=1:raise worker.DependencyPending('批量更新结果尚未完整可见，等待核对。')
                        if not matches(info,named,found[0]):
                            worker.update_needed(info,row['baseline'] or {},task['patch'],found[0],named,client)
                            raise worker.DependencyPending('飞书明细仍未显示本次修改，等待核对。')
                        finish(task,found[0])
                    except Exception as exc:fail(task,exc)
    except Exception as exc:
        for task in tasks:
            if task['id'] not in results:fail(task,exc)
    states=Counter(results.values())
    result={'id':str(first['id']),'state':'conflict' if states['conflict'] else 'retry' if states['retry'] else 'done',
        'batch_id':batch_id,'records':len(tasks),'written':write_count,'done':states['done'],'conflict':states['conflict'],'retry':states['retry'],
        'operations':operations,'duration_ms':round((time.monotonic()-started)*1000)}
    try:
        with connection() as conn:
            conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",('outbox-line-batch:'+lane,Jsonb({**result,'version':__import__('app').APP_VERSION,'completed_at':datetime.now(timezone.utc).isoformat()})))
    except Exception:LOG.warning('Line batch telemetry could not be saved')
    return result
