from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from feishu_bitable import FeishuBitableClient
from scripts.check_feishu_bitable import load_config


MATERIAL_TABLE_ID = "tbl4UsiEmprnImIY"
REQUEST_LINE_TABLE_ID = "tbl6i0F9UZjTuTV1"
DIMENSION_LINKS = (
    ("品类", "品类关联"),
    ("产品型号", "型号关联"),
    ("语种", "语种关联"),
)


def record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def link_ids(fields: dict[str, Any], field_name: str) -> list[str]:
    value = fields.get(field_name)
    items = value if isinstance(value, list) else ([value] if value else [])
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            linked_id = item.get("record_id") or item.get("id")
            if linked_id:
                result.append(str(linked_id))
            nested_ids = item.get("record_ids") or item.get("link_record_ids") or []
            if isinstance(nested_ids, list):
                result.extend(str(nested_id) for nested_id in nested_ids if nested_id)
    return list(dict.fromkeys(result))


def build_repairs(
    material_records: list[dict[str, Any]],
    request_line_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    materials = {record_id(record): dict(record.get("fields") or {}) for record in material_records}
    repairs: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for line in request_line_records:
        line_id = record_id(line)
        line_fields = dict(line.get("fields") or {})
        material_ids = link_ids(line_fields, "物料编码")
        material_fields = materials.get(material_ids[0], {}) if len(material_ids) == 1 else {}
        patch: dict[str, Any] = {}
        for line_field, material_field in DIMENSION_LINKS:
            target_ids = link_ids(material_fields, material_field)
            if len(target_ids) != 1:
                unresolved.append(line_id)
                patch = {}
                break
            if link_ids(line_fields, line_field) != target_ids:
                patch[line_field] = target_ids
        if patch:
            repairs.append({"record_id": line_id, "fields": patch})

    return repairs, list(dict.fromkeys(unresolved))


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair request-line category/model/language links.")
    parser.add_argument("--apply", action="store_true", help="Write the generated repairs to Feishu.")
    args = parser.parse_args()

    client = FeishuBitableClient(load_config())
    material_records = client.list_records(MATERIAL_TABLE_ID)
    request_line_records = client.list_records(REQUEST_LINE_TABLE_ID)
    repairs, unresolved = build_repairs(material_records, request_line_records)

    print(f"Request lines: {len(request_line_records)}")
    print(f"Repairs needed: {len(repairs)}")
    print(f"Unresolved lines: {len(unresolved)}")
    if unresolved:
        print("Unresolved record IDs: " + ", ".join(unresolved))
    if not args.apply:
        print("Dry run only. Pass --apply to write the repairs.")
        return 1 if unresolved else 0

    updated = 0
    for start in range(0, len(repairs), 500):
        updated += len(client.batch_update_records(REQUEST_LINE_TABLE_ID, repairs[start : start + 500]))
    print(f"Updated lines: {updated}")

    verified_lines = client.list_records(REQUEST_LINE_TABLE_ID)
    remaining, remaining_unresolved = build_repairs(material_records, verified_lines)
    print(f"Remaining mismatches: {len(remaining)}")
    print(f"Remaining unresolved lines: {len(remaining_unresolved)}")
    return 0 if not remaining and not remaining_unresolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
