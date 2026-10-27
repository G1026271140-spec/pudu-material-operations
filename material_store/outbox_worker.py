"""Claim durable local changes and publish them with field-level conflict checks."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import time
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from .db import connection
from . import repository as repo

LOGGER = logging.getLogger(__name__)
LANES = ('ordinary', 'cultural', 'admin', 'notification')


class SourceConflict(Exception):
    pass


class DependencyPending(Exception):
    pass


def _canonical(field, value):
    kind = int(field['type'])
    if kind in {18, 21}:
        return sorted(repo.link_ids(value))
    if kind == 17:
        return [x.get('file_token') for x in value or [] if isinstance(x, dict) and x.get('file_token')]
    if kind == 11:
        return sorted(x.get('id') or x.get('open_id') for x in value or [] if isinstance(x, dict))
    if kind == 4:
        return sorted(x.get('text') if isinstance(x, dict) else x for x in value or [])
    if kind in {1,3,13}:
        from .field_registry import scalar_text
        return scalar_text(value) or ''
    if isinstance(value, dict):
        value = value.get('value', value.get('text', value.get('name', value)))
    if isinstance(value, list) and kind not in {4, 11, 17, 18, 21}:
        value = value[0] if value else None
    if kind == 2:
        return str(repo.number(value).normalize())
    if kind == 5:
        return int(value) if value is not None else None
    return value


def _remote_fields(info, values, client):
    result = {}
    definitions = {f['field_id']: f for f in info['fields']}
    from .effects import resolve
    with connection() as conn:values=resolve(conn,values)
    for field_id, value in values.items():
        field = definitions[field_id]
        kind = int(field['type'])
        if kind in {19, 20} or kind >= 1000:
            continue
        if kind in {18, 21}:
            linked = []
            with connection() as conn:
                target = repo.table(conn, field['property']['table_id'])
                for key in repo.link_ids(value):
                    record = repo.raw_record(conn, target, key,include_deleted=True)
                    if record.get('deleted'):continue
                    if not record['remote_id']:
                        raise DependencyPending('关联记录尚未同步。')
                    linked.append(record['remote_id'])
            value = linked
        elif kind == 17:
            from .media import remote_token
            value = [{'file_token': item.get('file_token') or remote_token(item['local_media_id'], client)} for item in value or []]
        result[field['field_name']] = value
    return result


def delete_conflicts(conn, info, row, remote, client):
    """Check deletion against saved source values, allowing reciprocal cleanup.

    Old locally created records have no baseline for Feishu-generated backlinks
    or the automatic applicant department. Other absent values remain guarded.
    """
    baseline = row['baseline'] or {}
    current = remote.get('fields') or {}
    conflicts = []
    for field in info['fields']:
        fid = field['field_id']
        kind = int(field['type'])
        if kind in {19, 20} or kind >= 1000:
            continue
        if fid not in baseline and (
                (kind == 21 and (field.get('property') or {}).get('back_field_id'))
                or (info['name'] == '物料申请单' and field['field_name'] == '申请人.部门')):
            continue
        actual = _canonical(field, current.get(field['field_name']))
        if kind in {18, 21}:
            target = repo.table(conn, field['property']['table_id'])
            expected = []
            tombstones = set()
            for key, remote_id, deleted in conn.execute(
                    sql.SQL('SELECT _record_key,_remote_id,_deleted FROM material_data.{}')
                    .format(sql.Identifier(target['sql_table']))):
                if deleted:
                    tombstones.update(x for x in (key, remote_id) if x)
            for key in repo.link_ids(baseline.get(fid)):
                try:
                    linked = repo.raw_record(conn, target, key, include_deleted=True)
                    mapped = linked['remote_id'] or key
                except ValueError:
                    mapped = key  # Preserve known historic dangling source IDs.
                if key not in tombstones and mapped not in tombstones:
                    expected.append(mapped)
            expected = sorted(expected)
            actual = [key for key in actual if key not in tombstones]
        else:
            expected = _canonical(field, _remote_fields(info, {fid: baseline.get(fid)}, client).get(field['field_name']))
        if actual != expected:
            conflicts.append(field['field_name'])
    return conflicts


def claim(lane, worker_id):
    if lane not in LANES:
        raise ValueError('Unknown outbox lane')
    with connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        row = conn.execute("""SELECT id,table_id,record_key,local_version,patch,operation,attempts
            FROM material_ops.outbox o WHERE lane=%s
             AND ((state IN ('pending','retry') AND available_at<=now())
                  OR (state='processing' AND lease_until<now()))
             AND NOT EXISTS (SELECT 1 FROM material_ops.outbox earlier
               WHERE earlier.table_id=o.table_id AND earlier.record_key=o.record_key
                AND earlier.local_version<o.local_version AND earlier.state IN ('pending','processing','retry'))
            ORDER BY CASE (SELECT table_name FROM material_meta.tables t WHERE t.table_id=o.table_id)
                WHEN '物料申请单' THEN 0 WHEN '申请明细' THEN 1
                WHEN '库存流水' THEN 2 ELSE 3 END, ordinal
            LIMIT 1 FOR UPDATE OF o SKIP LOCKED""", (lane,)).fetchone()
        if row is None:
            return None
        token = uuid4()
        conn.execute("""UPDATE material_ops.outbox SET state='processing',claim_token=%s,
            claimed_by=%s,lease_until=now()+interval '3 minutes',attempts=attempts+1
            WHERE id=%s""", (token, worker_id, row[0]))
        return {'id': row[0], 'table_id': row[1], 'record_key': row[2], 'version': row[3],
                'patch': row[4], 'operation': row[5], 'attempts': row[6]+1, 'claim_token': token}


def _find_remote_create(client, info, fields):
    # A retry after a successful remote create must find the existing record.
    for name in ('提交幂等键', '幂等键', '原Supabase ID', '明细编号', '用户编号', '物料编码', '文化周边编码', '型号编号', '战区名称', '语言种类', '产品型号', '物料品类', '编码'):
        identity = fields.get(name)
        if identity and any(f['field_name']==name for f in info['fields']):
            field=next(f for f in info['fields'] if f['field_name']==name)
            matches = [r for r in client.list_records(info['table_id'])
                       if _canonical(field,(r.get('fields') or {}).get(name)) == _canonical(field,identity)]
            if len(matches) > 1:
                raise SourceConflict('飞书存在重复的创建标识。')
            return matches[0] if matches else None
    raise SourceConflict('创建任务缺少可查重的业务标识。')


def publish(task, client):
    with connection() as conn:
        info = repo.table(conn, task['table_id'])
        row = repo.raw_record(conn, info, task['record_key'],include_deleted=True)
        baseline = row['baseline'] or {}
        remote_id = row['remote_id']
    if isinstance(client,dict):
        if info['source'] not in client:raise SourceConflict('来源表未配置对应的飞书应用。')
        client=client[info['source']]
    elif info['source']!='primary':raise SourceConflict('来源表未配置对应的飞书应用。')
    if task['operation']=='delete':
        if not remote_id:return None
        from feishu_bitable import FeishuBitableError
        try:
            remote=client.get_record(info['table_id'],remote_id)
        except FeishuBitableError as exc:
            if '1254043' in str(exc):return remote_id
            raise
        # A delete may not erase a manual Feishu edit made since the last sync.
        with connection() as conn:
            conflicts = delete_conflicts(conn, info, row, remote, client)
        if conflicts:
            raise SourceConflict('飞书记录已经变化，删除任务等待人工核对。字段：' + '、'.join(conflicts))
        client.delete_record(info['table_id'],remote_id)
        return remote_id
    named = _remote_fields(info, task['patch'], client)
    if task['operation'] == 'create':
        if not named:
            raise SourceConflict('创建任务没有可写字段。')
        existing = _find_remote_create(client, info, named)
        created = existing or client.batch_create_records(info['table_id'], [named])[0]
        remote_id = created['record_id']
    else:
        if not remote_id:
            raise DependencyPending('本地记录尚未取得飞书 ID。')
        remote = client.get_record(info['table_id'], remote_id)
        remote_values = (remote.get('fields') or {})
        for fid in task['patch']:
            field = next(f for f in info['fields'] if f['field_id'] == fid)
            if fid not in baseline:
                continue
            current = _canonical(field, remote_values.get(field['field_name']))
            expected = _canonical(field, _remote_fields(info,{fid:baseline[fid]},client).get(field['field_name']))
            target = _canonical(field, named.get(field['field_name']))
            if current != expected and current != target:
                raise SourceConflict('飞书该字段已经被人工修改，等待校验。')
        if any(_canonical(next(f for f in info['fields'] if f['field_name']==name),remote_values.get(name))
               != _canonical(next(f for f in info['fields'] if f['field_name']==name),value)
               for name,value in named.items()):
            client.update_record(info['table_id'], remote_id, named)
    return remote_id


def finish(task, remote_id):
    with connection() as conn, conn.transaction():
        info=repo.table(conn, task['table_id'])
        row=repo.raw_record(conn,info,task['record_key'],lock=True,include_deleted=True)
        state=conn.execute("SELECT state,claim_token FROM material_ops.outbox WHERE id=%s FOR UPDATE",(task['id'],)).fetchone()
        if state != ('processing',task['claim_token']):
            raise RuntimeError('任务租约已变更，不能完成旧任务。')
        from psycopg import sql
        baseline={**(row['baseline'] or {}),**task['patch']}
        conn.execute(sql.SQL("UPDATE material_data.{} SET _remote_id=%s,_baseline=%s,_synced_version=GREATEST(_synced_version,%s),_sync_state=%s WHERE _record_key=%s").format(sql.Identifier(info['sql_table'])),
                     (remote_id,Jsonb(baseline),task['version'],'synced' if row['version']==task['version'] else 'pending',task['record_key']))
        conn.execute("UPDATE material_ops.outbox SET state='done',completed_at=now(),lease_until=NULL,claim_token=NULL,last_error=NULL WHERE id=%s",(task['id'],))
        conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value,local_version) VALUES (%s,%s,'worker',%s,%s)",
                     (info['table_id'],task['record_key'],Jsonb({'outbox_id':str(task['id']),'sync':'done'}),task['version']))


def fail(task, exc):
    conflict=isinstance(exc,SourceConflict)
    delay=min(1800,2 ** min(task['attempts'],10))
    with connection() as conn,conn.transaction():
        conn.execute("""UPDATE material_ops.outbox SET state=%s,available_at=now()+(%s * interval '1 second'),
          lease_until=NULL,claim_token=NULL,last_error=%s
          WHERE id=%s AND claim_token=%s""",
          ('conflict' if conflict else 'retry',delay,type(exc).__name__+': '+str(exc)[:400],task['id'],task['claim_token']))
        if conflict:
            from psycopg import sql
            info=repo.table(conn,task['table_id'])
            conn.execute(sql.SQL("UPDATE material_data.{} SET _sync_state='conflict' WHERE _record_key=%s").format(sql.Identifier(info['sql_table'])),(task['record_key'],))


def run_once(lane, client, worker_id='outbox-worker'):
    import psycopg
    # Session locks include the HTTP step and are automatically released on a
    # process crash. They also prevent reconciliation racing an active write.
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as guard:
        guard.execute("SELECT pg_advisory_lock_shared(hashtextextended('pudu-reconciliation',0))")
        task=claim(lane,worker_id)
        if task is None:return None
        resource='outbox-record:'+task['table_id']+':'+task['record_key']
        if not guard.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(resource,)).fetchone()[0]:
            fail(task,DependencyPending('同一记录的同步仍在执行。'))
            return {'id':str(task['id']),'state':'retry'}
        try:
            remote_id=publish(task,client)
            finish(task,remote_id)
            return {'id':str(task['id']),'state':'done'}
        except Exception as exc:
            fail(task,exc)
            LOGGER.warning('Outbox task %s: %s',task['id'],type(exc).__name__)
            return {'id':str(task['id']),'state':'conflict' if isinstance(exc,SourceConflict) else 'retry'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane',choices=LANES,required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if os.environ.get('PUDU_DATA_SOURCE')!='postgresql':
        raise RuntimeError('PostgreSQL mode required')
    import app
    client={'primary':app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())}
    if app.corporate_apparel_source_app_token():
        client['apparel_admin']=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.corporate_apparel_source_app_token())
    if not all((app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())):
        raise RuntimeError('Application identity is not configured')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    identity=f'{os.uname().nodename}:{os.getpid()}:{args.lane}'
    heartbeat_at=0
    while True:
        result=run_once(args.lane,client,identity)
        if time.monotonic()-heartbeat_at>=10:
            with connection() as conn:
                conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",
                             ('worker:'+args.lane,Jsonb({'worker':identity,'version':app.APP_VERSION,'lane':args.lane})))
            heartbeat_at=time.monotonic()
        if args.once:
            print(json.dumps(result or {'state':'empty'}))
            return
        if result is None:time.sleep(2)


if __name__=='__main__':
    main()
