import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
import app
import backend_runtime as runtime
from request_web import live_data, feishu_auth

web = importlib.import_module('request_web.api')


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv('PUDU_REALTIME_READS','1')
    calls = []
    records = {'物料品类':[{'record_id':'category','fields':{'物料品类':'First'}}],
               '用户权限表':[],'产品型号':[],'物料主数据':[]}
    def tables():
        return [{'name':name,'table_id':name} for name in records]
    def rows(table):
        calls.append(table)
        return [dict(row,fields=dict(row['fields'])) for row in records[table]]
    client = SimpleNamespace(list_tables=tables,list_records=rows)
    monkeypatch.setattr(app,'feishu_client',lambda:client)
    return records,calls,client


def test_live_rows_ignore_disk_and_runtime_snapshots_and_refresh_next_request(live,monkeypatch):
    records,calls,_ = live
    monkeypatch.setattr(app,'load_static_json_file',lambda *_:pytest.fail('Read a disk snapshot'))
    with runtime.request_scope():
        assert app.feishu_rows('物料品类')[0]['fields']['物料品类']=='First'
        assert app.page_data_cache_rows('物料品类')[0]['fields']['物料品类']=='First'
        assert web._json('page_data_cache.json')['tables']['物料品类'][0]['record_id']=='category'
    records['物料品类'][0]['fields']['物料品类']='Second'
    with runtime.request_scope():
        assert app.feishu_rows('物料品类')[0]['fields']['物料品类']=='Second'
    assert calls==['物料品类','物料品类']


def test_live_reader_does_not_live_beyond_explicit_scope(live):
    with runtime.request_scope():
        a=live_data.reader()
        assert live_data.reader() is a
    with runtime.request_scope():
        assert live_data.reader() is not a
    assert live_data.reader() is not live_data.reader()


def test_source_failure_does_not_fall_back_to_old_business_data(live):
    _,_,client=live
    client.list_records=lambda *_: (_ for _ in ()).throw(RuntimeError('offline'))
    with runtime.request_scope(),pytest.raises(RuntimeError,match='offline'):
        app.feishu_rows('物料品类')


def test_readonly_blocks_post_before_enqueue_and_skips_background_writers(monkeypatch):
    monkeypatch.setenv('PUDU_WEB_READ_ONLY','1')
    import submission_receipts
    monkeypatch.setattr(submission_receipts,'start',lambda:pytest.fail('Background notifier started'))
    monkeypatch.setattr(web,'start_pending_reconciliation',lambda:pytest.fail('Snapshot reconciler started'))
    monkeypatch.setattr(web,'_enqueue_fast',lambda *_:pytest.fail('Business task enqueued'))
    with TestClient(web.api) as client:
        assert client.post('/api/submit',json={}).status_code==409
        assert client.post('/api/corporate-exchange-sync',json={}).status_code==409


def test_signed_admin_still_requires_live_enabled_admin_permission(live,monkeypatch):
    records,_,_=live
    monkeypatch.setattr(feishu_auth,'own_tenant_key',lambda:'tenant')
    monkeypatch.setattr(feishu_auth,'session_identity',lambda *_:{'open_id':'ou_test','name':'Tester'})
    request=SimpleNamespace(cookies={'pudu_feishu':'signed'})
    records['用户权限表']=[{'fields':{'用户账号':[{'id':'ou_test'}],'是否启用':'是','角色':['管理员']}}]
    with runtime.request_scope(): assert web._signed_admin_open_id(request)=='ou_test'
    records['用户权限表'][0]['fields']['是否启用']='否'
    with runtime.request_scope(),pytest.raises(Exception) as exc: web.require_admin(request)
    assert exc.value.status_code==403


def test_live_stock_never_uses_shared_stock_cache(monkeypatch):
    monkeypatch.setenv('PUDU_REALTIME_READS','1')
    monkeypatch.setattr(web,'_json',lambda *_:{'tables':{}})
    monkeypatch.setitem(web._CORPORATE_APPAREL_STOCK_CACHE,'items',['stale'])
    monkeypatch.setitem(web._CORPORATE_APPAREL_STOCK_CACHE,'loaded_at',__import__('time').monotonic())
    source=SimpleNamespace(list_records=lambda _:['fresh'])
    monkeypatch.setattr(app,'corporate_apparel_source_client',lambda:source)
    monkeypatch.setattr(app,'corporate_apparel_catalog',lambda _,source_rows:{'items':source_rows})
    monkeypatch.setattr(web,'_corporate_apparel_web_items',lambda catalog:catalog['items'])
    from fastapi import Response
    assert web.corporate_apparel_stock(Response())=={'items':['fresh']}


def test_image_proxy_rejects_unattached_token(live):
    _,_,client=live
    client.get_record=lambda *_:{'fields':{'申领页图片':[{'file_token':'allowed'}]}}
    client.download_media=lambda *_:pytest.fail('Downloaded unreferenced file')
    with runtime.request_scope(),pytest.raises(KeyError):
        live_data.image_bytes('物料品类','category','other')


def test_public_origin_override_uses_company_callback(monkeypatch):
    monkeypatch.setenv('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work')
    feishu_auth.public_origin.cache_clear()
    try: assert feishu_auth.callback_url()=='https://materials.pudu.work/auth/feishu/callback'
    finally: feishu_auth.public_origin.cache_clear()


def test_live_health_is_a_valid_json_response_with_boolean_flags(monkeypatch):
    monkeypatch.setenv('PUDU_REALTIME_READS','1')
    monkeypatch.setenv('PUDU_WEB_READ_ONLY','1')
    body=TestClient(web.api).get('/api/health').json()
    assert body['status']=='ok' and body['business_cache_enabled'] is False
    assert body['mode']=='live_read_only'
