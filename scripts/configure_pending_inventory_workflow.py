"""Install the Base workflow that refreshes the local pending-inventory index."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
import uuid
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as legacy

TITLE = "未核实库存申请单本机同步"


def workflow_body(url: str, secret: str) -> dict:
    return {
        "client_token": uuid.uuid4().hex,
        "title": TITLE,
        "steps": [
            {
                "id": "request_change",
                "type": "ChangeRecordTrigger",
                "title": "申请单新增或修改",
                "next": "sync_pending",
                "data": {
                    "table_name": legacy.REQUEST_TABLE_NAME,
                    "condition_list": [{"conjunction": "and", "conditions": [
                        {"field_name": "申请单号", "operator": "isNotEmpty", "value": []}
                    ]}],
                },
            },
            {
                "id": "sync_pending",
                "type": "HTTPClientAction",
                "title": "通知营销物料管理系统更新本机待核实记录",
                "next": None,
                "data": {
                    "method": "POST",
                    "url": [{"value_type": "text", "value": url}],
                    "headers": [
                        {"key": "Content-Type", "value": [{"value_type": "text", "value": "application/json"}]},
                        {"key": "X-Pudu-Pending-Token", "value": [{"value_type": "text", "value": secret}]},
                    ],
                    "body_type": "raw",
                    "raw_body": [
                        {"value_type": "text", "value": '{"record_id":"'},
                        {"value_type": "ref", "value": "$.request_change.recordId"},
                        {"value_type": "text", "value": '"}'},
                    ],
                    "response_type": "json",
                    "response_value": '{"accepted":true}',
                },
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "config" / "project_config.json").read_text(encoding="utf-8-sig"))
    url = str(config["deployment"]["custom_domain"]).rstrip("/") + "/api/pending-inventory-sync"
    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("营销物料管理应用凭据未配置")
    tables = client.list_tables()
    table_id = legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME)
    if sum(item.get("table_id") == table_id for item in tables) != 1:
        raise RuntimeError("未唯一定位申请单源表")
    base = quote(client.config.app_token, safe="")
    endpoint = f"/base/v3/bases/{base}/workflows"
    listed = client._request("POST", endpoint + "/list", payload={"page_size": 100})
    matching = [item for item in (listed.get("data") or {}).get("items") or [] if item.get("title") == TITLE]
    if len(matching) > 1:
        raise RuntimeError("发现多个同名工作流，停止以避免重复触发")
    if not args.apply:
        print(json.dumps({"dry_run": True, "url": url, "existing": [
            {"id": item.get("workflow_id"), "status": item.get("status")} for item in matching
        ]}, ensure_ascii=False))
        return 0
    secrets = tomllib.loads(__import__("backend_runtime").secrets_path(ROOT).read_text(encoding="utf-8-sig"))
    secret = str(secrets.get("CORPORATE_EXCHANGE_WEBHOOK_TOKEN") or "")
    if len(secret) < 32:
        raise RuntimeError("未配置内部回调密钥")
    desired = workflow_body(url, secret)
    if matching:
        workflow_id = str(matching[0].get("workflow_id") or matching[0].get("id") or "")
        current = client._request("GET", endpoint + f"/{quote(workflow_id, safe='')}")
        if (current.get("data") or {}).get("steps") != desired["steps"]:
            client._request("PUT", endpoint + f"/{quote(workflow_id, safe='')}",
                            payload={"title": TITLE, "steps": desired["steps"]})
    else:
        created = client._request("POST", endpoint, payload=desired)
        data = dict(created.get("data") or {})
        workflow_id = str(data.get("workflow_id") or (data.get("workflow") or {}).get("workflow_id") or "")
    if not workflow_id.startswith("wkf"):
        raise RuntimeError("工作流创建结果没有有效 ID，请检查后重试")
    client._request("PATCH", endpoint + f"/{quote(workflow_id, safe='')}/enable")
    checked = client._request("POST", endpoint + "/list", payload={"page_size": 100})
    verified = next((item for item in (checked.get("data") or {}).get("items") or []
                     if str(item.get("workflow_id") or item.get("id") or "") == workflow_id), {})
    if verified.get("status") != "enabled":
        raise RuntimeError("工作流未能验证为启用状态")
    print(json.dumps({"configured": True, "workflow_id": workflow_id, "status": "enabled"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
