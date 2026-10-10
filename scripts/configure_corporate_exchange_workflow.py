"""Configure a Base automation that wakes the corporate-exchange quota reconciler."""
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

from scripts.reconcile_corporate_apparel_quotas import EXCHANGE_TABLE, _client

TITLE = "文化周边兑换份额即时同步"
WEBHOOK_PATH = "/api/corporate-exchange-sync"


def workflow_body(url: str, secret: str) -> dict:
    return {
        "client_token": uuid.uuid4().hex,
        "title": TITLE,
        "steps": [
            {
                "id": "exchange_change",
                "type": "ChangeRecordTrigger",
                "title": "文化周边兑换记录新增或修改",
                "next": "wake_reconciler",
                "data": {
                    "table_name": EXCHANGE_TABLE,
                    "condition_list": [
                        {"conjunction": "and", "conditions": [
                            {"field_name": "数量", "operator": "isNotEmpty", "value": []}
                        ]}
                    ],
                },
            },
            {
                "id": "wake_reconciler",
                "type": "HTTPClientAction",
                "title": "通知营销物料管理系统更新份额",
                "next": None,
                "data": {
                    "method": "POST",
                    "url": [{"value_type": "text", "value": url}],
                    "headers": [
                        {"key": "Content-Type", "value": [{"value_type": "text", "value": "application/json"}]},
                        {"key": "User-Agent", "value": [{"value_type": "text", "value": "PuduMaterialExchangeSync/1.0"}]},
                        {"key": "X-Pudu-Exchange-Token", "value": [{"value_type": "text", "value": secret}]},
                    ],
                    "body_type": "raw",
                    "raw_body": [
                        {"value_type": "text", "value": '{"record_id":"'},
                        {"value_type": "ref", "value": "$.exchange_change.recordId"},
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
    parser.add_argument("--apply", action="store_true", help="Create and enable the workflow.")
    args = parser.parse_args()
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))
    secret = str(secrets.get("CORPORATE_EXCHANGE_WEBHOOK_TOKEN") or "")
    if len(secret) < 32:
        raise RuntimeError("缺少独立的兑换同步回调密钥。")
    config = json.loads((ROOT / "config" / "project_config.json").read_text(encoding="utf-8-sig"))
    url = str(config["deployment"]["custom_domain"]).rstrip("/") + WEBHOOK_PATH
    client = _client()
    tables = client.list_tables()
    if sum(str(table.get("name") or "") == EXCHANGE_TABLE for table in tables) != 1:
        raise RuntimeError("未唯一定位‘文化周边兑换’源表。")
    base = quote(client.config.app_token, safe="")
    endpoint = f"/base/v3/bases/{base}/workflows"
    existing = client._request("POST", endpoint + "/list", payload={"page_size": 100})
    items = list((existing.get("data") or {}).get("items") or [])
    matching = [item for item in items if str(item.get("title") or "") == TITLE]
    if len(matching) > 1:
        raise RuntimeError("发现同名自动化流程，请先处理重复配置。")
    if not args.apply:
        print(json.dumps({"dry_run": True, "table": EXCHANGE_TABLE, "url": url,
                          "existing": [(item.get("workflow_id"), item.get("status")) for item in matching]},
                         ensure_ascii=False))
        return 0
    if matching:
        workflow_id = str(matching[0].get("workflow_id") or matching[0].get("id") or "")
        status = str(matching[0].get("status") or "")
        current = dict((client._request("GET", endpoint + f"/{quote(workflow_id, safe='')}").get("data") or {}))
        desired = workflow_body(url, secret)
        if current.get("steps") != desired["steps"]:
            client._request("PUT", endpoint + f"/{quote(workflow_id, safe='')}",
                            payload={"title": TITLE, "steps": desired["steps"]})
    else:
        created = client._request("POST", endpoint, payload=workflow_body(url, secret))
        data = dict(created.get("data") or {})
        workflow = dict(data.get("workflow") or {})
        workflow_id = str(data.get("workflow_id") or workflow.get("workflow_id") or workflow.get("id") or "")
        if not workflow_id:
            raise RuntimeError("自动化创建已返回，但未取得 workflow ID；请检查源表，避免重复创建。")
        status = "disabled"
    if not workflow_id.startswith("wkf"):
        raise RuntimeError("自动化 workflow ID 无效。")
    if status != "enabled":
        client._request("PATCH", endpoint + f"/{quote(workflow_id, safe='')}/enable")
    checked = client._request("POST", endpoint + "/list", payload={"page_size": 100})
    verified = next((item for item in (checked.get("data") or {}).get("items") or []
                     if str(item.get("workflow_id") or item.get("id") or "") == workflow_id), {})
    if str(verified.get("status") or "") != "enabled":
        raise RuntimeError("自动化已创建但未验证为启用状态。")
    print(json.dumps({"configured": True, "workflow_id": workflow_id, "status": "enabled"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
