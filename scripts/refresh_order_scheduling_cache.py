"""Refresh scheduling cache by reading Base only; never run inventory sync jobs."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from order_scheduling_service import SchedulingService
from scripts.validate_page_data_cache import validate_page_data_cache


def main():
    service = SchedulingService(app)
    service.validate_schema()
    cache = json.loads(app.PAGE_DATA_STATIC_CACHE_PATH.read_text(encoding="utf-8"))
    cached_paths = {}
    for rows in cache["tables"].values():
        for row in rows:
            for value in app.feishu_fields(row).values():
                for item in value if isinstance(value, list) else []:
                    if isinstance(item, dict) and item.get("file_token") and item.get("cached_path"):
                        cached_paths[item["file_token"]] = item["cached_path"]
    fresh = service.snapshot(live=True)  # strict: errors must not become empty tables
    for table in (app.CATEGORY_TABLE_NAME, app.MATERIAL_TABLE_NAME, app.USER_PERMISSION_TABLE_NAME):
        if not fresh[table]:
            raise ValueError(f"{table}读取为空，保留原缓存，禁止发布。")
    fresh[app.MATERIAL_TABLE_NAME] = app.material_rows_with_dimension_model_names(
        fresh[app.MATERIAL_TABLE_NAME], fresh[app.MODEL_TABLE_NAME])
    for table, rows in fresh.items():
        for row in rows:
            for value in app.feishu_fields(row).values():
                for item in value if isinstance(value, list) else []:
                    if isinstance(item, dict) and item.get("file_token") in cached_paths:
                        item["cached_path"] = cached_paths[item["file_token"]]
        cache["tables"][table] = rows
        cache["row_counts"][table] = len(rows)
    cache["order_scheduling_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
    validate_page_data_cache(cache, require_data=True, require_cached_gift_images=True, cache_root=ROOT)
    output = app.PAGE_DATA_STATIC_CACHE_PATH
    temp = output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output)
    print("order_scheduling_cache_valid", json.dumps({name: len(rows) for name, rows in fresh.items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
