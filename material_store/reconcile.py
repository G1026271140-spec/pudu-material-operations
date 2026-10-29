"""Daily Feishu-authoritative field comparison for the local PostgreSQL mirror."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import logging
import os
import time

from psycopg import sql
from psycopg.types.json import Jsonb

from . import repository as repo
from .db import connection


def _local_links(conn,info,values):
    """Remote IDs resolve to stable local keys, including newly created rows."""
    result=dict(values)
    for field in info['fields']:
        if field['type'] not in {18,21} or field['field_id'] not in values:continue
        target=repo.table(conn,field['property']['table_id'])
        ids=repo.link_ids(values[field['field_id']])
        mapping=dict(conn.execute(sql.SQL('SELECT _remote_id,_record_key FROM material_data.{} WHERE _remote_id=ANY(%s)').format(sql.Identifier(target['sql_table'])),(ids,)).fetchall()) if ids else {}
        if any(mapping.get(key,key)!=key for key in ids):
            result[field['field_id']]=[mapping.get(key,key) for key in ids]
    return result

LOGGER=logging.getLogger(__name__)


def reconcile_snapshot(conn,info,records,run_id):
    """Apply one fetched table within the caller's transaction."""
    by_remote={}
    for row in conn.execute(sql.SQL("SELECT _record_key,_remote_id,_fields,_baseline,_local_version,_synced_version,_sync_state,_deleted FROM material_data.{}")
                            .format(sql.Identifier(info['sql_table']))):
        by_remote[row[1] or row[0]]=row
    seen=set();changed=created=deleted=conflicts=0
    for source in records:
        remote_id=source.get('record_id') or source.get('id')
        seen.add(remote_id)
        values=_local_links(conn,info,repo.source_values(info,source.get('fields') or {}))
        old=by_remote.get(remote_id)
        if old is None:
            repo.insert_source_records(conn,info,[repo.feishu_record(info,{'record_id':remote_id,'fields':values})]);created+=1
            conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value,reconcile_run) VALUES (%s,%s,'feishu_daily',%s,%s)",
                         (info['table_id'],remote_id,Jsonb(values),run_id))
            continue
        key,_,current,baseline,version,synced_version,state,was_deleted=old
        baseline=baseline or {}
        pending=conn.execute("SELECT id,patch,local_version FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state IN ('pending','processing','retry') FOR UPDATE",
                             (info['table_id'],key)).fetchall()
        if values==current and not was_deleted and not pending:continue
        conflict_ids=[];done_ids=[]
        for task_id,patch,task_version in pending:
            if all(values.get(fid)==target for fid,target in patch.items()):
                done_ids.append(task_id)
            else:
                conflict_ids.append(task_id)
        if done_ids:
            conn.execute("UPDATE material_ops.outbox SET state='done',completed_at=now(),claim_token=NULL,lease_until=NULL WHERE id=ANY(%s)",(done_ids,))
        if conflict_ids:
            conn.execute("UPDATE material_ops.outbox SET state='conflict',last_error='飞书全量校验：源字段已变化，旧本地写入已取消',claim_token=NULL,lease_until=NULL WHERE id=ANY(%s)",(conflict_ids,))
            conflicts+=len(conflict_ids)
        # The daily job adopts the entire current Feishu record, including
        # cleared fields. Unsynced *new* local records are handled separately.
        for fid in current.keys()|values.keys():
            value=values.get(fid)
            if value != current.get(fid):
                conn.execute("INSERT INTO material_ops.audit(table_id,record_key,field_id,source,before_value,after_value,local_version,reconcile_run) VALUES (%s,%s,%s,'feishu_daily',%s,%s,%s,%s)",
                             (info['table_id'],key,fid,Jsonb(current.get(fid)),Jsonb(value),version+1,run_id))
        next_version=version+1
        repo.replace_values(conn,info,key,values,version=next_version,state='synced')
        conn.execute(sql.SQL("UPDATE material_data.{} SET _baseline=%s,_synced_version=%s,_deleted=false,_source_seen_at=now() WHERE _record_key=%s")
                     .format(sql.Identifier(info['sql_table'])),(Jsonb(values),next_version,key))
        changed+=1
    for remote_id,old in by_remote.items():
        if remote_id in seen or old[1] is None or old[7]:continue
        key=old[0]
        pending=conn.execute("SELECT count(*) FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state IN ('pending','processing','retry')",(info['table_id'],key)).fetchone()[0]
        if pending:
            conn.execute("UPDATE material_ops.outbox SET state='conflict',last_error='飞书全量校验：源记录已删除',claim_token=NULL,lease_until=NULL WHERE table_id=%s AND record_key=%s AND state IN ('pending','processing','retry')",(info['table_id'],key))
            conflicts+=pending
        conn.execute(sql.SQL("UPDATE material_data.{} SET _deleted=true,_sync_state='conflict',_updated_at=now() WHERE _record_key=%s")
                     .format(sql.Identifier(info['sql_table'])),(key,))
        conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,before_value,reconcile_run) VALUES (%s,%s,'feishu_daily',%s,%s)",
                     (info['table_id'],key,Jsonb(old[2]),run_id))
        deleted+=1
    return {'changed':changed,'created':created,'deleted':deleted,'conflicts':conflicts}


def run(clients, *, progress=None, trigger="daily", actor="system:daily-reconcile", db_connection=None):
    """Hold a session lock while fetching; no SQL transaction spans HTTP calls."""
    report = progress or (lambda value: None)
    report({'stage':'waiting_lock','fetched':0,'total':0,'trigger':trigger})
    with (nullcontext(db_connection) if db_connection is not None else connection()) as guard:
        guard.execute("SELECT pg_advisory_lock(hashtextextended('pudu-reconciliation',0))")
        run_id=None;stage='starting'
        try:
            # Register before preflight/fetch so schema or network failures are
            # visible to the database workbench, not only the system journal.
            run_id=guard.execute("INSERT INTO material_ops.reconcile_runs(state,summary) VALUES ('running',%s) RETURNING id",(Jsonb({'trigger':trigger,'actor':actor}),)).fetchone()[0]
            report({'stage':'metadata','run_id':str(run_id),'fetched':0,'total':0,'trigger':trigger})
            guard.execute("UPDATE material_ops.outbox SET state='retry',claim_token=NULL,lease_until=NULL,available_at=now() WHERE state='processing'")
            stage='metadata'
            metadata=[repo.table(guard,r[0]) for r in guard.execute('SELECT table_id FROM material_meta.tables ORDER BY source_key,table_id')]
            def fetch(info):
                client=clients[info['source']]
                expected={(f['field_id'],f['field_name'],int(f['type'])) for f in info['fields']}
                actual={(f['field_id'],f['field_name'],int(f['type'])) for f in client.list_fields(info['table_id'])}
                if expected!=actual:raise ValueError('飞书字段定义与数据库注册不一致：'+info['name'])
                records=client.list_records(info['table_id'])
                ids=[r.get('record_id') or r.get('id') for r in records]
                if len(ids)!=len(set(ids)):raise ValueError('飞书返回了重复记录：'+info['name'])
                return info,records
            stage='source_fetch'
            fetched=[]
            report({'stage':stage,'run_id':str(run_id),'fetched':0,'total':len(metadata),'trigger':trigger})
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(fetch,info) for info in metadata]
                for future in as_completed(futures):
                    fetched.append(future.result())
                    report({'stage':stage,'run_id':str(run_id),'fetched':len(fetched),'total':len(metadata),'trigger':trigger})
            order={info['table_id']:index for index,info in enumerate(metadata)}
            fetched.sort(key=lambda item:order[item[0]['table_id']])
            stage='apply'
            report({'stage':stage,'run_id':str(run_id),'fetched':len(fetched),'total':len(metadata),'trigger':trigger})
            with guard.transaction():
                summary={'tables':len(fetched),'run_id':str(run_id),'trigger':trigger,'actor':actor,'source':'feishu','started_local':datetime.now().isoformat(timespec='seconds'),
                         'changed':0,'created':0,'deleted':0,'conflicts':0}
                for info,records in fetched:
                    stats=reconcile_snapshot(guard,info,records,run_id)
                    for name,value in stats.items():summary[name]+=value
                guard.execute("UPDATE material_ops.reconcile_runs SET state='done',completed_at=now(),summary=%s WHERE id=%s",(Jsonb(summary),run_id))
            report({'stage':'done',**summary})
            return summary
        except Exception as exc:
            if run_id:
                summary={'error_type':type(exc).__name__,'stage':stage,'trigger':trigger,'actor':actor}
                message=str(exc)
                if message.startswith('飞书字段定义与数据库注册不一致：'):
                    summary.update(reason='schema_mismatch',table=message.split('：',1)[1])
                guard.execute("UPDATE material_ops.reconcile_runs SET state='failed',completed_at=now(),summary=%s WHERE id=%s",(Jsonb(summary),run_id))
                report({**summary,'stage':'failed','failed_stage':stage,'run_id':str(run_id)})
            raise
        finally:
            guard.execute("SELECT pg_advisory_unlock(hashtextextended('pudu-reconciliation',0))")


def clients():
    import app
    if not app.corporate_apparel_source_app_token():raise RuntimeError('行政源表 Token 未配置，不能做全量日校验。')
    primary=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    apparel=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.corporate_apparel_source_app_token())
    return {'primary':primary,'apparel_admin':apparel}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true',required=True);args=parser.parse_args()
    if os.environ.get('PUDU_DATA_SOURCE')!='postgresql':raise RuntimeError('PostgreSQL mode required')
    print(json.dumps(run(clients()),ensure_ascii=False))


if __name__=='__main__':main()
