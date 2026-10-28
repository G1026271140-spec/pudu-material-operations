"""Send one durable admin result after each management/allocation/shipping operation."""
import json
from uuid import UUID
from psycopg.types.json import Jsonb
import backend_runtime as runtime
from .db import connection
from . import repository as repo

TASKS={'采购补库','库存减库','物料品类同步','物料品类删除','型号语种管理','文化周边管理',
    '申请物料库存编辑','申请物料库存确认','申请物料库存驳回','物料申请撤回删除','库存提交撤回','库存提交修正','发货信息同步'}
PREFIX='admin-completion:'
SUPPRESSED_SUCCESS={
    '申请物料库存编辑':('配货调整沿用原卡片更新，不额外发送完成通知','original_allocation_cards_updated'),
    '发货信息同步':('保留申请人发货卡片，跳过管理员发货同步成功通知','applicant_shipping_card_retained'),
}

def register(conn,job_id,kind,payload,result,actor=''):
    if kind not in TASKS:return
    if conn.execute('SELECT 1 FROM material_ops.documents WHERE name=%s',(PREFIX+str(job_id),)).fetchone():return
    dependencies={str(row[0]) for row in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s',(job_id,))}
    for table_id,key in runtime.request_state.get('_write_touched',set()):
        dependencies.update(str(row[0]) for row in conn.execute("SELECT id FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND state IN ('pending','processing','retry')",(table_id,key)))
    effect_ids=[str(row[0]) for row in conn.execute('SELECT id FROM material_ops.effects WHERE job_id=%s',(job_id,))]
    draft=payload.get('draft') or payload.get('sync_args') or payload
    details=[]
    for label,names in [('申请单',['request_no','request_id']),('业务单号',['restock_no','purchase_order_no']),('品类',['category','name','category_name']),('变更说明',['change_note','note'])]:
        value=next((draft[name] for name in names if draft.get(name)),None)
        if value:details.append(label+'：'+str(value)[:500])
    if result.get('entries'):details.append('申请单：'+'、'.join(str(row.get('request_no') or row.get('request_id')) for row in result['entries'])[:1500])
    counts={key:value for key,value in result.items() if isinstance(value,(int,bool))}
    if counts:details.append('处理结果：'+json.dumps(counts,ensure_ascii=False)[:800])
    data={'state':'waiting','job_id':str(job_id),'kind':kind,'actor':actor or draft.get('operator_open_id') or draft.get('operator') or '系统',
          'details':details,'outbox_ids':sorted(dependencies),'effect_ids':effect_ids}
    conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO NOTHING',(PREFIX+str(job_id),Jsonb(data)))

def run_once():
    from . import effects,portal_records
    import app
    with runtime.request_scope(),connection() as conn,conn.transaction():
        # Also suppress legacy success receipts that were queued before this
        # policy changed and have never been attempted. Applicant effects and
        # failed/ambiguous sends remain untouched.
        obsolete=conn.execute("""UPDATE material_ops.effects e SET state='done',completed_at=clock_timestamp(),
            last_error='按通知设置跳过管理员成功回执' FROM material_ops.jobs j
            WHERE e.job_id=j.id AND j.task_type=ANY(%s) AND e.kwargs ? '_admin_completion'
              AND e.kwargs->>'_completion_status'='任务已完成'
              AND e.state IN ('pending','retry') AND e.first_attempt_at IS NULL
            RETURNING e.job_id""",(list(SUPPRESSED_SUCCESS),)).fetchall()
        for job_id in {str(row[0]) for row in obsolete}:
            conn.execute("UPDATE material_ops.documents SET payload=payload || %s,updated_at=clock_timestamp() WHERE name=%s",
                (Jsonb({'state':'skipped','reason':'按通知设置跳过管理员成功回执'}),PREFIX+job_id))
        # Inspect several waiting jobs so an older slow task never blocks the rest.
        rows=conn.execute("SELECT name,payload FROM material_ops.documents WHERE name LIKE 'admin-completion:%' AND payload->>'state'='waiting' ORDER BY updated_at LIMIT 30 FOR UPDATE SKIP LOCKED").fetchall()
        for name,data in rows:
            job=conn.execute('SELECT state,last_error FROM material_ops.jobs WHERE id=%s',(data['job_id'],)).fetchone()
            if not job or job[0] in {'pending','processing','retry'}:continue
            outbox=conn.execute('SELECT state FROM material_ops.outbox WHERE id::text=ANY(%s)',(data['outbox_ids'],)).fetchall()
            if any(row[0] in {'pending','processing','retry'} for row in outbox):continue
            blocked=job[0]=='failed' or len(outbox)!=len(data['outbox_ids']) or any(row[0] in {'conflict','cancelled'} for row in outbox)
            previous=conn.execute('SELECT state FROM material_ops.effects WHERE id::text=ANY(%s)',(data['effect_ids'],)).fetchall()
            if not blocked and any(row[0] in {'pending','processing','retry'} for row in previous):continue
            good=job[0]=='done' and len(outbox)==len(data['outbox_ids']) and all(row[0]=='done' for row in outbox) and all(row[0]=='done' for row in previous)
            # Applicant shipping cards and original allocation cards remain
            # the business notifications. Failures still need admin attention.
            if good and data['kind'] in SUPPRESSED_SUCCESS:
                explanation,reason=SUPPRESSED_SUCCESS[data['kind']]
                data.update(state='skipped',reason=explanation)
                conn.execute('UPDATE material_ops.documents SET payload=%s,updated_at=now() WHERE name=%s',(Jsonb(data),name))
                return {'job_id':data['job_id'],'skipped':True,'reason':reason}
            status='任务已完成' if good else '任务需核对'
            users={actor for row in portal_records.permission_rows(conn) if app.feishu_permission_enabled(row['fields']) and '管理员' in app.feishu_choice_values(row['fields'],'角色') for actor in app.feishu_person_open_ids(row['fields'],['用户账号'])}
            directory=conn.execute("SELECT payload FROM material_ops.documents WHERE name='contact_departments_cache.json'").fetchone()
            actor=data['actor']
            if directory:actor=next((u.get('name') for u in directory[0].get('users',[]) if u.get('open_id')==actor),actor)
            subject=''
            for detail in data['details']:
                if detail.startswith(('申请单：','业务单号：','品类：')):
                    subject=detail
                    break
            if subject.startswith('申请单：'):
                identities=subject[len('申请单：'):].split('、');numbers=[]
                info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
                for identity in identities:
                    if identity.startswith(('local_','rec')):
                        try:
                            row=repo.raw_record(conn,info,identity,include_deleted=True)
                            fields=repo.feishu_record(info,row)['fields']
                            identity=app.feishu_text(fields,'申请单号')
                        except ValueError:identity=''
                    if identity and not identity.startswith(('local_','rec')):numbers.append(identity)
                subject='申请单：'+'、'.join(numbers) if numbers else ''
            from .task_result_card import card as result_card
            import os
            receipt=result_card(data['kind'],actor,subject,good,os.environ.get('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work'))
            ordinal=conn.execute('SELECT coalesce(max(ordinal),0) FROM material_ops.effects WHERE job_id=%s',(data['job_id'],)).fetchone()[0]
            runtime.request_state.update(_write_conn=conn,_job_id=data['job_id'],_effect_ordinal=ordinal)
            for recipient in sorted(users):effects.defer('primary','send_interactive_message',[recipient,receipt],{'receive_id_type':'open_id','_admin_completion':data['job_id'],'_completion_status':status})
            data.update(state='queued',recipients=len(users),status=status)
            conn.execute('UPDATE material_ops.documents SET payload=%s,updated_at=now() WHERE name=%s',(Jsonb(data),name))
            return {'job_id':data['job_id'],'recipients':len(users),'status':status}
    return None
