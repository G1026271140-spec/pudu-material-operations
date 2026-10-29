"""Explicit calendar shipping before approval and calendar-only repeated notices."""
from copy import deepcopy
import pytest
from test_auto_shipping import auto_store,fields,drain,save
from test_approval_sync import graph
from test_shipping_calendar import store,image
from test_shipping_batch import batch,change
from test_approval_shipping import final_shipping
from material_store import auto_shipping as auto,shipping_calendar as shipping,repository as repo,effects


def pending(data):
    conn,info,_,key,_,source=data
    source.native_status='PENDING'
    state=auto.document(conn,key);state['native'].update(status='PENDING',checked_at=0);auto.put(conn,key,state)
    return conn,info,key,source


def notify(data):
    conn,info,_,key,_,source=data
    drain(source);result=auto.process_one(key,source);drain(source)
    return result,effects.run_once({'primary':source})


@pytest.mark.parametrize('use_image',[False,True])
def test_calendar_marks_shipped_immediately_and_notifies_while_approval_pending(auto_store,use_image):
    conn,info,key,source=pending(auto_store)
    photo=image('ou_admin') if use_image else None
    body=batch([change(conn,key,shipping_text='' if use_image else 'SF12345',images=[{'local_media_id':photo['local_media_id']}] if photo else [],shipped=False)])
    result=shipping.save_batch('ou_admin',body)
    assert fields(auto_store)['是否发货'] is True
    assert shipping.save_batch('ou_admin',body)==result
    assert not source.sent and effects.run_once({'primary':source}) is None
    outcome,sent=notify(auto_store)
    assert outcome['state']=='queued' and sent['state']=='done' and len(source.sent)==1
    assert source.sent[0]['receive_id']=='ou_applicant' and '您的物料申请已发货' in source.sent[0]['content']
    source.native_status='APPROVED'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    auto.process_one(key,source);drain(source)
    assert effects.run_once({'primary':source}) is None and len(source.sent)==1
    assert fields(auto_store)['发货单号及文字信息']==('' if use_image else 'SF12345')


def test_calendar_logistics_updates_renotify_but_source_changes_do_not(auto_store):
    conn,info,key,source=pending(auto_store)
    save(auto_store);notify(auto_store)
    assert len(source.sent)==1
    for tracking in ('NEW TRACKING','DHL 123'):
        body=batch([change(conn,key,shipping_text=tracking,images=[],shipped=True)])
        shipping.save_batch('ou_admin',body)
        assert shipping.save_batch('ou_admin',body)['changed']==1
        notify(auto_store)
    assert len(source.sent)==3
    # Source event / daily reconciliation is not a new calendar submission.
    row=repo.feishu_record(info,repo.raw_record(conn,info,key));row['fields'][shipping.TEXT]='SOURCE SIDE CHANGE'
    repo.insert_source_records(conn,info,[row]);source.rows[info['table_id']][key]=deepcopy(row)
    auto.process_one(key,source);drain(source)
    assert effects.run_once({'primary':source}) is None and len(source.sent)==3


def test_placeholders_never_authorize_early_shipping(auto_store):
    from material_store import shipping_defaults as defaults
    conn,info,key,source=pending(auto_store)
    placeholder=defaults.ensure_image(conn)
    row=repo.feishu_record(info,repo.raw_record(conn,info,key));row['fields'][shipping.IMAGES]=[placeholder]
    repo.insert_source_records(conn,info,[row])
    shipping.save_batch('ou_admin',batch([change(conn,key,shipping_text='  待补充  ',images=[{'local_media_id':placeholder['local_media_id']}],shipped=False)]))
    assert not fields(auto_store)[shipping.SHIPPED]
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE table_id=%s AND record_key=%s",(info['table_id'],key))
    assert auto.process_one(key,source)['state']=='waiting_approval'
    assert not source.sent


def test_later_approval_does_not_fill_or_replace_any_early_calendar_logistics(final_shipping):
    data,download=final_shipping
    conn,info,key,source=pending(data)
    shipping.save_batch('ou_admin',batch([change(conn,key,shipping_text='EARLY SHIPMENT',images=[],shipped=False)]))
    notify(data)
    assert len(source.sent)==1
    source.native_status='APPROVED'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    auto.process_one(key,source);drain(source)
    assert fields(data)[shipping.TEXT]=='EARLY SHIPMENT' and fields(data)[shipping.IMAGES]==[]
    assert not download.called and len(source.sent)==1
    assert effects.run_once({'primary':source}) is None


def test_source_logistics_before_approval_does_not_authorize_early_dispatch(auto_store):
    conn,info,key,source=pending(auto_store)
    row=repo.feishu_record(info,repo.raw_record(conn,info,key));row['fields'][shipping.TEXT]='SOURCE EDIT'
    repo.insert_source_records(conn,info,[row]);source.rows[info['table_id']][key]=deepcopy(row)
    assert auto.process_one(key,source)['state']=='waiting_approval'
    assert not fields(auto_store)[shipping.SHIPPED] and not source.sent


def test_new_calendar_image_after_first_dispatch_sends_one_new_card(auto_store):
    conn,info,key,source=pending(auto_store)
    save(auto_store);notify(auto_store)
    photo=image('ou_admin')
    body=batch([change(conn,key,shipping_text='DHL 123',images=[{'local_media_id':photo['local_media_id']}],shipped=True)])
    shipping.save_batch('ou_admin',body);notify(auto_store)
    assert len(source.sent)==2
    assert shipping.save_batch('ou_admin',body)['changed']==1
    assert auto.process_one(key,source)['state']=='unchanged'
    assert effects.run_once({'primary':source}) is None
