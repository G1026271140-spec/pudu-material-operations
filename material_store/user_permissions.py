"""Administrator permission edits preserve counters and use the Feishu outbox."""
import hashlib,json
from psycopg.types.json import Jsonb
from . import repository as repo
from .portal_records import roles_for,permission_rows
from .client import DatabaseWriteClient
from .db import connection

def directory(conn):
    row=conn.execute("SELECT payload,updated_at FROM material_ops.documents WHERE name='contact_departments_cache.json'").fetchone()
    if not row or not row[0].get('users'):raise ValueError('公司通讯录尚未完成同步。')
    return row[0]['users'],str(row[1])

def index_permissions(conn):
    import app
    result={}
    for row in permission_rows(conn):
        for actor in app.feishu_person_open_ids(row['fields'],['用户账号']):result.setdefault(actor,[]).append(row)
    return result

def catalog(conn):
    import app
    users,updated=directory(conn);indexed=index_permissions(conn);info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    choices=next(f for f in info['fields'] if f['field_name']=='角色')['property']['options']
    people=[];seen=set()
    for user in users:
        actor=user.get('open_id') or user.get('id')
        if not isinstance(actor,str) or not actor.startswith('ou_') or actor in seen:continue
        seen.add(actor);rows=indexed.get(actor,[]);current=rows[0] if rows else None;fields=current['fields'] if current else {}
        active=[row for row in rows if app.feishu_permission_enabled(row['fields'])]
        combined=set(role for row in (active or rows) for role in app.feishu_choice_values(row['fields'],'角色'))
        states={row['sync_state'] for row in rows}
        people.append({'open_id':actor,'name':user.get('name') or '未命名人员','departments':user.get('department_paths') or [],
            'roles':[choice['name'] for choice in choices if choice['name'] in combined] if current else ['销售'],'enabled':bool(active) if current else True,
            'configured':bool(current),'record_id':current['record_id'] if current else '',
            'version':current['version'] if current else None,'versions':{row['record_id']:row['version'] for row in rows},
            'record_count':len(rows),'sync_state':'conflict' if 'conflict' in states else 'pending' if 'pending' in states else current['sync_state'] if current else '',
            'duplicate':len(rows)>1})
    people.sort(key=lambda user:(user['name'],user['open_id']))
    return {'users':people,'roles':[item['name'] for item in choices],'directory_updated_at':updated,'total':len(people)}

def save(actor,body):
    import app,backend_runtime as runtime
    runtime.release_database_snapshot()
    if not isinstance(body,dict) or set(body) not in ({'open_id','roles','enabled','expected_version','idempotency_key'},{'open_id','roles','enabled','expected_version','expected_versions','idempotency_key'}):raise ValueError('只能修改所选人员的角色和启用状态。')
    target=body['open_id'];key=body['idempotency_key'];selected=body['roles']
    if not actor or not isinstance(target,str) or not target.startswith('ou_') or not isinstance(key,str) or not 8<=len(key)<=150:raise ValueError('人员或提交标识无效。')
    if type(body['enabled']) is not bool or not isinstance(selected,list) or not all(isinstance(role,str) for role in selected) or len(set(selected))!=len(selected):raise ValueError('角色或启用状态无效。')
    if body['enabled'] and not selected:raise ValueError('启用人员至少需要一个角色。')
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-permission-management',0))")
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('user-permission:'+target,))
        if '管理员' not in roles_for(conn,actor):raise PermissionError('仅已启用管理员可修改用户权限。')
        prior=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',('user-permissions:'+key,)).fetchone()
        if prior:
            if prior[0]['actor']!=actor or prior[0]['hash']!=digest:raise repo.VersionConflict('提交标识已用于其他修改。')
            return prior[0]['result']
        users,_=directory(conn)
        if not any((user.get('open_id') or user.get('id'))==target for user in users):raise ValueError('所选人员不在公司通讯录中，请刷新后重试。')
        info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
        choices={o['name'] for f in info['fields'] if f['field_name']=='角色' for o in f['property']['options']}
        if not set(selected)<=choices:raise ValueError('包含未配置的权限角色。')
        indexed=index_permissions(conn);matches=indexed.get(target,[])
        originals=[repo.raw_record(conn,info,row['record_id'],lock=True) for row in sorted(matches,key=lambda row:row['record_id'])]
        old=originals[0] if originals else None
        versions=body.get('expected_versions')
        if versions is not None:
            from .concurrency import check_versions
            check_versions(versions,{row['record_id']:row['version'] for row in originals},'该账号的权限版本无效，请刷新后重试。')
        else:
            expected=body['expected_version']
            from .concurrency import last_commit_wins,check_version
            if last_commit_wins() and old and expected is not None:
                check_version(expected,old['version'],'权限版本无效。')
            if not last_commit_wins() and (len(originals)>1 or (old and (type(expected)is not int or old['version']!=expected)) or (not old and expected is not None)):
                raise repo.VersionConflict('人员权限已被其他操作修改，请刷新后重试。')
        if any(row['sync_state']=='conflict' for row in originals):raise repo.VersionConflict('该人员权限存在飞书同步冲突，请先核对。')
        if not body['enabled'] or '管理员' not in selected:
            admins={person for person,rows in indexed.items() if any(app.feishu_permission_enabled(row['fields']) and '管理员' in app.feishu_choice_values(row['fields'],'角色') for row in rows)}
            if target in admins and not admins-{target}:raise ValueError('必须保留至少一名已启用管理员。')
        runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane='admin')
        client=DatabaseWriteClient(conn)
        patch={'角色':selected,'是否启用':'是' if body['enabled'] else '否'}
        if originals:
            for row in originals:client.update_record(info['table_id'],row['record_id'],patch)
            rid=originals[0]['record_id']
        else:rid=client.batch_create_records(info['table_id'],[{'用户账号':[{'id':target}],**patch}])[0]['record_id']
        current=repo.raw_record(conn,info,rid)
        result={'saved':True,'open_id':target,'version':current['version'],'sync_state':current['sync_state'],'updated_records':len(originals) or 1}
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',('user-permissions:'+key,Jsonb({'actor':actor,'hash':digest,'result':result})))
        return result
