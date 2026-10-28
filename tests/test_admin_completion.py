from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock
import pytest
from psycopg.types.json import Jsonb
import app,backend_runtime as runtime
from test_account_tools import account_store
from test_shipping_calendar import store
from material_store import admin_completion as completion,jobs,repository as repo,effects,shipping_calendar as shipping

@pytest.fixture
def notices(account_store,monkeypatch):
    conn,ids=account_store
    @contextmanager
    def same():yield conn
    for module in [completion,jobs,effects]:monkeypatch.setattr(module,'connection',same)
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    repo.insert_source_records(conn,info,[{'record_id':'rec_admin_duplicate_'+uuid4().hex,'fields':{'用户账号':[{'id':ids['admin']}],'角色':['管理员'],'是否启用':'是'}}])
    return conn,ids

def monitored(conn,kind='采购补库'):
    task,_=jobs.enqueue(kind,'completion-test-'+uuid4().hex,{'draft':{'operator':'测试操作人','restock_no':'RESTOCK-ISOLATED'}},conn=conn)
    outbox=conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,operation,job_id) VALUES (%s,'admin',%s,'isolated',1,'{}','update',%s) RETURNING id",(uuid4().hex,'tblytA4DHQVbJiIJ',task.task_id)).fetchone()[0]
    with runtime.request_scope():
        runtime.request_state.update(_write_conn=conn,_job_id=task.task_id,_effect_ordinal=0)
        effects.defer('primary','send_text_message',['ou_applicant','isolated'],{'receive_id_type':'open_id','_outbox_ids':[str(outbox)]})
        completion.register(conn,task.task_id,kind,task.payload,{'updated':1},'测试操作人')
    conn.execute("UPDATE material_ops.jobs SET state='done' WHERE id=%s",(task.task_id,))
    return task,outbox

def test_admin_success_waits_for_source_and_applicant_but_sends_no_extra_receipt(notices):
    conn,ids=notices;task,outbox=monitored(conn)
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE id=%s",(outbox,))
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(task.task_id,))
    assert completion.run_once()['skipped']
    assert completion.run_once() is None
    assert conn.execute("SELECT count(*) FROM material_ops.effects WHERE kwargs ? '_admin_completion'").fetchone()[0]==0


def test_source_conflict_reports_needs_review_instead_of_claiming_completed(notices):
    conn,ids=notices;task,outbox=monitored(conn)
    conn.execute("UPDATE material_ops.outbox SET state='conflict' WHERE id=%s",(outbox,))
    result=completion.run_once();assert result['status']=='任务需核对'
    text=conn.execute("SELECT args->1 FROM material_ops.effects WHERE kwargs ? '_admin_completion'").fetchone()[0]
    assert '任务需核对' in __import__('json').dumps(text,ensure_ascii=False) and '均已更新' not in __import__('json').dumps(text,ensure_ascii=False)

def test_legacy_jobs_never_retroactively_send_admin_receipts(notices):
    conn,ids=notices
    task,_=jobs.enqueue('采购补库','legacy-'+uuid4().hex,{},conn=conn)
    conn.execute("UPDATE material_ops.jobs SET state='done' WHERE id=%s",(task.task_id,))
    assert completion.run_once() is None

def test_disabled_admin_does_not_receive_completion(notices):
    conn,ids=notices;task,outbox=monitored(conn)
    permission=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    repo.insert_source_records(conn,permission,[{'record_id':'rec_disabled_admin_'+uuid4().hex,'fields':{'用户账号':[{'id':ids['other']}],'角色':['管理员'],'是否启用':'否'}}])
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE id=%s",(outbox,))
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(task.task_id,))
    conn.execute("UPDATE material_ops.outbox SET state='conflict' WHERE id=%s",(outbox,))
    assert completion.run_once()['recipients']==1


def test_allocation_edit_updates_original_cards_without_extra_success_receipt(notices):
    conn,ids=notices;task,outbox=monitored(conn,'申请物料库存编辑')
    original=conn.execute('SELECT id,args,kwargs FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchone()
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE id=%s",(outbox,))
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(task.task_id,))
    result=completion.run_once();assert result['skipped'] is True
    assert completion.run_once() is None
    assert conn.execute('SELECT id,args,kwargs FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchall()==[original]
    assert conn.execute("SELECT payload->>'state' FROM material_ops.documents WHERE name=%s",(completion.PREFIX+task.task_id,)).fetchone()[0]=='skipped'


def test_failed_allocation_sync_still_reports_needs_review(notices):
    conn,ids=notices;task,outbox=monitored(conn,'申请物料库存编辑')
    conn.execute("UPDATE material_ops.outbox SET state='conflict' WHERE id=%s",(outbox,))
    result=completion.run_once();assert result['status']=='任务需核对'
    receipt=conn.execute("SELECT args->1 FROM material_ops.effects WHERE kwargs ? '_admin_completion'").fetchone()[0]
    assert receipt['header']['title']['content']=='配货任务需核对'


@pytest.mark.parametrize('shipped',[True,False])
def test_shipping_keeps_applicant_card_without_admin_success_receipt(notices,shipped):
    from test_shipping_batch import request,change,batch
    conn,ids=notices;key=request(conn)
    result=shipping.save_batch(ids['admin'],batch([change(conn,key,shipped=shipped)]))
    job=result['batch_id']
    original=conn.execute('SELECT id,args,kwargs FROM material_ops.effects WHERE job_id=%s',(job,)).fetchall()
    assert len(original)==1 and original[0][2]['_shipping_request']==key
    expected='您的物料申请已发货' if shipped else '您的物料申请发货信息已更新'
    assert original[0][1][1]['header']['title']['content']==expected
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE job_id=%s",(job,))
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(job,))
    skipped=completion.run_once()
    assert skipped['skipped'] and skipped['reason']=='applicant_shipping_card_retained'
    assert conn.execute('SELECT id,args,kwargs FROM material_ops.effects WHERE job_id=%s',(job,)).fetchall()==original
    assert conn.execute("SELECT payload->>'state' FROM material_ops.documents WHERE name=%s",(completion.PREFIX+job,)).fetchone()[0]=='skipped'
    assert completion.run_once() is None


def test_shipping_sync_failure_still_alerts_administrators(notices):
    conn,ids=notices;task,outbox=monitored(conn,'发货信息同步')
    conn.execute("UPDATE material_ops.outbox SET state='conflict' WHERE id=%s",(outbox,))
    assert completion.run_once()['status']=='任务需核对'
    receipt=conn.execute("SELECT args->1 FROM material_ops.effects WHERE kwargs ? '_admin_completion'").fetchone()[0]
    assert receipt['header']['title']['content']=='发货任务需核对'


def test_previously_queued_never_attempted_shipping_success_is_skipped(notices):
    conn,ids=notices;task,outbox=monitored(conn,'发货信息同步')
    with runtime.request_scope():
        runtime.request_state.update(_write_conn=conn,_job_id=task.task_id,_effect_ordinal=1)
        effects.defer('primary','send_interactive_message',[ids['admin'],{'schema':'2.0'}],
            {'receive_id_type':'open_id','_admin_completion':task.task_id,'_completion_status':'任务已完成'})
        effects.defer('primary','send_interactive_message',[ids['admin'],{'schema':'2.0'}],
            {'receive_id_type':'open_id','_admin_completion':task.task_id,'_completion_status':'任务需核对'})
    conn.execute("UPDATE material_ops.documents SET payload=payload || %s WHERE name=%s",(Jsonb({'state':'queued'}),completion.PREFIX+task.task_id))
    assert completion.run_once() is None
    entries=conn.execute('SELECT state,kwargs,last_error FROM material_ops.effects WHERE job_id=%s ORDER BY ordinal',(task.task_id,)).fetchall()
    assert entries[0][0]=='pending' and '_admin_completion' not in entries[0][1]
    assert entries[1][0]=='done' and '跳过' in entries[1][2]
    assert entries[2][0]=='pending' and entries[2][1]['_completion_status']=='任务需核对'


@pytest.mark.parametrize('kind',sorted(completion.TASKS))
def test_all_management_success_receipts_are_disabled(notices,kind):
    conn,ids=notices;task,outbox=monitored(conn,kind)
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE id=%s",(outbox,))
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(task.task_id,))
    assert completion.run_once()['skipped']
    assert conn.execute("SELECT count(*) FROM material_ops.effects WHERE job_id=%s AND kwargs ? '_admin_completion'",(task.task_id,)).fetchone()[0]==0
