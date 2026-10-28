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

def test_admin_completion_waits_real_source_and_applicant_effects_and_deduplicates(notices):
    conn,ids=notices;task,outbox=monitored(conn)
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE id=%s",(outbox,))
    assert completion.run_once() is None
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id=%s",(task.task_id,))
    result=completion.run_once();assert result['status']=='任务已完成' and result['recipients']==1
    assert completion.run_once() is None
    rows=conn.execute("SELECT args,kwargs FROM material_ops.effects WHERE kwargs ? '_admin_completion'").fetchall()
    assert len(rows)==1 and rows[0][0][0]==ids['admin']
    assert 'RESTOCK-ISOLATED' in __import__('json').dumps(rows[0][0][1],ensure_ascii=False) and '测试操作人' in __import__('json').dumps(rows[0][0][1],ensure_ascii=False)
    assert rows[0][0][1]['schema']=='2.0'
    assert '任务编号' not in __import__('json').dumps(rows[0][0][1],ensure_ascii=False)
    fake=Mock();fake._request.return_value={'data':{'message_id':'om_isolated_admin'}}
    assert effects.run_once({'primary':fake})['state']=='done'
    assert effects.run_once({'primary':fake}) is None

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
