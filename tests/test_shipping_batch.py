"""Batch confirmation, atomicity, delayed notifications and dedup in real PG."""
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_shipping_calendar import store, insert_request, draft, image
from material_store import shipping_calendar as shipping, repository as repo, effects, outbox_worker


def change(conn, key, **kwargs):
    result = draft(conn, key, **kwargs)
    result.pop('idempotency_key')
    return result


def batch(changes, **kwargs):
    return {'changes': changes, 'confirmed': True, 'idempotency_key': 'ship-batch-' + uuid4().hex, **kwargs}


def request(conn):
    return insert_request(conn, 申请人=[{'id': 'ou_isolated_applicant', 'name': '测试申请人'}])


def test_confirmation_required_and_batch_all_or_nothing(store):
    conn = store; one = request(conn); two = request(conn)
    original = [repo.raw_record(conn, shipping.source_info(conn), key) for key in [one, two]]
    changes = [change(conn, one), change(conn, two)]
    with pytest.raises(ValueError, match='确定提交'):
        shipping.save_batch('ou_admin', batch(changes, confirmed=False))
    changes[1]['expected_version'] += 1
    with pytest.raises(repo.VersionConflict):
        shipping.save_batch('ou_admin', batch(changes))
    assert [repo.raw_record(conn, shipping.source_info(conn), key) for key in [one, two]] == original
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=ANY(%s)', ([one, two],)).fetchone()[0] == 0


def test_two_orders_one_durable_batch_and_deduplicated_effects(store):
    conn = store; one = request(conn); two = request(conn)
    photo = image('ou_admin')
    body = batch([change(conn, one, images=[{'local_media_id': photo['local_media_id']}]), change(conn, two)])
    result = shipping.save_batch('ou_admin', body)
    assert result['changed'] == 2
    assert shipping.save_batch('ou_admin', body) == result
    assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s', (result['batch_id'],)).fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE job_id=%s', (result['batch_id'],)).fetchone()[0] == 2
    with pytest.raises(repo.VersionConflict):
        shipping.save_batch('ou_other', body)
    assert shipping.catalog(conn)['requests']
    states = shipping.notification_states(conn)
    assert states[one]['state'] == states[two]['state'] == 'pending'


def test_noop_batch_never_notifies_and_missing_applicant_never_partial_saves(store):
    conn = store; key = request(conn)
    result = shipping.save_batch('ou_admin', batch([change(conn, key, shipping_text='原说明', shipped=False)]))
    assert result['changed'] == 0 and result['unchanged'] == 1
    assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s', (result['batch_id'],)).fetchone()[0] == 0
    missing = insert_request(conn)
    with pytest.raises(ValueError, match='申请人账号'):
        shipping.save_batch('ou_admin', batch([change(conn, key), change(conn, missing)]))
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=ANY(%s)', ([key, missing],)).fetchone()[0] == 0


def test_effects_wait_for_outbox_without_using_attempts_then_retry_same_uuid(store, monkeypatch):
    conn = store
    @contextmanager
    def same_connection():
        yield conn
    monkeypatch.setattr(effects, 'connection', same_connection)
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    key = request(conn); result = shipping.save_batch('ou_admin', batch([change(conn, key)]))
    source = Mock()
    assert effects.run_once({'primary': source}) is None
    assert conn.execute('SELECT attempts,first_attempt_at FROM material_ops.effects WHERE job_id=%s', (result['batch_id'],)).fetchone() == (0, None)
    source._request.assert_not_called()
    # A real source conflict must also hold the applicant notification.
    conn.execute("UPDATE material_ops.outbox SET state='conflict' WHERE job_id=%s", (result['batch_id'],))
    assert effects.run_once({'primary': source}) is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE job_id=%s", (result['batch_id'],))
    source._request.side_effect = [TimeoutError('Simulated unknown send result'), {'data': {'message_id': 'om_shipping_test'}}]
    assert effects.run_once({'primary': source})['state'] == 'retry'
    conn.execute("UPDATE material_ops.effects SET available_at=now() WHERE job_id=%s", (result['batch_id'],))
    assert effects.run_once({'primary': source})['state'] == 'done'
    calls = source._request.call_args_list
    assert calls[0].kwargs['payload']['uuid'] == calls[1].kwargs['payload']['uuid']
    assert calls[1].kwargs['payload']['receive_id'] == 'ou_isolated_applicant'
    assert calls[1].kwargs['payload']['msg_type'] == 'interactive'
    assert '您的物料申请已发货' in calls[1].kwargs['payload']['content']
    assert 'shipping_view=readonly' in calls[1].kwargs['payload']['content']
    assert effects.run_once({'primary': source}) is None


def test_one_delayed_record_does_not_block_other_applicant_in_same_batch(store, monkeypatch):
    conn = store
    @contextmanager
    def same_connection():
        yield conn
    monkeypatch.setattr(effects, 'connection', same_connection)
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    one = request(conn); two = request(conn)
    result = shipping.save_batch('ou_admin', batch([change(conn, one), change(conn, two)]))
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE record_key=%s", (result['entries'][1]['request_id'],))
    source = Mock(); source._request.return_value = {'data': {'message_id': 'om_second'}}
    assert effects.run_once({'primary': source})['state'] == 'done'
    assert effects.run_once({'primary': source}) is None


def test_batch_api_and_old_single_save_cannot_bypass_confirmation(store):
    from request_web.shipping_calendar_api import register
    api = FastAPI(); register(api, lambda: 'ou_admin')
    key = request(store)
    with TestClient(api) as client:
        assert client.post('/api/admin/shipping-calendar/save', json=draft(store, key)).status_code == 422
        assert client.post('/api/admin/shipping-calendar/batch', json=batch([change(store, key)], confirmed=False)).status_code == 422
        response = client.post('/api/admin/shipping-calendar/batch', json=batch([change(store, key)]))
        assert response.status_code == 200, response.text
        assert response.json()['changed'] == 1


def test_later_batch_supersedes_only_never_attempted_old_notification(store):
    conn = store; key = request(conn)
    first = shipping.save_batch('ou_admin', batch([change(conn, key)]))
    second = shipping.save_batch('ou_admin', batch([change(conn, key, shipping_text='新的运单号')]))
    assert conn.execute('SELECT state,first_attempt_at FROM material_ops.effects WHERE job_id=%s', (first['batch_id'],)).fetchone() == ('failed', None)
    assert conn.execute('SELECT state FROM material_ops.effects WHERE job_id=%s', (second['batch_id'],)).fetchone() == ('pending',)


def test_notification_insertion_failure_rolls_back_all_business_changes(store, monkeypatch):
    conn = store; one = request(conn); two = request(conn)
    before = [repo.raw_record(conn, shipping.source_info(conn), key) for key in [one, two]]
    monkeypatch.setattr(effects, 'defer', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Isolated effect insertion failure')))
    with pytest.raises(RuntimeError, match='effect insertion'):
        shipping.save_batch('ou_admin', batch([change(conn, one), change(conn, two)]))
    assert [repo.raw_record(conn, shipping.source_info(conn), key) for key in [one, two]] == before
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=ANY(%s)', ([one, two],)).fetchone()[0] == 0
