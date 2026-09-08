import importlib
import json

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
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))

    task_id = web_api._enqueue_fast("物料申请写入", "stable-token", {"version": 1})

    assert len(task_id) == 32
    assert len(client.calls) == 1
    table_id, rows = client.calls[0]
    assert table_id == "tbl-queue"
    assert len(rows) == 1
    assert rows[0]["幂等键"] == "stable-token"
    assert rows[0]["载荷JSON"] == '{"version":1}'


def test_fast_enqueue_chunks_large_management_payload(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, table_id, records):
            self.calls.append((table_id, records))
            return [{"record_id": f"rec-{index}"} for index, _ in enumerate(records)]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_INLINE_LIMIT", 20)
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_CHUNK_SIZE", 10)

    web_api._enqueue_fast("物料品类同步", "large-token", {"rows": ["大型载荷" * 20]})

    assert [call[0] for call in client.calls] == ["tbl-payload", "tbl-queue"]
    marker = json.loads(client.calls[1][1][0]["载荷JSON"])
    assert marker["storage"] == "chunks"
    assert marker["chunks"] == len(client.calls[0][1])


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


def test_page_validation_enforces_cached_sales_lead_time(monkeypatch):
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {"rolesByUser": {"ou-sales": ["销售"]}},
    )
    monkeypatch.setattr(
        web_api,
        "_validate",
        lambda _draft, *, live: ({}, [], []),
    )
    monkeypatch.setattr("order_scheduling.today", lambda: "2026-09-08")

    response = TestClient(api).post(
        "/api/validate",
        json={
            "title": "test",
            "department": "市场部",
            "requester": "销售用户",
            "requester_open_id": "ou-sales",
            "customer_name": "客户",
            "country": "中国",
            "recipient_info": "收件信息",
            "material_usage": "测试",
            "request_reason": "展会需求",
            "arrival_start": "2026-09-10",
            "arrival_end": "2026-09-10",
            "lines": [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}],
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "至少提前7个自然日" in response.json()["errors"][0]


def test_page_validation_keeps_manager_time_exemption(monkeypatch):
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {"rolesByUser": {"ou-manager": ["销售", "区域市场经理"]}},
    )
    monkeypatch.setattr(web_api, "_validate", lambda _draft, *, live: ({}, [], []))
    monkeypatch.setattr("order_scheduling.today", lambda: "2026-09-08")

    response = TestClient(api).post(
        "/api/validate",
        json={
            "title": "test",
            "department": "市场部",
            "requester": "经理用户",
            "requester_open_id": "ou-manager",
            "customer_name": "客户",
            "country": "中国",
            "recipient_info": "收件信息",
            "material_usage": "测试",
            "request_reason": "展会需求",
            "arrival_start": "2026-09-10",
            "arrival_end": "2026-09-10",
            "lines": [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"valid": True, "errors": []}


def admin_client():
    client = TestClient(api)
    web_api._ADMIN_SESSIONS.add("test-admin-session")
    client.cookies.set("pudu_admin", "test-admin-session")
    return client


def test_management_catalog_requires_password_and_uses_cached_snapshot():
    assert TestClient(api).get("/api/admin/management-catalog").status_code == 401
    response = admin_client().get("/api/admin/management-catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"]
    assert payload["inventory"]
    assert payload["dimensions"]["model"]
    assert payload["dimensions"]["language"]
    assert payload["dimensions"]["region"]


def test_management_restock_queues_existing_worker_payload(monkeypatch):
    observed = {}
    monkeypatch.setattr(legacy_app, "validate_restock_draft", lambda draft: [])
    monkeypatch.setattr(legacy_app, "build_restock_no", lambda token: "RST-TEST")
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(
            task_type=task_type, key=key, payload=payload
        ) or "task-restock",
    )
    draft = {
        "operator": "管理员",
        "submission_token": "restock-token",
        "lines": [
            {
                "category_definition": "印刷物料",
                "product": "产品单页",
                "model": "T300",
                "language": "英语",
                "quantity": 10,
            }
        ],
    }
    response = admin_client().post("/api/admin/restock/submit", json=draft)
    assert response.status_code == 200
    assert response.json()["restockNo"] == "RST-TEST"
    assert observed["key"] == "RST-TEST"
    assert observed["payload"]["draft"]["lines"][0]["quantity"] == 10


def test_dimension_preview_builds_worker_changes_from_cached_associations(monkeypatch):
    snapshot = {
        "categories": [{"record_id": "cat-1", "category": "产品单页", "no_model": False, "no_language": False}],
        "inventory": [],
        "culturalInventory": [],
        "dimensions": {
            "model": [],
            "language": [{"record_id": "lang-1", "name": "英语"}],
            "region": [],
        },
    }
    monkeypatch.setattr(web_api, "_management_snapshot", lambda: snapshot)
    response = admin_client().post(
        "/api/admin/dimension/preview",
        json={
            "kind": "model",
            "operation": "create",
            "name": "T300",
            "status": "启用",
            "selected_keys": [["产品单页", "英语"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["changes"] == [
        {
            "action": "create",
            "category": "产品单页",
            "category_record_id": "cat-1",
            "model": "T300",
            "language": "英语",
            "region": "",
            "quantity": 0,
            "unit_price": 0.0,
            "customs_code": "",
            "status": "启用",
            "request_visible": "是",
        }
    ]


def test_category_submit_preserves_target_value_rows_for_worker(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(payload=payload) or "task-category",
    )
    response = admin_client().post(
        "/api/admin/category/submit",
        json={
            "operation": "edit",
            "submission_token": "category-token",
            "sync_args": {
                "old_product": "产品单页",
                "new_product": "产品单页",
                "target_values_rows": [
                    {
                        "model": "T300",
                        "language": "英语",
                        "values": {"quantity": 8, "status": "启用"},
                    }
                ],
            },
            "draft": {"product": "产品单页"},
        },
    )
    assert response.status_code == 200
    assert observed["payload"]["sync_args"]["target_values_rows"][0]["values"]["quantity"] == 8
