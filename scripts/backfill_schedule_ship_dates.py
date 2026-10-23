"""Fill missing schedule shipping dates from their source requests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import app
import order_scheduling as rules


def main() -> int:
    requests = app.fresh_feishu_rows(app.REQUEST_TABLE_NAME)
    request_lines = app.fresh_feishu_rows(app.REQUEST_LINE_TABLE_NAME)
    details = app.fresh_feishu_rows(rules.DETAIL_TABLE)
    line_updates = 0
    detail_updates = 0
    batch_updates = 0
    request_ship_dates = {}
    for row in requests:
        fields = app.feishu_fields(row)
        ship_value = fields.get(rules.SHIP_DATE)
        if ship_value in (None, ""):
            continue
        request_id = app.feishu_record_id(row)
        if request_id:
            request_ship_dates[request_id] = ship_value
    for row in request_lines:
        fields = app.feishu_fields(row)
        if fields.get(rules.SHIP_DATE) not in (None, ""):
            continue
        request_ids = app.feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        ship_value = next((request_ship_dates.get(request_id) for request_id in request_ids if request_id in request_ship_dates), None)
        if ship_value in (None, ""):
            continue
        app.feishu_update_record_fields(app.REQUEST_LINE_TABLE_NAME, app.feishu_record_id(row), {rules.SHIP_DATE: ship_value})
        line_updates += 1
    for row in details:
        fields = app.feishu_fields(row)
        if fields.get(rules.SHIP_DATE) not in (None, ""):
            continue
        request_ids = app.feishu_link_ids(fields, "来源申请单")
        ship_value = next((request_ship_dates.get(request_id) for request_id in request_ids if request_id in request_ship_dates), None)
        if ship_value in (None, ""):
            continue
        app.feishu_update_record_fields(rules.DETAIL_TABLE, app.feishu_record_id(row), {rules.SHIP_DATE: ship_value})
        detail_updates += 1
    batches = app.fresh_feishu_rows(rules.BATCH_TABLE)
    for row in batches:
        fields = app.feishu_fields(row)
        if fields.get(rules.SHIP_DATE) not in (None, ""):
            continue
        batch_id = app.feishu_record_id(row)
        batch_detail = next((item for item in details if batch_id in app.feishu_link_ids(app.feishu_fields(item), "所属下单批次")), None)
        if batch_detail is None:
            continue
        request_ids = app.feishu_link_ids(app.feishu_fields(batch_detail), "来源申请单")
        ship_value = next((request_ship_dates.get(request_id) for request_id in request_ids if request_id in request_ship_dates), None)
        if ship_value in (None, ""):
            continue
        app.feishu_update_record_fields(rules.BATCH_TABLE, batch_id, {rules.SHIP_DATE: ship_value})
        batch_updates += 1
    print(json.dumps({"request_count": len(request_ship_dates), "request_line_updates": line_updates,
                      "detail_updates": detail_updates, "batch_updates": batch_updates}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
