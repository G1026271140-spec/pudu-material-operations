from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import json
from unittest.mock import Mock
from PIL import Image
import pytest
from psycopg import sql
from material_store import approval_shipping as imported,auto_shipping as auto,repository as repo,shipping_defaults as defaults,effects
from test_auto_shipping import auto_store,drain,fields,save
from test_approval_sync import graph
from test_shipping_calendar import store,image


@pytest.fixture
def final_shipping(auto_store,monkeypatch):
    conn,info,lines,key,number,source=auto_store
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(imported,'connection',same)
    old=source._request
    source.approval_shipping=[{'name':defaults.TEXT,'type':'input','value':'DHL FINAL 123'},
        {'name':defaults.IMAGES,'type':'attachmentV2','value':['https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=test'],'ext':'actual.png'}]
    def request(method,path,**kwargs):
        result=old(method,path,**kwargs)
        if path.startswith('/approval/v4/instances/'):
            form=json.loads(result['data']['form']);form+=source.approval_shipping
            result['data']['form']=json.dumps(form)
        return result
    source._request=request
    data=BytesIO();Image.new('RGB',(7,7),'green').save(data,format='PNG')
    download=Mock(return_value=data.getvalue());monkeypatch.setattr(imported,'download',download)
    return auto_store,download


def test_approved_fields_are_local_first_then_outbox_and_one_receipt(final_shipping):
    data,download=final_shipping;conn,info,line_info,key,number,source=data
    before=deepcopy(source.rows[line_info['table_id']])
    result=auto.process_one(key,source)
    assert result['state']=='queued' and set(result['approval_import_fields'])=={defaults.TEXT,defaults.IMAGES}
    assert fields(data)[defaults.TEXT]=='DHL FINAL 123' and fields(data)['是否发货'] is True
    assert fields(data)[defaults.IMAGES][0]['local_media_id']
    assert source.rows[info['table_id']][key]['fields'][defaults.TEXT]=='' and not source.sent
    assert effects.run_once({'primary':source}) is None
    drain(source)
    assert source.rows[info['table_id']][key]['fields'][defaults.TEXT]=='DHL FINAL 123'
    assert source.rows[info['table_id']][key]['fields'][defaults.IMAGES][0]['file_token']=='test-shipping-image-token'
    assert effects.run_once({'primary':source})['state']=='done' and len(source.sent)==1
    # A source roundtrip changes local attachment shape, not receipt identity.
    repo.insert_source_records(conn,info,[deepcopy(source.rows[info['table_id']][key])])
    assert auto.process_one(key,source)['state']=='unchanged'
    assert source.rows[line_info['table_id']]==before
    assert download.call_count==1
    save(data);drain(source);auto.process_one(key,source)
    assert fields(data)[defaults.TEXT]=='DHL 123'  # Later frontend edits are not overwritten by old approval.


def test_pending_edits_wait_for_approval_and_final_values_are_fetched(final_shipping):
    data,download=final_shipping;conn,info,_,key,_,source=data
    source.native_status='PENDING'
    assert auto.process_one(key,source)['state']=='waiting_approval'
    assert fields(data)[defaults.TEXT]=='' and not download.called
    source.native_status='APPROVED';source.approval_shipping[0]['value']='FINAL NEW'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    assert auto.process_one(key,source)['state']=='queued'
    assert fields(data)[defaults.TEXT]=='FINAL NEW' and download.call_count==1


def test_legacy_catchup_preserves_real_fields_and_does_not_fetch_old_images(final_shipping):
    data,download=final_shipping;conn,info,_,key,_,source=data
    current=repo.feishu_record(info,repo.raw_record(conn,info,key))
    current['fields'].update({defaults.TEXT:'NEWER WEB',defaults.IMAGES:[{'file_token':'real-web-image'}]})
    repo.insert_source_records(conn,info,[current])
    auto.process_one(key,source)
    assert fields(data)[defaults.TEXT]=='NEWER WEB' and fields(data)[defaults.IMAGES][0]['file_token']=='real-web-image'
    assert not download.called


def test_missing_image_can_retry_without_delaying_approved_flag(final_shipping):
    data,download=final_shipping;conn,info,_,key,_,source=data
    source.approval_shipping[0]['value']='待补充'
    download.side_effect=ValueError('image temporarily unavailable')
    first=auto.process_one(key,source)
    assert first['state']=='waiting_information' and fields(data)['是否发货'] is True
    assert auto.document(conn,key)['approval_import_error'] and not source.sent
    drain(source);download.side_effect=None
    assert auto.process_one(key,source)['state']=='queued'
    drain(source);effects.run_once({'primary':source})
    assert len(source.sent)==1 and download.call_count==2


def test_other_approval_number_does_not_import_or_download(final_shipping):
    data,download=final_shipping;conn,info,_,key,_,source=data
    original=source._request
    def wrong(method,path,**kw):
        result=original(method,path,**kw)
        form=json.loads(result['data']['form']);form[0]['value']='OTHER'
        result['data']['form']=json.dumps(form);return result
    source._request=wrong
    assert auto.process_one(key,source)['state']=='waiting_approval'
    assert fields(data)[defaults.TEXT]=='' and not download.called and not source.sent


def test_placeholder_image_and_text_are_not_imported_as_actual_logistics(final_shipping):
    data,download=final_shipping;conn,info,_,key,_,source=data
    source.approval_shipping[0]['value']='待补充';download.return_value=defaults.asset()[0]
    assert auto.process_one(key,source)['state']=='waiting_information'
    assert fields(data)[defaults.TEXT]=='' and fields(data)[defaults.IMAGES]==[] and not source.sent


@pytest.mark.parametrize('url',['http://internal-api-drive-stream.feishu.cn/image','https://feishu.cn.evil.example/image','https://127.0.0.1/image','https://user:pass@feishu.cn/image','https://feishu.cn:8443/image'])
def test_approval_url_and_redirect_validation_refuses_untrusted_targets(url):
    with pytest.raises(ValueError):imported.validate_url(url)
    with pytest.raises(ValueError):imported.SafeRedirect().redirect_request(None,None,302,'',{},url)


def test_bad_form_reports_error_without_losing_the_approval_status():
    result=imported.extract([{'name':defaults.IMAGES,'value':['x']*13}])
    assert result['version']==1 and '最多 12' in result['error']


@pytest.mark.parametrize('prefill_text,prefill_image',[(True,True),(True,False),(False,True)])
def test_early_calendar_dispatch_preserves_both_logistics_fields_after_approval(final_shipping,prefill_text,prefill_image):
    from material_store import shipping_calendar as calendar
    from test_shipping_batch import batch,change
    data,download=final_shipping;conn,info,_,key,_,source=data
    source.native_status='PENDING'
    assert auto.process_one(key,source)['state']=='waiting_approval'
    photo=image('ou_admin') if prefill_image else None
    calendar.save_batch('ou_admin',batch([change(conn,key,shipping_text='CALENDAR FIRST' if prefill_text else '待补充',
        images=[{'local_media_id':photo['local_media_id']}] if photo else [],shipped=False)]))
    drain(source)
    before=deepcopy(fields(data))
    source.native_status='APPROVED'
    state=auto.document(conn,key);state['native']['checked_at']=0;auto.put(conn,key,state)
    result=auto.process_one(key,source)
    assert result['state']=='queued' and fields(data)['是否发货'] is True
    assert fields(data)[defaults.TEXT]==before[defaults.TEXT]
    assert fields(data)[defaults.IMAGES]==before[defaults.IMAGES]
    assert result['approval_import_fields']==[]
    assert not download.called
    drain(source);assert effects.run_once({'primary':source})['state']=='done'
    assert len(source.sent)==1
    assert auto.process_one(key,source)['state']=='unchanged'


def test_calendar_edit_during_approval_download_wins_after_version_retry(final_shipping):
    from material_store import shipping_calendar as calendar
    from test_shipping_batch import batch,change
    data,download=final_shipping;conn,info,_,key,_,source=data
    payload=download.return_value
    photo=image('ou_admin')
    def simultaneous_edit(url):
        calendar.save_batch('ou_admin',batch([change(conn,key,shipping_text='CONCURRENT CALENDAR',
            images=[{'local_media_id':photo['local_media_id']}],shipped=False)]))
        return payload
    download.side_effect=simultaneous_edit
    assert auto.process_one(key,source)['state']=='changed_during_check'
    assert fields(data)[defaults.TEXT]=='CONCURRENT CALENDAR'
    before=deepcopy(fields(data)[defaults.IMAGES]);drain(source)
    download.side_effect=None
    assert auto.process_one(key,source)['state']=='queued'
    assert fields(data)[defaults.TEXT]=='CONCURRENT CALENDAR' and fields(data)[defaults.IMAGES]==before
    assert download.call_count==1
