from contextlib import contextmanager
import importlib,json
from urllib.parse import urlparse,parse_qs
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_shipping_calendar import store,insert_request
from test_shipping_access import SnapshotTestConnection
from material_store.shipping_card import card

def test_shipping_card_has_requested_title_and_only_readonly_open_url_action():
    receipt=card('REQ-ISOLATED','local/unsafe?value',True,'2026-10-28','2026-11-02','DHL <bad> *123*',2,'https://materials.pudu.work')
    assert receipt['schema']=='2.0' and receipt['header']['title']['content']=='您的物料申请已发货'
    assert receipt['header']['template']=='green'
    actions=receipt['body']['elements'][-1]['behaviors']
    assert len(actions)==1 and actions[0]['type']=='open_url'
    query=parse_qs(urlparse(actions[0]['default_url']).query)
    assert query=={'shipping_request':['local/unsafe?value'],'shipping_view':['readonly']}
    assert '<bad>' not in json.dumps(receipt,ensure_ascii=False)
    assert '2026-11-02' in json.dumps(receipt)
    assert card('REQ','id',False,'','','',0,'https://materials.pudu.work')['header']['title']['content']=='您的物料申请发货信息已更新'

def test_applicant_link_forces_owner_only_and_readonly_even_for_editor(store,monkeypatch):
    conn=store;owned=insert_request(conn,申请人=[{'id':'ou_owner'}]);other=insert_request(conn,申请人=[{'id':'ou_other'}])
    module=importlib.import_module('request_web.shipping_calendar_api')
    @contextmanager
    def same():yield SnapshotTestConnection(conn)
    monkeypatch.setattr(module,'connection',same)
    api=FastAPI();module.register(api,lambda:'ou_owner',lambda:'ou_owner',lambda request:True)
    with TestClient(api) as client:
        normal=client.get('/api/shipping-calendar').json();assert normal['can_edit'] is True
        own=client.get('/api/shipping-calendar?view=applicant&owner=ou_other').json()
        assert own['can_edit'] is False and {r['request_id'] for r in own['requests']}=={owned}
        assert other not in {r['request_id'] for r in own['requests']}
