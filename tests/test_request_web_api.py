import importlib

from fastapi.testclient import TestClient

import app as legacy_app
from request_web.api import api, build_catalog


web_api = importlib.import_module("request_web.api")


def test_catalog_uses_local_snapshot_and_exposes_all_products():
    catalog = build_catalog()
    assert len(catalog["products"]) == 11
    assert len(catalog["users"]) > 100
    assert catalog["rolesByUser"]
    assert all(product["options"] for product in catalog["products"])


def test_health_endpoint():
    response = TestClient(api).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workspace_excludes_gift_page_and_reads_cached_surfaces():
    payload = TestClient(api).get("/api/workspace").json()
    assert payload["inventory"]
    assert payload["categories"]
    assert payload["models"]
    assert payload["languages"]
    assert "giftProjects" not in payload


def test_fast_enqueue_performs_one_queue_write_without_readback(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, table_id, records):
            self.calls.append((table_id, records))
            return [{"record_id": "rec-queue"}]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue"))

    task_id = web_api._enqueue_fast("物料申请写入", "stable-token", {"version": 1})

    assert len(task_id) == 32
    assert len(client.calls) == 1
    table_id, rows = client.calls[0]
    assert table_id == "tbl-queue"
    assert len(rows) == 1
    assert rows[0]["幂等键"] == "stable-token"
    assert rows[0]["载荷JSON"] == '{"version":1}'


def test_submit_uses_page_snapshot_and_skips_live_permission_validation(monkeypatch):
    observed = {}
    payload = {
        "title": "test",
        "department": "市场部",
        "requester": "测试用户",
        "requester_open_id": "ou-test",
        "customer_name": "客户",
        "country": "中国",
        "recipient_info": "收件信息",
        "freight_payer": "PUDU",
        "material_usage": "测试",
        "submission_token": "stable-token",
        "scheduling_version": 1,
        "accepted_roles": ["区域市场经理"],
        "accepted_date": "2026-09-08",
        "accepted_at_ms": 1788796800000,
        "request_reason": "展会需求",
        "arrival_start": "2026-09-20",
        "arrival_end": "2026-09-20",
    }
    lines = [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}]

    def fake_validate(_draft, *, live):
        observed["live"] = live
        return payload, lines, []

    def fake_enqueue(task_type, idempotency_key, queued_payload):
        observed.update(task_type=task_type, key=idempotency_key, payload=queued_payload)
        return "task-fast"

    monkeypatch.setattr(web_api, "_validate", fake_validate)
    monkeypatch.setattr(web_api, "_enqueue_fast", fake_enqueue)
    monkeypatch.setattr(
        legacy_app,
        "queued_material_request_payload",
        lambda request_payload, request_lines: {
            "request_payload": request_payload,
            "lines": request_lines,
        },
    )

    response = TestClient(api).post(
        "/api/submit",
        json={**payload, "department_id": "od-test", "lines": lines},
    )

    assert response.status_code == 200
    assert response.json()["taskId"] == "task-fast"
    assert observed["live"] is False
    assert observed["key"] == "stable-token"
    assert observed["payload"]["request_payload"]["accepted_roles"] == ["区域市场经理"]
    assert observed["payload"]["request_payload"]["accepted_date"] == "2026-09-08"
