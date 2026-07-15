import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class PageDataCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        app.page_data_runtime_cache.clear()
        app.load_static_page_data_cache.clear()

    def tearDown(self) -> None:
        app.page_data_runtime_cache.clear()
        app.load_static_page_data_cache.clear()

    def test_feishu_rows_uses_static_snapshot_without_network(self) -> None:
        rows = [{"record_id": "material-1", "fields": {"物料编码": "MAT-0001"}}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "page_data_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-07-15 12:00:00",
                        "tables": {app.MATERIAL_TABLE_NAME: rows},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(app, "PAGE_DATA_STATIC_CACHE_PATH", cache_path),
                patch.object(app, "load_feishu_rows_snapshot") as live_loader,
            ):
                app.load_static_page_data_cache.clear()
                result = app.feishu_rows(app.MATERIAL_TABLE_NAME)

        self.assertEqual(result, rows)
        live_loader.assert_not_called()

    def test_runtime_refresh_overrides_static_snapshot(self) -> None:
        static_rows = [{"record_id": "old", "fields": {}}]
        fresh_rows = [{"record_id": "new", "fields": {}}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "page_data_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-07-15 12:00:00",
                        "tables": {app.MATERIAL_TABLE_NAME: static_rows},
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(app, "PAGE_DATA_STATIC_CACHE_PATH", cache_path),
                patch.object(app, "fresh_feishu_rows", return_value=fresh_rows),
            ):
                app.load_static_page_data_cache.clear()
                result = app.refresh_page_cache_tables([app.MATERIAL_TABLE_NAME])
                rows = app.feishu_rows(app.MATERIAL_TABLE_NAME)

        self.assertEqual(result["row_count"], 1)
        self.assertEqual(rows, fresh_rows)

    def test_empty_static_table_does_not_fall_back_to_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "page_data_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-07-15 12:00:00",
                        "tables": {app.REQUEST_TABLE_NAME: []},
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(app, "PAGE_DATA_STATIC_CACHE_PATH", cache_path),
                patch.object(app, "load_feishu_rows_snapshot") as live_loader,
            ):
                app.load_static_page_data_cache.clear()
                result = app.feishu_rows(app.REQUEST_TABLE_NAME)

        self.assertEqual(result, [])
        live_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
