from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


NAME_FIELD_FALLBACKS = {
    "品类名称": ("品类名称", "实际发放物料品类"),
    "产品型号名称": ("产品型号名称", "实际发放产品型号"),
    "语种名称": ("语种名称", "实际发放语种"),
}


def build_name_snapshots(rows: list[dict]) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    for row in rows:
        record_id = app.feishu_record_id(row)
        fields = app.feishu_fields(row)
        if not record_id:
            continue
        values = {
            target: app.feishu_text_any(fields, candidates)
            for target, candidates in NAME_FIELD_FALLBACKS.items()
        }
        snapshots.append({"record_id": record_id, "fields": values})
    return snapshots


def migrate() -> dict[str, object]:
    client = app.feishu_client()
    if client is None:
        raise RuntimeError("飞书配置不可用。")
    table_id = app.feishu_table_id(app.REQUEST_LINE_TABLE_NAME)
    rows = app.fresh_feishu_rows(app.REQUEST_LINE_TABLE_NAME)
    snapshots = build_name_snapshots(rows)
    backup_dir = Path("work") / "schema_migrations"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"request-line-name-fields-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup_path.write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    live_fields = {item["field_name"]: item for item in client.list_fields(table_id)}
    converted: list[str] = []
    for field_name in NAME_FIELD_FALLBACKS:
        field = live_fields.get(field_name)
        if not field:
            raise RuntimeError(f"申请明细缺少字段：{field_name}")
        if int(field.get("type") or 0) != 1:
            client.update_field(table_id, str(field["field_id"]), field_name, 1)
            converted.append(field_name)

    app.refresh_feishu_schema_cache()
    updates = [
        {"record_id": item["record_id"], "fields": item["fields"]}
        for item in snapshots
        if any(str(value).strip() for value in item["fields"].values())
    ]
    app.feishu_batch_update_record_fields(app.REQUEST_LINE_TABLE_NAME, updates)
    return {
        "backup_path": str(backup_path.resolve()),
        "snapshot_count": len(snapshots),
        "updated_count": len(updates),
        "converted_fields": converted,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("请使用 --apply 确认执行字段迁移。")
    print(json.dumps(migrate(), ensure_ascii=False))


if __name__ == "__main__":
    main()
