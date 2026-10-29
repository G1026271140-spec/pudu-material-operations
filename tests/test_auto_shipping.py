"""No real Feishu calls: approval + logistics gate, source events and receipts."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import json
import pytest
import app
from psycopg.types.json import Jsonb
from material_store import auto_shipping as auto,repository as repo,shipping_calendar as shipping,effects,outbox_worker as worker
from material_store.client import DatabaseWriteClient
from test_approval_sync import graph,add_lines
from test_shipping_batch import batch,change
from test_shipping_calendar import store,image


@pytest.fixture
def auto_store(graph,monkeypatch):
    conn,info,line_info,key,number,remote=graph
    for name in ('FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN'):monkeypatch.setenv(name,'test')
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(auto,'connection',same_connection);monkeypatch.setattr(effects,'connection',same_connection)
    conn.execute("DELETE FROM material_ops.documents WHERE name LIKE 'automatic-shipping:%'")
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    code=str(uuid4()).upper()
    parent=remote.rows[info['table_id']][key]
    parent['fields'].update({'审批状态':'已发放','库存审查状态':'已核实库存','审批实例Code':code,
        '申请人':[{'id':'ou_applicant'}],'是否发货':False,'发货单号及文字信息':'','发货图片':[],'物料发货时间':1793116800000})
    repo.insert_source_records(conn,info,[deepcopy(parent)])
    for row in remote.rows[line_info['table_id']].values():
        row['fields'].update({'明细状态':'已发放','实际发放数量':1})
    repo.insert_source_records(conn,line_info,list(deepcopy(remote.rows[line_info['table_id']]).values()))
    remote.native_status='APPROVED';remote.sent=[];remote.read_calls=0;remote.timeout_once=False
    remote.form_lines=[{'明细编号':r['fields']['明细编号'],'实际发放数量':1} for r in remote.rows[line_info['table_id']].values()]
    def native_request(method,path,**kwargs):
        if method=='GET' and path.startswith('/approval/v4/instances/'):
            remote.read_calls+=1
            form=[{'name':'申请单号','value':number},{'type':'fieldList','value':[
                [{'name':name,'value':value} for name,value in row.items()] for row in remote.form_lines]}]
            return {'data':{'status':remote.native_status,'form':json.dumps(form),'end_time':'1793161039320'}}
        assert method=='POST' and path=='/im/v1/messages'
        remote.sent.append(kwargs['payload'])
        if remote.timeout_once:remote.timeout_once=False;raise TimeoutError('unknown result')
        return {'data':{'message_id':'om_test_'+str(len(remote.sent))}}
    remote._request=native_request
    remote.upload_media=lambda *args,**kwargs:'test-shipping-image-token'
    auto.activate(remote,seed_native={code:{'status':'APPROVED','request_no':number,'line_nos':[r['明细编号'] for r in remote.form_lines],
        'lines':[{'line_no':r['明细编号'],'quantity':1} for r in remote.form_lines]}})
    return graph


def drain(source,lane='ordinary'):
    for _ in range(100):
        task=worker.claim(lane,'isolated-auto-shipping')
        if not task:return
        worker.finish(task,worker.publish(task,source))
    raise AssertionError('unexpected outbox loop')


def fields(data):
    conn,info,_,key,_,_=data
    return repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']


def save(data,**kwargs):
    conn,info,_,key,_,_=data
    return shipping.save_batch('ou_admin',batch([change(conn,key,shipping_text='DHL 123',images=[],shipped=False,**kwargs)]))


def test_activation_baselines_without_any_business_write_or_historical_message(auto_store):
    conn,info,_,key,_,source=auto_store
    assert auto.enabled(conn)
    assert auto.activate(source)=={'already_enabled':True}
    assert auto.process_one(key,source)['state']=='waiting_information'
    assert fields(auto_store)['是否发货'] is True and not source.sent
    drain(source)
    assert auto.process_one(key,source)['state']=='unchanged'
    assert not source.sent


@pytest.mark.parametrize('use_image',[False,True])
def test_text_or_image_alone_marks_shipped_and_sends_after_outbox(auto_store,use_image):
    conn,info,_,key,_,source=auto_store
    if use_image:
        photo=image('ou_admin')
        body=batch([change(conn,key,shipping_text='',images=[{'local_media_id':photo['local_media_id']}],shipped=False)])
    else:body=batch([change(conn,key,shipping_text='  DHL 123  ',images=[],shipped=False)])
    result=shipping.save_batch('ou_admin',body)
    assert result['entries'][0]['automatic'] and result['entries'][0]['effect_id'] is None
    assert fields(auto_store)['是否发货'] is False
    assert auto.process_one(key,source)['state']=='syncing'
    drain(source)
    outcome=auto.process_one(key,source)
    assert outcome['state']=='queued' and fields(auto_store)['是否发货'] is True
    assert effects.run_once({'primary':source}) is None
    assert not source.sent
    drain(source)
    assert effects.run_once({'primary':source})['state']=='done'
    assert len(source.sent)==1 and source.sent[0]['receive_id']=='ou_applicant'
    assert '您的物料申请已发货' in source.sent[0]['content'] and 'shipping_view=readonly' in source.sent[0]['content']
    assert auto.process_one(key,source)['state']=='unchanged'
    assert effects.run_once({'primary':source}) is None
    assert auto.document(conn,key)['announced'] is True


@pytest.mark.parametrize('native_state',['PENDING','REJECTED','CANCELED'])
def test_native_approval_must_be_passed_even_if_source_header_says_issued(auto_store,native_state):
    conn,info,_,key,_,source=auto_store
    source.native_status=native_state
    save(auto_store);drain(source)
    assert auto.process_one(key,source)['state']=='waiting_approval'
    assert not fields(auto_store)['是否发货'] and not source.sent
    assert effects.run_once({'primary':source}) is None


def test_approved_without_text_or_valid_image_never_notifies(auto_store):
    conn,info,_,key,_,source=auto_store
    body=batch([change(conn,key,shipping_text='   ',images=[],shipped=True)])
    shipping.save_batch('ou_admin',body);drain(source)
    assert auto.process_one(key,source)['state']=='waiting_information'
    assert fields(auto_store)['是否发货'] is True and not source.sent
    drain(source)
    assert effects.run_once({'primary':source}) is None


def test_native_approval_changes_after_logistics_are_entered(auto_store):
    conn,info,_,key,_,source=auto_store
    source.native_status='PENDING';save(auto_store);drain(source)
    assert auto.process_one(key,source)['state']=='waiting_approval'
    source.native_status='APPROVED'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    assert auto.process_one(key,source)['state']=='queued'
    drain(source);assert effects.run_once({'primary':source})['state']=='done'
    assert len(source.sent)==1


def test_approval_marks_shipped_without_requiring_later_detail_writeback(auto_store):
    conn,info,_,key,_,source=auto_store
    add_lines(auto_store,7,lane='ordinary')
    save(auto_store);drain(source)
    assert auto.process_one(key,source)['state']=='queued'
    assert fields(auto_store)['是否发货'] is True
    assert not source.sent


def test_shipped_flag_does_not_rewrite_issue_quantities(auto_store):
    conn,info,line_info,key,_,source=auto_store
    row=next(iter(source.rows[line_info['table_id']].values()))
    row['fields']['实际发放数量']=2;repo.insert_source_records(conn,line_info,[row])
    save(auto_store);drain(source)
    assert auto.process_one(key,source)['state']=='queued'
    assert fields(auto_store)['是否发货'] is True
    assert app.feishu_int(repo.feishu_record(line_info,repo.raw_record(conn,line_info,row['record_id']))['fields'],'实际发放数量')==2
    assert not source.sent


def test_unknown_send_result_retries_same_uuid_without_marking_sent_early(auto_store):
    conn,info,_,key,_,source=auto_store
    save(auto_store);drain(source);auto.process_one(key,source);drain(source)
    source.timeout_once=True
    assert effects.run_once({'primary':source})['state']=='retry'
    assert not auto.document(conn,key)['announced']
    conn.execute("UPDATE material_ops.effects SET available_at=now() WHERE kwargs->>'_shipping_request'=%s",(key,))
    assert effects.run_once({'primary':source})['state']=='done'
    assert source.sent[0]['uuid']==source.sent[1]['uuid'] and auto.document(conn,key)['announced']


def test_stale_content_or_changed_applicant_does_not_send_old_card(auto_store):
    conn,info,_,key,_,source=auto_store
    save(auto_store);drain(source);auto.process_one(key,source);drain(source)
    row=repo.raw_record(conn,info,key);named=repo.feishu_record(info,row)
    named['fields']['申请人']=[{'id':'ou_other'}];repo.insert_source_records(conn,info,[named])
    assert effects.run_once({'primary':source})['state']=='skipped'
    assert not source.sent


def test_source_side_logistics_edit_is_observed_without_a_frontend_save(auto_store):
    conn,info,_,key,_,source=auto_store
    row=repo.feishu_record(info,repo.raw_record(conn,info,key))
    row['fields']['发货单号及文字信息']='Feishu direct tracking'
    repo.insert_source_records(conn,info,[row]);source.rows[info['table_id']][key]=deepcopy(row)
    assert auto.process_one(key,source)['state']=='queued'
    drain(source);assert effects.run_once({'primary':source})['state']=='done'


def test_later_date_change_is_a_card_and_still_requires_logistics(auto_store):
    conn,info,_,key,_,source=auto_store
    save(auto_store);drain(source);auto.process_one(key,source);drain(source);effects.run_once({'primary':source})
    shipping.save_batch('ou_admin',batch([change(conn,key,shipping_text='DHL 123',images=[],shipped=True,ship_date='2026-10-30')]))
    drain(source);auto.process_one(key,source);drain(source);effects.run_once({'primary':source})
    assert len(source.sent)==2 and '物料发货时间变更通知' in source.sent[1]['content']


def test_poll_has_fifteen_second_compensation_and_refreshes_all_approval_outputs(auto_store,monkeypatch):
    from material_store import inbound
    conn,info,_,key,_,source=auto_store;calls=[]
    monkeypatch.setattr(inbound,'refresh',lambda names,clients:(calls.append(names) or {'changed':0}))
    monkeypatch.setattr(auto,'process_changed',lambda **kwargs:{'checked':0,'queued':0})
    monkeypatch.setattr(auto,'_last_poll',0)
    assert auto.poll(source)['queued']==0
    assert auto.poll(source)['state']=='not_due'
    assert calls==[[app.REQUEST_TABLE_NAME,app.REQUEST_LINE_TABLE_NAME,app.MATERIAL_TABLE_NAME,app.LEDGER_TABLE_NAME]]


def test_rejected_native_is_hidden_and_cannot_be_edited(auto_store):
    conn,info,_,key,_,source=auto_store
    state=auto.document(conn,key);state['native']['status']='REJECTED';auto.put(conn,key,state)
    assert key not in {r['request_id'] for r in shipping.catalog(conn)['requests']}
    with pytest.raises(ValueError,match='飞书审批'):
        save(auto_store)
    assert not source.sent


def test_old_rejection_cache_does_not_hide_or_block_a_new_instance(auto_store):
    conn,info,_,key,_,source=auto_store
    state=auto.document(conn,key);state['native'].update(status='REJECTED',code='old-instance');auto.put(conn,key,state)
    request=next(r for r in shipping.catalog(conn)['requests'] if r['request_id']==key)
    assert request['approval_status'] is None
    assert save(auto_store)['changed']==1


def test_approval_passes_before_line_writeback_and_without_logistics(auto_store):
    conn,info,line_info,key,number,source=auto_store
    row=repo.feishu_record(info,repo.raw_record(conn,info,key));row['fields']['审批状态']='待审批'
    repo.insert_source_records(conn,info,[row])
    line=next(iter(source.rows[line_info['table_id']].values()))
    line['fields'].update(明细状态='待审批',实际发放数量=0)
    repo.insert_source_records(conn,line_info,[line])
    outcome=auto.process_one(key,source)
    assert outcome['state']=='waiting_information' and outcome['flag_updated']
    assert fields(auto_store)['是否发货'] is True
    assert fields(auto_store)['审批状态']=='待审批'
    drain(source)
    assert effects.run_once({'primary':source}) is None and not source.sent
    assert app.feishu_int(repo.feishu_record(line_info,repo.raw_record(conn,line_info,line['record_id']))['fields'],'实际发放数量')==0


def test_add_logistics_after_approval_only_flag_sends_exactly_one_card(auto_store):
    conn,info,_,key,_,source=auto_store
    assert auto.process_one(key,source)['state']=='waiting_information'
    drain(source);assert not source.sent
    save(auto_store);drain(source)
    assert auto.process_one(key,source)['state']=='queued'
    drain(source);assert effects.run_once({'primary':source})['state']=='done'
    assert len(source.sent)==1
    assert auto.process_one(key,source)['state']=='unchanged'


def test_another_native_request_number_does_not_mark_or_notify(auto_store):
    conn,info,_,key,_,source=auto_store
    state=auto.document(conn,key);state['native']['request_no']='OTHER';auto.put(conn,key,state)
    assert auto.process_one(key,source)['state']=='unchanged'
    assert fields(auto_store)['是否发货'] is False and not source.sent


def test_replaced_approval_blocks_old_card_and_new_approval_can_notify(auto_store):
    conn,info,_,key,_,source=auto_store
    save(auto_store);drain(source);assert auto.process_one(key,source)['state']=='queued';drain(source)
    row=repo.feishu_record(info,repo.raw_record(conn,info,key));row['fields']['审批实例Code']=str(uuid4()).upper()
    repo.insert_source_records(conn,info,[row]);source.rows[info['table_id']][key]=deepcopy(row)
    assert effects.run_once({'primary':source})['state']=='skipped' and not source.sent
    source.native_status='PENDING'
    assert auto.process_one(key,source)['state']=='waiting_approval'
    source.native_status='APPROVED'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    assert auto.process_one(key,source)['state']=='queued'
    drain(source);assert effects.run_once({'primary':source})['state']=='done'
    assert len(source.sent)==1
