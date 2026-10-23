import json
import os
import time

from fastapi.testclient import TestClient

import corporate_exchange_sync as sync
from request_web import api as web_api
from scripts.configure_corporate_exchange_workflow import workflow_body


def test_workflow_watches_exchange_changes_and_sends_record_id():
    body = workflow_body("https://example.invalid/api/corporate-exchange-sync", "test-secret")
    trigger, action = body["steps"]
    assert trigger["type"] == "ChangeRecordTrigger"
    assert trigger["data"]["table_name"] == "文化周边兑换（扫码接口）"
    assert action["type"] == "HTTPClientAction"
    assert action["data"]["raw_body"][1]["value"] == "$.exchange_change.recordId"
    headers = {item["key"]: item["value"][0]["value"] for item in action["data"]["headers"]}
    assert headers["X-Pudu-Exchange-Token"] == "test-secret"
    assert headers["User-Agent"] == "PuduMaterialExchangeSync/1.0"


def test_webhook_rejects_wrong_token_and_queues_valid_record(monkeypatch, tmp_path):
    secrets_dir = tmp_path / ".streamlit"
    secrets_dir.mkdir()
    (secrets_dir / "secrets.toml").write_text(
        'CORPORATE_EXCHANGE_WEBHOOK_TOKEN = "test-token"', encoding="utf-8"
    )
    monkeypatch.setattr(web_api, "ROOT", tmp_path)
    called = []
    monkeypatch.setattr(sync.runner, "trigger", called.append)
    client = TestClient(web_api.api)
    body = {"record_id": "rec-example"}
    assert client.post("/api/corporate-exchange-sync", json=body).status_code == 401
    accepted = client.post(
        "/api/corporate-exchange-sync", json=body,
        headers={"X-Pudu-Exchange-Token": "test-token"},
    )
    assert accepted.status_code == 202
    assert accepted.json() == {"accepted": True}
    assert called == ["rec-example"]


def test_overlay_is_used_only_when_newer_than_published_cache(monkeypatch, tmp_path):
    cache = tmp_path / "page_data_cache.json"
    cache.write_text("{}", encoding="utf-8")
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"rows": [{"record_id": "new"}]}), encoding="utf-8")
    monkeypatch.setattr(sync, "OVERLAY_PATH", overlay)
    os.utime(cache, (time.time() - 20, time.time() - 20))
    assert sync.current_permission_rows(cache, [{"record_id": "old"}]) == [{"record_id": "new"}]
    os.utime(cache, None)
    assert sync.current_permission_rows(cache, [{"record_id": "old"}]) == [{"record_id": "old"}]


def test_plan_visible_waits_for_update_and_new_person():
    plan = {
        "updates": [{"record_id": "row-1", "fields": {"POLO申领数量累计": 2}}],
        "creates": [{"用户账号": [{"id": "ou-new"}], "文化夹克申领数量累计": 1}],
    }
    rows = [
        {"record_id": "row-1", "fields": {"POLO申领数量累计": 2}},
        {"record_id": "row-2", "fields": {"用户账号": [{"id": "ou-new"}], "文化夹克申领数量累计": 1}},
    ]
    assert sync._plan_visible(plan, rows)
    rows[1]["fields"]["文化夹克申领数量累计"] = 0
    assert not sync._plan_visible(plan, rows)
