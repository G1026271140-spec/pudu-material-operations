"""Audited repair of unsynced legacy PO-prefix collisions, never business replay."""
from datetime import datetime
from psycopg import sql
from psycopg.types.json import Jsonb
from . import repository as repo
import order_scheduling as rules


def plan(conn, remote_batches):
    info=repo.named_table(conn,rules.BATCH_TABLE)
    names={f['field_name']:f['field_id'] for f in info['fields']}
    candidates=conn.execute('''SELECT o.id::text,o.record_key,o.local_version,o.patch,o.last_error FROM material_ops.outbox o
        WHERE o.table_id=%s AND o.operation='create' AND o.state='conflict' ORDER BY o.created_at''',(info['table_id'],)).fetchall()
    plans=[]
    local_rows=repo.rows(conn,info)
    for oid,key,version,patch,error in candidates:
        if error!='SourceConflict: 飞书已有该下单编号的不同内容，等待核对。':continue
        row=repo.raw_record(conn,info,key,include_deleted=True)
        fields=repo.feishu_record(info,row)['fields']
        number=fields.get('下单批次号','');generation=fields.get('生成幂等键','')
        if row['remote_id'] or row['deleted'] or not generation.startswith('allocation:') or not number.endswith('-ALLOCATION'):continue
        if sum(rules_text(r,'生成幂等键')==generation for r in local_rows)!=1:raise ValueError('本地存在重复生成幂等键，不能自动修复。')
        day=datetime.strptime(number[3:11],'%Y%m%d').date()
        if number!=f'PO-{day:%Y%m%d}-ALLOCATION':raise ValueError('旧下单编号格式异常，不能自动修复。')
        same_key=[r for r in remote_batches if rules_text(r,'生成幂等键')==generation]
        if same_key:raise ValueError('飞书已存在相同生成幂等键，需先核对远端记录，不能重建。')
        collisions=[r for r in remote_batches if rules_text(r,'下单批次号')==number]
        if not collisions or any(not rules_text(r,'生成幂等键') for r in collisions):raise ValueError('未证实为不同生成键导致的旧编号碰撞，不能自动修复。')
        new_number=rules.batch_number(generation,day=day)
        if any(rules_text(r,'下单批次号')==new_number for r in remote_batches+local_rows):raise ValueError('修复目标编号已存在。')
        if row['version']!=version or patch.get(names['下单批次号'])!=number or patch.get(names['生成幂等键'])!=generation:
            raise ValueError('记录或原始创建任务已变化，请重新核对。')
        plans.append({'table_id':info['table_id'],'record_key':key,'outbox_id':oid,'version':version,'generation_key':generation,
                      'old_number':number,'new_number':new_number,'collision_remote_ids':[r['record_id'] for r in collisions]})
    return plans


def rules_text(row,name):
    from .field_registry import scalar_text
    return scalar_text((row.get('fields') or {}).get(name)) or ''


def apply(conn, plans):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        for change in plans:
            info=repo.table(conn,change['table_id'])
            if info['source']!='primary' or info['name']!=rules.BATCH_TABLE:raise ValueError('只能修复指定下单批次表。')
            fid=next(f['field_id'] for f in info['fields'] if f['field_name']=='下单批次号')
            gen=next(f['field_id'] for f in info['fields'] if f['field_name']=='生成幂等键')
            resource='outbox-record:'+info['table_id']+':'+change['record_key']
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(resource,))
            old=repo.raw_record(conn,info,change['record_key'],lock=True,include_deleted=True)
            task=conn.execute('SELECT state,patch,local_version,last_error FROM material_ops.outbox WHERE id=%s FOR UPDATE',(change['outbox_id'],)).fetchone()
            if (old['remote_id'] or old['deleted'] or old['version']!=change['version'] or old['fields'].get(fid)!=change['old_number']
                or old['fields'].get(gen)!=change['generation_key'] or not task or task[0]!='conflict' or task[2]!=change['version']):
                raise ValueError('修复前记录已变化，未修改任何记录。')
            if task[1].get(fid)!=change['old_number'] or task[1].get(gen)!=change['generation_key']:raise ValueError('原创建任务内容已变化。')
            later=conn.execute('SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND local_version>%s)',(info['table_id'],old['record_id'],change['version'])).fetchone()[0]
            if later:raise ValueError('该记录存在后续变更，不能折叠修复。')
            version=old['version']+1
            values={**old['fields'],fid:change['new_number']}
            repo.replace_values(conn,info,old['record_id'],values,version=version,state='pending')
            conn.execute("""UPDATE material_ops.outbox SET patch=%s,local_version=%s,state='retry',available_at=clock_timestamp(),
                last_error=NULL,claim_token=NULL,lease_until=NULL WHERE id=%s""",(Jsonb({**task[1],fid:change['new_number']}),version,change['outbox_id']))
            conn.execute("""INSERT INTO material_ops.audit(table_id,record_key,field_id,source,before_value,after_value,local_version,actor_open_id)
                VALUES (%s,%s,%s,'worker',%s,%s,%s,'worker:order-batch-recovery')""",(info['table_id'],old['record_id'],fid,Jsonb(change['old_number']),Jsonb(change['new_number']),version))
            conn.execute('''INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)''',
                ('order-batch-repair:'+change['outbox_id'],Jsonb({**change,'previous_error':task[3],'reason':'legacy generation-prefix collision','new_version':version})))
    return len(plans)
