from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

EXCHANGE_TABLE = "文化周边兑换"
PERMISSION_TABLE = "用户权限表"
REQUEST_TABLE = "物料申请单"
REQUEST_LINE_TABLE = "申请明细"
QUEUE_TABLE = "后台任务队列"

STYLE_TO_FIELD = {
    "文化衫-休闲T恤-黑色（短袖）": "T恤-黑色（短袖）申领数量累计",
    "文化衫-休闲商务POLO-黑色（短袖）": "POLO申领数量累计",
    "文化衫-休闲商务夹克-黑色（长袖）": "文化夹克申领数量累计",
    "文化衫-商务衬衫-黑色（长袖）": "商务衬衫-黑色（长袖）神灵数量累计",
    "文化衫-休闲冲锋衣-黑色": "冲锋衣-黑色申领数量累计",
}
PRODUCT_TO_FIELD = {
    "T恤-黑色（短袖）": "T恤-黑色（短袖）申领数量累计",
    "休闲商务POLO-黑色（短袖）": "POLO申领数量累计",
    "休闲商务夹克-黑色（长袖）": "文化夹克申领数量累计",
    "商务衬衫-黑色（长袖）": "商务衬衫-黑色（长袖）神灵数量累计",
    "冲锋衣-黑色": "冲锋衣-黑色申领数量累计",
    "文化POLO衫": "POLO申领数量累计",
    "文化夹克": "文化夹克申领数量累计",
}


def _client() -> FeishuBitableClient:
    secrets = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    return FeishuBitableClient(
        FeishuBitableConfig(
            str(secrets["FEISHU_APP_ID"]),
            str(secrets["FEISHU_APP_SECRET"]),
            str(secrets["FEISHU_BITABLE_APP_TOKEN"]),
        )
    )


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _people(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _person_id(fields: dict[str, Any], field: str) -> str:
    return next(
        (str(item.get("id") or "") for item in _people(fields.get(field)) if item.get("id")),
        "",
    )


def _person_name(fields: dict[str, Any], field: str) -> str:
    return next(
        (str(item.get("name") or item.get("en_name") or "") for item in _people(fields.get(field))),
        "",
    )


def _linked_text(fields: dict[str, Any], field: str) -> str:
    for item in fields.get(field) or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return text
    return ""


def build_plan(client: FeishuBitableClient) -> dict[str, Any]:
    schema = client.discover_schema()["tables"]
    rows = {
        name: client.list_records(schema[name]["table_id"])
        for name in (EXCHANGE_TABLE, PERMISSION_TABLE, REQUEST_TABLE, REQUEST_LINE_TABLE, QUEUE_TABLE)
    }
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    people: dict[str, str] = {}

    for row in rows[EXCHANGE_TABLE]:
        fields = dict(row.get("fields") or {})
        quota_field = STYLE_TO_FIELD.get(str(fields.get("款式") or "").strip())
        open_id = _person_id(fields, "兑换人")
        quantity = _int(fields.get("数量"))
        if quota_field and open_id and quantity > 0:
            totals[open_id][quota_field] += quantity
            people[open_id] = _person_name(fields, "兑换人")

    requests_by_no: dict[str, dict[str, Any]] = {}
    for row in rows[REQUEST_TABLE]:
        fields = dict(row.get("fields") or {})
        request_no = str(fields.get("申请单号") or "").strip()
        if request_no:
            requests_by_no[request_no] = fields

    completed_corporate_tokens = {
        str(fields.get("幂等键") or "").strip()
        for row in rows[QUEUE_TABLE]
        if (fields := dict(row.get("fields") or {})).get("任务类型") == "企业文化衫领取"
        and fields.get("状态") == "已完成"
    }

    for row in rows[REQUEST_LINE_TABLE]:
        fields = dict(row.get("fields") or {})
        if str(fields.get("明细状态") or "").strip() == "已驳回":
            continue
        quota_field = PRODUCT_TO_FIELD.get(str(fields.get("品类名称") or "").strip())
        if not quota_field:
            continue
        quantity = _int(
            fields.get("实际发放数量")
            or fields.get("审批通过数量")
            or fields.get("申请数量")
        )
        if quantity <= 0:
            continue
        request_no = _linked_text(fields, "所属申请单")
        if not request_no:
            line_no = str(fields.get("明细编号") or "").strip()
            request_no = line_no.rsplit("-", 1)[0] if line_no else ""
        request_fields = requests_by_no.get(request_no, {})
        if (
            str(fields.get("明细业务类型") or "").strip() == "企业文化衫"
            and str(request_fields.get("提交幂等键") or "").strip()
            not in completed_corporate_tokens
        ):
            continue
        open_id = _person_id(request_fields, "申请人") or _person_id(request_fields, "申请人姓名")
        if not open_id:
            continue
        totals[open_id][quota_field] += quantity
        people.setdefault(
            open_id,
            _person_name(request_fields, "申请人") or _person_name(request_fields, "申请人姓名"),
        )

    permission_by_user: dict[str, dict[str, Any]] = {}
    max_number = 0
    for row in rows[PERMISSION_TABLE]:
        fields = dict(row.get("fields") or {})
        open_id = _person_id(fields, "用户账号")
        if open_id:
            permission_by_user[open_id] = row
        raw_number = str(fields.get("用户编号") or "").strip()
        if raw_number.isdigit():
            max_number = max(max_number, int(raw_number))

    updates: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []
    for open_id, quota_totals in sorted(totals.items()):
        existing = permission_by_user.get(open_id)
        if existing:
            current_fields = dict(existing.get("fields") or {})
            changed = {
                field: max(_int(current_fields.get(field)), quantity)
                for field, quantity in quota_totals.items()
                if max(_int(current_fields.get(field)), quantity) != _int(current_fields.get(field))
            }
            if changed:
                updates.append({"record_id": existing["record_id"], "fields": changed})
            continue
        max_number += 1
        creates.append(
            {
                "用户编号": str(max_number),
                "用户账号": [{"id": open_id}],
                "角色": ["销售"],
                "是否启用": "是",
                **quota_totals,
            }
        )

    return {
        "table_id": schema[PERMISSION_TABLE]["table_id"],
        "updates": updates,
        "creates": creates,
        "source_user_count": len(totals),
        "source_quantity_by_field": {
            field: sum(user_totals.get(field, 0) for user_totals in totals.values())
            for field in STYLE_TO_FIELD.values()
        },
        "people": people,
    }


def _chunks(items: list[dict[str, Any]], size: int = 500) -> list[list[dict[str, Any]]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile corporate-apparel quotas from exchange and issued requests.")
    parser.add_argument("--apply", action="store_true", help="Write the calculated updates and missing users.")
    args = parser.parse_args()
    client = _client()
    plan = build_plan(client)
    if args.apply:
        for chunk in _chunks(plan["updates"]):
            client.batch_update_records(plan["table_id"], chunk)
        for chunk in _chunks(plan["creates"]):
            client.batch_create_records(plan["table_id"], chunk)
    print(json.dumps({
        "applied": args.apply,
        "source_user_count": plan["source_user_count"],
        "updated_user_count": len(plan["updates"]),
        "created_user_count": len(plan["creates"]),
        "source_quantity_by_field": plan["source_quantity_by_field"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
