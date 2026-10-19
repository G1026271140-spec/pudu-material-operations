from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import pending_inventory_sqlite as pending
from request_web import api as web_api
from scripts.configure_pending_inventory_workflow import workflow_body


def _request(status: str = "待核实库存") -> dict:
    return {"record_id": "recRequest", "fields": {
        "申请单号": "REQ-TEST-001", "申请类型": "普通物料申请",
        "审批状态": "待审批", "库存审查状态": status,
    }}


def _line(line_id: str, quantity: int) -> dict:
    return {"record_id": line_id, "fields": {
        "申请单号": "REQ-TEST-001", "申请数量": quantity,
    }}


def test_pending_rows_are_replaced_and_cascaded_on_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("PUDU_PENDING_INVENTORY_DB", str(tmp_path / "pending.sqlite3"))
    assert pending.upsert(_request(), [_line("recLine1", 2), _line("recLine2", 4)])
    assert pending.get("recRequest") == (_request(), [_line("recLine1", 2), _line("recLine2", 4)])
    assert pending.list_pending()[0][1] == 2

    assert pending.upsert(_request(), [_line("recLine2", 5)])
    assert pending.get("recRequest")[1] == [_line("recLine2", 5)]
    assert not pending.upsert(_request("已核实库存"), [_line("recLine2", 5)])
    assert pending.get("recRequest") is None
    assert pending.list_pending() == []


def test_incomplete_or_other_request_never_enters_pending_index(tmp_path, monkeypatch):
    monkeypatch.setenv("PUDU_PENDING_INVENTORY_DB", str(tmp_path / "pending.sqlite3"))
    try:
        pending.upsert(_request(), [])
    except ValueError as exc:
        assert "缺少申请明细" in str(exc)
    else:
        raise AssertionError("incomplete request was accepted")
    other = _request()
    other["fields"]["申请类型"] = "文化周边申请"
    assert not pending.upsert(other, [_line("recLine1", 1)])
    assert pending.list_pending() == []


def test_pending_webhook_requires_token_and_queues_record(monkeypatch):
    submitted = []
    monkeypatch.setattr(web_api, "_check_corporate_exchange_webhook_token",
                        lambda token: (_ for _ in ()).throw(ValueError("bad token")) if token != "good" else None)
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_EXECUTOR", SimpleNamespace(
        submit=lambda fn, record_id: submitted.append((fn, record_id))
    ))
    client = TestClient(web_api.api)
    response = client.post("/api/pending-inventory-sync", json={"record_id": "recRequest"},
                           headers={"X-Pudu-Pending-Token": "good"})
    assert response.status_code == 202
    assert submitted[0][1] == "recRequest"
    assert client.post("/api/pending-inventory-sync", json={"record_id": "bad"},
                       headers={"X-Pudu-Pending-Token": "good"}).status_code == 422


def test_workflow_passes_only_record_id_to_tokened_endpoint():
    body = workflow_body("https://example.test/api/pending-inventory-sync", "secret")
    assert body["steps"][0]["type"] == "ChangeRecordTrigger"
    action = body["steps"][1]
    assert action["type"] == "HTTPClientAction"
    assert action["data"]["raw_body"][1]["value"] == "$.request_change.recordId"
    assert action["data"]["headers"][1]["value"][0]["value"] == "secret"
