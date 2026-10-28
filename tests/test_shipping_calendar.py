import importlib
import os
from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

import app
import backend_runtime as runtime
from material_store import repository as repo, shipping_calendar as shipping, media

psycopg = pytest.importorskip('psycopg')
DSN = os.environ.get('PUDU_TEST_DATABASE_DSN')


@pytest.mark.parametrize('roles,enabled,allowed', [
    (['管理员'], '是', True), (['HR', '管理员'], '是', True),
    (['HR'], '是', False), (['销售'], '是', False), (['管理员'], '否', False), ([], '是', False),
])
def test_shipping_requires_enabled_administrator(monkeypatch, roles, enabled, allowed):
    web = importlib.import_module('request_web.api')
    from request_web import feishu_auth
    monkeypatch.setattr(feishu_auth, 'session_identity', lambda *args: {'open_id': 'ou_shipping_auth'})
    monkeypatch.setattr(feishu_auth, 'own_tenant_key', lambda: 'test-tenant')
    monkeypatch.setattr(web, '_json', lambda name: {'tables': {'用户权限表': [{'fields': {'用户账号': [{'id': 'ou_shipping_auth'}], '角色': roles, '是否启用': enabled}}]}})
    request = Request({'type': 'http', 'headers': [(b'cookie', b'pudu_feishu=fake')]})
    if allowed:
        assert web.require_admin(request) == 'ou_shipping_auth'
    else:
        with pytest.raises(HTTPException) as error:
            web.require_admin(request)
        assert error.value.status_code == 403


@pytest.fixture
def store(monkeypatch, tmp_path):
    if not DSN:
        pytest.skip('Requires isolated PostgreSQL database')
    monkeypatch.setenv('PUDU_DATA_SOURCE', 'postgresql')
    monkeypatch.setenv('PUDU_DATABASE_DSN', DSN)
    monkeypatch.setenv('PUDU_MEDIA_ROOT', str(tmp_path / 'media'))
    from feishu_bitable import FeishuBitableClient
    monkeypatch.setattr(FeishuBitableClient, '_request', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Unexpected Feishu HTTP')))
    with psycopg.connect(DSN, autocommit=True) as conn:
        assert conn.execute('SELECT current_database()').fetchone()[0] == 'pudu_materials_test'
        @contextmanager
        def same_connection():
            yield conn
        monkeypatch.setattr(shipping, 'connection', same_connection)
        monkeypatch.setattr(media, 'connection', same_connection)
        with pytest.raises(RuntimeError, match='rollback'):
            with conn.transaction(), runtime.request_scope():
                yield conn
                raise RuntimeError('rollback')


def insert_request(conn, **updates):
    from order_scheduling import date_ms
    info = shipping.source_info(conn)
    key = 'rec_shipping_' + uuid4().hex
    fields = {'申请单号': 'SHIP-' + uuid4().hex, '申请类型': '普通物料申请',
              '库存审查状态': '已核实库存', '审批状态': '已发放',
              '备注': '申请人：隔离发货验收', '物料发货时间': date_ms('2026-10-28'),
              '要求达到开始日期': date_ms('2026-11-02'), '是否发货': False,
              '发货单号及文字信息': '原说明', '发货图片': [], **updates}
    repo.insert_source_records(conn, info, [{'record_id': key, 'fields': fields}])
    return key


def draft(conn, key, **updates):
    old = repo.raw_record(conn, shipping.source_info(conn), key)
    return {'request_id': key, 'expected_version': old['version'], 'shipping_text': 'DHL 123\n发货说明',
            'shipped': True, 'images': [], 'idempotency_key': 'ship-' + uuid4().hex, **updates}


def image(actor):
    output = BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(output, 'PNG')
    return media.save_image(output.getvalue(), 'shipment.png', actor)


def test_catalog_eligibility_dates_and_full_lines(store):
    conn = store
    key = insert_request(conn)
    missing = insert_request(conn, 物料发货时间=None, 要求达到开始日期=None)
    excluded = [insert_request(conn, **patch) for patch in [
        {'库存审查状态': '待核实库存'}, {'申请类型': '文化周边申请'},
        {'审批状态': '已撤回'}, {'审批状态': '已驳回'}, {'审批状态': '已取消'},
    ]]
    number = repo.feishu_record(shipping.source_info(conn), repo.raw_record(conn, shipping.source_info(conn), key))['fields']['申请单号']
    line_info = repo.named_table(conn, app.REQUEST_LINE_TABLE_NAME)
    # No language/model: the shipping UI must retain this custom/historical line.
    repo.insert_source_records(conn, line_info, [{'record_id': 'rec_line_' + uuid4().hex, 'fields': {
        '明细编号': number + '-01', '所属申请单': [key], '品类名称': '自定义物料',
        '申请数量': 4, '审批通过数量': 3, '实际发放数量': 2, '备注': '历史规格缺失',
    }}])
    requests = {item['request_id']: item for item in shipping.catalog(conn)['requests']}
    assert key in requests and missing in requests
    assert not set(excluded).intersection(requests)
    assert requests[key]['ship_date'] == '2026-10-28'
    assert requests[key]['arrival_start'] == '2026-11-02'
    assert requests[missing]['ship_date'] == ''
    assert requests[key]['lines'][0]['product'] == '自定义物料'
    assert requests[key]['lines'][0]['approved_quantity'] == 3


def test_save_atomic_three_fields_audit_idempotency_and_stale_editor(store):
    conn = store; key = insert_request(conn); actor = 'ou_shipping_actor'
    upload = image(actor)
    body = draft(conn, key, images=[{'local_media_id': upload['local_media_id']}])
    before = repo.raw_record(conn, shipping.source_info(conn), key)
    result = shipping.save(actor, body)
    assert shipping.save(actor, body) == result
    current = repo.raw_record(conn, shipping.source_info(conn), key)
    fields = repo.feishu_record(shipping.source_info(conn), current)['fields']
    assert fields[shipping.TEXT] == body['shipping_text'] and fields[shipping.SHIPPED] is True
    assert fields[shipping.IMAGES][0]['local_media_id'] == upload['local_media_id']
    assert current['version'] == before['version'] + 1 and current['sync_state'] == 'pending'
    tasks = conn.execute('SELECT lane,patch FROM material_ops.outbox WHERE record_key=%s', (key,)).fetchall()
    fids = {f['field_id'] for f in shipping.source_info(conn)['fields'] if f['field_name'] in {shipping.TEXT, shipping.SHIPPED, shipping.IMAGES}}
    assert len(tasks) == 1 and tasks[0][0] == 'ordinary' and set(tasks[0][1]) == fids
    assert conn.execute('SELECT count(*) FROM material_ops.audit WHERE record_key=%s AND actor_open_id=%s', (key, actor)).fetchone()[0] == 3
    with pytest.raises(repo.VersionConflict):
        shipping.save(actor, {**body, 'idempotency_key': 'stale-' + uuid4().hex})
    with pytest.raises(repo.VersionConflict):
        shipping.save(actor, {**body, 'shipping_text': '重复标识改值'})
    with pytest.raises(repo.VersionConflict):
        shipping.save('ou_other', body)
    # Unchecking uses the same workflow and immediately moves the local card back.
    shipping.save(actor, draft(conn, key, shipped=False, shipping_text='', images=[]))
    item = next(item for item in shipping.catalog(conn)['requests'] if item['request_id'] == key)
    assert not item['shipped'] and item['images'] == []


def test_foreign_images_extra_fields_and_invalid_checkbox_do_not_partially_save(store):
    conn = store; key = insert_request(conn)
    foreign = image('ou_someone_else')
    initial = repo.raw_record(conn, shipping.source_info(conn), key)
    for patch in [
        {'images': [{'local_media_id': foreign['local_media_id']}]},
        {'images': [{'file_token': 'unrelated-source-token'}]}, {'shipped': '是'},
        {'库存审查状态': '已核实库存'}, {'shipping_text': 'a' * 20001},
        {'images': [{'local_media_id': 'not-a-uuid'}]},
    ]:
        with pytest.raises(ValueError):
            shipping.save('ou_actor', draft(conn, key, **patch))
        assert repo.raw_record(conn, shipping.source_info(conn), key) == initial
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=%s', (key,)).fetchone()[0] == 0


def test_status_changed_since_open_is_rejected(store):
    conn = store; key = insert_request(conn); body = draft(conn, key)
    info = shipping.source_info(conn); old = repo.raw_record(conn, info, key)
    changed = {**old['fields'], **repo.source_values(info, {'库存审查状态': '待核实库存'})}
    repo.replace_values(conn, info, key, changed)
    with pytest.raises(ValueError, match='已核实库存'):
        shipping.save('ou_actor', body)


def test_worker_uploads_photo_once_across_retry_and_publishes_only_shipping_fields(store, monkeypatch):
    conn = store
    from material_store import outbox_worker
    @contextmanager
    def same_connection():
        yield conn
    monkeypatch.setattr(outbox_worker, 'connection', same_connection)
    # The restored fixture may contain unrelated jobs. Keep this test publisher isolated.
    conn.execute("UPDATE material_ops.outbox SET state='cancelled' WHERE state IN ('pending','retry','processing')")
    key = insert_request(conn); info = shipping.source_info(conn)
    original = repo.feishu_record(info, repo.raw_record(conn, info, key))
    upload = image('ou_actor')
    class Source:
        calls = []; uploads = 0; attempts = 0
        row = original
        def get_record(self, table, rid):
            assert table == info['table_id'] and rid == key
            return self.row
        def update_record(self, table, rid, fields):
            self.attempts += 1
            if self.attempts == 1:
                raise TimeoutError('Isolated simulated Feishu timeout')
            self.calls.append(fields); self.row['fields'].update(fields)
        def upload_media(self, *args):
            self.uploads += 1; return 'shipping-uploaded-token'
    source = Source()
    shipping.save('ou_actor', draft(conn, key, images=[{'local_media_id': upload['local_media_id']}]))
    result = outbox_worker.run_once('ordinary', {'primary': source})
    assert result['state'] == 'retry'
    assert repo.raw_record(conn, info, key)['fields'][next(f['field_id'] for f in info['fields'] if f['field_name'] == shipping.SHIPPED)] is True
    conn.execute("UPDATE material_ops.outbox SET available_at=now() WHERE record_key=%s", (key,))
    result = outbox_worker.run_once('ordinary', {'primary': source})
    assert result['state'] == 'done'
    assert source.uploads == 1 and len(source.calls) == 1
    assert set(source.calls[0]) == {shipping.TEXT, shipping.IMAGES, shipping.SHIPPED}
    assert source.calls[0][shipping.IMAGES] == [{'file_token': 'shipping-uploaded-token'}]
    assert source.row['fields'][shipping.SHIPPED] is True
    assert repo.raw_record(conn, info, key)['sync_state'] == 'synced'


def test_daily_feishu_authority_covers_shipping_fields(store):
    from material_store.reconcile import reconcile_snapshot
    conn = store; key = insert_request(conn); info = shipping.source_info(conn)
    shipping.save('ou_actor', draft(conn, key))
    source = repo.rows(conn, info)
    # Daily source snapshot is authoritative even when it differs from a local pending edit.
    for row in source:
        if row['record_id'] == key:
            row['fields'].update({shipping.TEXT: '飞书人工修改', shipping.SHIPPED: False, shipping.IMAGES: []})
    run_id = conn.execute("INSERT INTO material_ops.reconcile_runs(state) VALUES ('running') RETURNING id").fetchone()[0]
    reconcile_snapshot(conn, info, source, run_id)
    current = repo.raw_record(conn, info, key)
    fields = repo.feishu_record(info, current)['fields']
    assert fields[shipping.TEXT] == '飞书人工修改' and fields[shipping.SHIPPED] is False
    assert fields[shipping.IMAGES] == [] and current['sync_state'] == 'synced'
    assert conn.execute('SELECT state FROM material_ops.outbox WHERE record_key=%s', (key,)).fetchone()[0] == 'conflict'


def test_shipping_routes_all_require_admin_before_read_or_upload(monkeypatch):
    from request_web.shipping_calendar_api import register
    def denied():
        raise HTTPException(403, 'Denied')
    api = FastAPI(); register(api, denied)
    with TestClient(api) as client:
        for method, path in [
            ('GET', '/api/admin/shipping-calendar'), ('POST', '/api/admin/shipping-calendar/save'),
            ('POST', '/api/admin/shipping-calendar/images'), ('GET', '/api/admin/shipping-calendar/uploads/not-a-uuid'),
            ('GET', '/api/admin/shipping-calendar/record/local-images/not-a-uuid'),
            ('GET', '/api/admin/shipping-calendar/record/remote-images/token'),
        ]:
            assert client.request(method, path, json={}).status_code == 403
