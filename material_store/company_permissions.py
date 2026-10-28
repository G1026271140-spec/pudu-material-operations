"""One-time directory provisioning with stable accounts, quota-safe merging and outbox writes."""
from collections import defaultdict
import hashlib,json
from psycopg import sql
from psycopg.types.json import Jsonb
from . import repository as repo,user_permissions as permissions
from .client import DatabaseWriteClient
from .db import connection

TABLE='tblytA4DHQVbJiIJ'

def fingerprint(users,rows):
    return hashlib.sha256(json.dumps({'users':sorted({u.get('open_id') or u.get('id') for u in users if str(u.get('open_id') or u.get('id') or '').startswith('ou_')}),
        'records':sorted(rows,key=lambda r:r['record_id'])},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def plan(conn):
    import app
    users,updated=permissions.directory(conn);info=repo.table(conn,TABLE);rows=repo.rows(conn,info)
    indexed=defaultdict(list)
    for row in rows:
        actors=app.feishu_person_open_ids(row['fields'],['用户账号'])
        if len(actors)!=1:raise ValueError('权限记录必须对应唯一用户账号，不能按姓名合并。')
        indexed[actors[0]].append(row)
    identities=sorted({u.get('open_id') or u.get('id') for u in users if str(u.get('open_id') or u.get('id') or '').startswith('ou_')})
    counters=[f for f in info['fields'] if '数量累计' in f['field_name'] and f['type'] in {1,2}]
    defaults={f['field_name']:'0' if f['type']==1 else 0 for f in counters}
    missing=[{'用户账号':[{'id':identity}],'角色':['销售'],'是否启用':'是',**defaults} for identity in identities if identity not in indexed]
    roles=next(f for f in info['fields'] if f['field_name']=='角色')['property']['options']
    merges=[];mapping={}
    for actor,matches in sorted(indexed.items()):
        if len(matches)<2:continue
        def order(row):
            number=app.feishu_text(row['fields'],'用户编号')
            return (int(number) if number.isdigit() else 10**20,row['record_id'])
        matches.sort(key=order);keep=matches[0]
        active=[row for row in matches if app.feishu_permission_enabled(row['fields'])]
        combined={role for row in (active or matches) for role in app.feishu_choice_values(row['fields'],'角色')}
        patch={'角色':[option['name'] for option in roles if option['name'] in combined],'是否启用':'是' if active else '否'}
        for field in counters:
            name=field['field_name'];used=max(app.feishu_int(row['fields'],name) for row in matches)
            patch[name]=str(used) if field['type']==1 else used
        # Preserve every nonempty non-role field. Ambiguous free text must be
        # reviewed rather than silently overwritten during physical deduplication.
        for field in info['fields']:
            name=field['field_name']
            if name in patch or name in {'用户账号','用户编号'} or field['type'] in {18,19,20,21} or field['type']>=1000:continue
            values=[row['fields'].get(name) for row in matches if row['fields'].get(name) not in (None,'',[])]
            unique={json.dumps(value,ensure_ascii=False,sort_keys=True) for value in values}
            if len(unique)>1:raise ValueError('重复权限记录的 '+name+' 内容不一致，不能自动丢弃。')
            if values and not keep['fields'].get(name):patch[name]=values[0]
        removed=[row['record_id'] for row in matches[1:]]
        mapping.update({key:keep['record_id'] for key in removed})
        merges.append({'open_id':actor,'keep':keep['record_id'],'remove':removed,'patch':patch})
    linked=[]
    for row in rows:
        patch={}
        for field in info['fields']:
            if field['type'] not in {18,21} or (field.get('property') or {}).get('table_id')!=TABLE:continue
            ids=repo.link_ids(row['fields'].get(field['field_name']))
            if any(key in mapping for key in ids):patch[field['field_name']]=list(dict.fromkeys(mapping.get(key,key) for key in ids))
        if patch:linked.append({'record_id':row['record_id'],'patch':patch})
    return {'fingerprint':fingerprint(users,rows),'directory_updated_at':updated,'directory_people':len(identities),
        'existing_unique_accounts':len(indexed),'create':missing,'merge':merges,'remap_links':linked,
        'summary':{'new_sales_accounts':len(missing),'duplicate_accounts':len(merges),'duplicate_records_removed':len(mapping),'links_remapped':len(linked)}}

def apply(planned,actor='system:company-directory'):
    import backend_runtime as runtime
    with connection() as conn,conn.transaction(),runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-permission-management',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:cultural',0))")
        token='company-permissions:'+planned['fingerprint']
        prior=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(token,)).fetchone()
        if prior:return prior[0]
        current=plan(conn)
        if current!=planned:raise repo.VersionConflict('通讯录或权限记录已变化，请重新预览。')
        if conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND state IN ('pending','processing','retry','conflict'))",(TABLE,)).fetchone()[0]:
            raise repo.VersionConflict('权限表仍有未完成的同步，不能批量合并。')
        runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane='admin')
        client=DatabaseWriteClient(conn)
        for merge in current['merge']:client.update_record(TABLE,merge['keep'],merge['patch'])
        for entry in current['remap_links']:client.update_record(TABLE,entry['record_id'],entry['patch'])
        for merge in current['merge']:
            for record in merge['remove']:client.delete_record(TABLE,record)
        client.batch_create_records(TABLE,current['create'])
        result={**current['summary'],'directory_people':current['directory_people'],'fingerprint':current['fingerprint'],'writes':'postgresql_then_outbox'}
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',(token,Jsonb(result)))
        return result

def refresh_source(client):
    """Only the permission table; preserve local aliases and reject pending writes."""
    from .reconcile import reconcile_snapshot
    with connection() as guard:
        guard.execute("SELECT pg_advisory_lock(hashtextextended('pudu-reconciliation',0))")
        try:
            if guard.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND state IN ('pending','processing','retry','conflict'))",(TABLE,)).fetchone()[0]:
                raise repo.VersionConflict('权限同步尚未完成，不能载入源表快照。')
            records=client.list_records(TABLE)
            with guard.transaction():
                stats=reconcile_snapshot(guard,repo.table(guard,TABLE),records,None)
                guard.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('company-permissions-source-refresh',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",(Jsonb(stats),))
            return stats
        finally:guard.execute("SELECT pg_advisory_unlock(hashtextextended('pudu-reconciliation',0))")
