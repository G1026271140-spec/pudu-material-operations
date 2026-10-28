from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock
import importlib
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from test_shipping_calendar import store, insert_request, image
from test_shipping_batch import change, batch
from material_store import shipping_calendar as shipping, repository as repo


class SnapshotTestConnection:
    """The fixture already owns the rollback transaction and seeded rows."""
    def __init__(self, conn): self.conn = conn
    def __getattr__(self, name): return getattr(self.conn, name)
    def execute(self, query, *args, **kwargs):
        if isinstance(query, str) and query.startswith('SET TRANSACTION ISOLATION LEVEL'):
            return None
        return self.conn.execute(query, *args, **kwargs)


def test_owner_filter_uses_person_account_not_matching_name_or_submitter(store):
    conn = store
    owner = insert_request(conn, 申请人=[{'id': 'ou_owner', 'name': '同名'}])
    other = insert_request(conn, 申请人=[{'id': 'ou_other', 'name': '同名'}], 提交人=[{'id': 'ou_owner'}])
    missing = insert_request(conn)
    found = {r['request_id'] for r in shipping.catalog(conn, owner='ou_owner')['requests']}
    assert owner in found and other not in found and missing not in found
    assert {owner, other, missing} <= {r['request_id'] for r in shipping.catalog(conn)['requests']}


def test_applicant_api_and_images_deny_other_request_and_all_mutations(store, monkeypatch):
    conn = store
    module = importlib.import_module('request_web.shipping_calendar_api')
    @contextmanager
    def same_connection():
        yield SnapshotTestConnection(conn)
    monkeypatch.setattr(module, 'connection', same_connection)
    photo = image('ou_admin')
    owned = insert_request(conn, 申请人=[{'id': 'ou_owner'}], 发货图片=[{'local_media_id': photo['local_media_id']}])
    other = insert_request(conn, 申请人=[{'id': 'ou_other'}], 发货图片=[{'local_media_id': photo['local_media_id']}, {'file_token': 'other_remote_image'}])
    def viewer(request: Request):
        if request.headers.get('x-test-user') != 'owner':
            raise HTTPException(401, 'Not signed in')
        return 'ou_owner'
    def admin(request: Request):
        raise HTTPException(403, 'Admin only')
    api = FastAPI(); module.register(api, admin, viewer, lambda request: False)
    native = Mock(); monkeypatch.setattr(module, 'runtime', module.runtime)
    import app
    monkeypatch.setattr(app, '_native_feishu_bitable_client', lambda *a: native)
    with TestClient(api) as client:
        assert client.get('/api/shipping-calendar').status_code == 401
        headers = {'x-test-user': 'owner'}
        response = client.get('/api/shipping-calendar?owner=ou_other&all=true', headers=headers)
        assert response.status_code == 200
        data = response.json(); assert data['can_edit'] is False
        assert {r['request_id'] for r in data['requests']} == {owned}
        path = data['requests'][0]['images'][0]['path']
        assert client.get(path, headers=headers).status_code == 200
        assert client.get(f'/api/shipping-calendar/{other}/local-images/{photo["local_media_id"]}', headers=headers).status_code == 404
        assert client.get(f'/api/shipping-calendar/{other}/remote-images/other_remote_image', headers=headers).status_code == 404
        native.get_record.assert_not_called()
        for path in ['/api/admin/shipping-calendar/batch', '/api/admin/shipping-calendar/images', '/api/admin/shipping-calendar/save']:
            assert client.post(path, headers=headers, json={}).status_code == 403
        assert client.get('/api/admin/shipping-calendar', headers=headers).status_code == 403


def test_admin_general_catalog_sees_all_and_can_edit(store, monkeypatch):
    conn = store; one = insert_request(conn, 申请人=[{'id': 'ou_one'}]); two = insert_request(conn, 申请人=[{'id': 'ou_two'}])
    module = importlib.import_module('request_web.shipping_calendar_api')
    @contextmanager
    def same_connection(): yield SnapshotTestConnection(conn)
    monkeypatch.setattr(module, 'connection', same_connection)
    api = FastAPI(); module.register(api, lambda: 'ou_admin', lambda: 'ou_admin', lambda request: True)
    with TestClient(api) as client:
        data = client.get('/api/shipping-calendar').json()
        assert data['can_edit'] is True
        assert {one, two} <= {r['request_id'] for r in data['requests']}


def test_admin_date_change_updates_request_lines_schedule_and_notification_dependencies(store, monkeypatch):
    import app
    from order_scheduling import date_ms, BATCH_TABLE, DETAIL_TABLE
    for name in ['FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_BITABLE_APP_TOKEN']:
        monkeypatch.setenv(name, 'test')
    conn = store
    key = insert_request(conn, 申请人=[{'id': 'ou_owner'}])
    line = repo.named_table(conn, app.REQUEST_LINE_TABLE_NAME)
    detail = repo.named_table(conn, DETAIL_TABLE)
    orders = repo.named_table(conn, BATCH_TABLE)
    line_key, detail_key, batch_key = ['rec_' + uuid4().hex for _ in range(3)]
    old_day = date_ms('2026-10-28')
    repo.insert_source_records(conn, line, [{'record_id': line_key, 'fields': {'所属申请单': [key], '申请数量': 1, '物料发货时间': old_day}}])
    repo.insert_source_records(conn, orders, [{'record_id': batch_key, 'fields': {'物料发货时间': old_day}}])
    repo.insert_source_records(conn, detail, [{'record_id': detail_key, 'fields': {'来源申请单': [key], '所属下单批次': [batch_key], '物料发货时间': old_day}}])
    # Date-only edit must still create one applicant notice.
    item = change(conn, key, shipping_text='原说明', shipped=False, ship_date='2026-11-05')
    result = shipping.save_batch('ou_admin', batch([item]))
    assert result['changed'] == 1
    for info, rid in [(shipping.source_info(conn), key), (line, line_key), (detail, detail_key), (orders, batch_key)]:
        actual = repo.feishu_record(info, repo.raw_record(conn, info, rid))['fields']
        assert actual['物料发货时间'] == date_ms('2026-11-05')
    dependency_keys = {str(row[0]) for row in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s', (result['batch_id'],))}
    assert len(dependency_keys) == 4
    assert dependency_keys <= set(result['entries'][0]['outbox_ids'])
    args = conn.execute('SELECT args FROM material_ops.effects WHERE job_id=%s', (result['batch_id'],)).fetchone()[0]
    assert '2026-11-05' in args[1]


@pytest.mark.parametrize('value', ['2026-02-30', '2026-11-05T12:00:00', 'bad', '', None])
def test_invalid_or_cleared_admin_ship_date_rejects_whole_batch(store, value):
    conn = store; key = insert_request(conn, 申请人=[{'id': 'ou_owner'}])
    before = repo.raw_record(conn, shipping.source_info(conn), key)
    with pytest.raises(ValueError, match='日期'):
        shipping.save_batch('ou_admin', batch([change(conn, key, ship_date=value)]))
    assert repo.raw_record(conn, shipping.source_info(conn), key) == before


def test_authenticated_viewer_requires_valid_enterprise_session(monkeypatch):
    web = importlib.import_module('request_web.api')
    from request_web import feishu_auth
    monkeypatch.setattr(feishu_auth, 'own_tenant_key', lambda: 'tenant')
    monkeypatch.setattr(feishu_auth, 'session_identity', lambda cookie, tenant: None)
    with pytest.raises(HTTPException) as error:
        web.require_shipping_calendar_viewer(Request({'type': 'http', 'headers': []}))
    assert error.value.status_code == 401
