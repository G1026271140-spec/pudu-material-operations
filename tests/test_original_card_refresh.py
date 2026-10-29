"""Real PostgreSQL jobs/outbox/effects; all Feishu traffic is simulated."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
from unittest.mock import Mock
import pytest
import app
import backend_runtime as runtime
from material_store import jobs,repository as repo,effects,outbox_worker as worker
from test_shipping_calendar import store,insert_request


@pytest.fixture
def confirmation(store,monkeypatch):
    conn=store
    for name in ('FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN'):monkeypatch.setenv(name,'test')
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(effects,'connection',same_connection);monkeypatch.setattr(worker,'connection',same_connection)
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state NOT IN ('done','cancelled')")
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    key=insert_request(conn,审批状态='待审批',库存审查状态='待核实库存',库存确认消息ID='[]')
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    original=deepcopy(repo.feishu_record(info,repo.raw_record(conn,info,key)))
    def context(**kwargs):
        f=repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']
        return {'request':{'record_id':key,'request_no':app.feishu_text(f,'申请单号'),
            'status':app.feishu_text(f,'审批状态'),'inventory_review_status':app.feishu_text(f,'库存审查状态'),
            'inventory_message_ids':app._json_list(app.feishu_text(f,'库存确认消息ID'))},
            'request_row':{'fields':f},'lines':[],'result':app.INVENTORY_RESULT_SUFFICIENT}
    monkeypatch.setattr(app,'request_inventory_review_context',context)
    monkeypatch.setattr(app,'enabled_admin_open_ids',lambda:['ou_admin','ou_new_admin'])
    monkeypatch.setattr(app,'material_request_notification_card',lambda *a,**kw:{'schema':'2.0','header':{'title':{'tag':'plain_text','content':'库存已核实'}},'body':{'elements':[]}})
    monkeypatch.setattr(app,'feishu_datetime_value',lambda *a:1793232000000)
    remote=Mock();remote.row=original;remote.cards=[]
    remote.get_record=lambda table,record:deepcopy(remote.row)
    def update_record(table,record,fields):remote.row['fields'].update(deepcopy(fields));return deepcopy(remote.row)
    remote.update_record=update_record
    remote.update_interactive_message=lambda identity,card:remote.cards.append((identity,card))
    remote._request=Mock(side_effect=AssertionError('No new message may be sent'))
    task,_=jobs.enqueue(app.QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,'original-card-'+uuid4().hex,
        {'draft':{'request_id':key,'expected_version':0,'operator_open_id':'ou_admin','message_id':'om_clicked_original'}},conn=conn)
    row=conn.execute('SELECT id,task_type,idempotency_key,payload,state,result FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()
    result=jobs._run(conn,row)
    return conn,info,key,task,result,remote


def drain(remote):
    for _ in range(30):
        item=worker.claim('admin','isolated-original-card')
        if not item:return
        worker.finish(item,worker.publish(item,remote))
    raise AssertionError('Outbox did not drain')


def test_confirm_updates_clicked_card_after_data_without_sending_replacements(confirmation):
    conn,info,key,task,result,remote=confirmation
    methods=conn.execute('SELECT method,args,kwargs FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchall()
    assert len(methods)==1 and methods[0][0]=='update_interactive_message'
    assert methods[0][1][0]=='om_clicked_original' and methods[0][2]['_outbox_ids']
    assert effects.run_once({'primary':remote}) is None
    drain(remote)
    assert remote.row['fields']['库存审查状态']=='已核实库存'
    assert remote.row['fields']['库存确认消息ID']=='["om_clicked_original"]'
    assert effects.run_once({'primary':remote})['state']=='done'
    assert [identity for identity,_ in remote.cards]==['om_clicked_original']
    remote._request.assert_not_called()
    assert effects.run_once({'primary':remote}) is None
    payload=conn.execute('SELECT payload,idempotency_key FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()
    again,created=jobs.enqueue(app.QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,payload[1],payload[0],conn=conn)
    assert not created and again.task_id==task.task_id
    assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchone()[0]==1


def test_expired_original_card_is_retained_for_retry_without_new_card(confirmation):
    conn,info,key,task,result,remote=confirmation;drain(remote)
    remote.update_interactive_message=Mock(side_effect=RuntimeError('Feishu code 230031 Message has expired'))
    assert effects.run_once({'primary':remote})['state']=='retry'
    remote.update_interactive_message.assert_called_once()
    assert remote.update_interactive_message.call_args.args[0]=='om_clicked_original'
    remote._request.assert_not_called()
    assert conn.execute('SELECT method FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchall()==[('update_interactive_message',)]


def test_newer_confirmation_waits_for_older_original_card_retry(confirmation):
    conn,info,key,task,result,remote=confirmation;drain(remote)
    old_id=conn.execute('SELECT id FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchone()[0]
    conn.execute("UPDATE material_ops.effects SET state='retry',available_at=now()+interval '1 minute' WHERE id=%s",(old_id,))
    newer,_=jobs.enqueue(app.QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,'newer-card-'+uuid4().hex,{'draft':{'request_id':key}},conn=conn)
    runtime.request_state.update(_job_id=newer.task_id,_effect_ordinal=0)
    effects.defer('primary','update_interactive_message',['om_clicked_original',{'newer':True}],{'_outbox_ids':[],'_inventory_request':key})
    assert effects.run_once({'primary':remote}) is None and not remote.cards
    conn.execute('UPDATE material_ops.effects SET available_at=now() WHERE id=%s',(old_id,))
    assert effects.run_once({'primary':remote})['state']=='done'
    assert effects.run_once({'primary':remote})['state']=='done'
    assert remote.cards[-1]==('om_clicked_original',{'newer':True})
    remote._request.assert_not_called()


def test_confirmation_refreshes_all_registered_cards_without_notifying_new_admin(monkeypatch):
    source=Mock();context={'request':{'record_id':'request-1','inventory_message_ids':['om_admin_a','om_admin_b']}}
    monkeypatch.setattr(app,'feishu_client',lambda:source)
    monkeypatch.setattr(app,'enabled_admin_open_ids',lambda:['ou_a','ou_b','ou_new'])
    monkeypatch.setattr(app,'request_inventory_review_context',lambda **kwargs:context)
    monkeypatch.setattr(app,'material_request_notification_card',lambda *a,**kw:{'schema':'2.0'})
    monkeypatch.setattr(app,'feishu_update_record_fields',Mock())
    monkeypatch.setattr(app,'feishu_datetime_value',lambda *a:123)
    app.notify_enabled_admins_of_material_request('REQ-1',{},[],update_only=True,original_message_id='om_admin_a',operator_open_id='ou_a',request_id='request-1')
    assert [call.args[0] for call in source.update_interactive_message.call_args_list]==['om_admin_a','om_admin_b']
    source.send_interactive_message.assert_not_called()


def test_context_failure_does_not_fall_back_to_a_new_confirmation_card(monkeypatch):
    source=Mock()
    monkeypatch.setattr(app,'feishu_client',lambda:source)
    monkeypatch.setattr(app,'enabled_admin_open_ids',lambda:['ou_admin'])
    def unavailable(**kwargs):raise RuntimeError('snapshot unavailable')
    monkeypatch.setattr(app,'request_inventory_review_context',unavailable)
    with pytest.raises(RuntimeError,match='snapshot unavailable'):
        app.notify_enabled_admins_of_material_request('REQ-1',{},[],update_only=True,original_message_id='om_original',request_id='request-1')
    source.send_interactive_message.assert_not_called()


def test_repeat_confirmation_preserves_quantities_after_approval_started(monkeypatch):
    context={'request':{'record_id':'request-1','request_no':'REQ-1','status':'待审批','inventory_review_status':app.INVENTORY_REVIEW_CONFIRMED},
        'request_row':{'fields':{'审批实例Code':'APPROVAL-1'}},
        'lines':[{'record_id':'line-1','quantity':10,'approved_qty':0,'actual_issue_qty':0}],
        'result':app.INVENTORY_RESULT_SUFFICIENT}
    monkeypatch.setattr(app,'enabled_admin_open_ids',lambda:['ou_admin'])
    monkeypatch.setattr(app,'request_inventory_review_context',lambda **kwargs:context)
    update=Mock();monkeypatch.setattr(app,'feishu_batch_update_record_fields',update)
    notify=Mock(return_value=1);monkeypatch.setattr(app,'notify_enabled_admins_of_material_request',notify)
    result=app.execute_request_inventory_confirm({'request_id':'request-1','expected_version':0,'operator_open_id':'ou_admin','message_id':'om_original'})
    assert result['already_confirmed'] and result['repaired_line_count']==0
    update.assert_not_called()
    assert notify.call_args.kwargs['update_only'] and notify.call_args.kwargs['original_message_id']=='om_original'
