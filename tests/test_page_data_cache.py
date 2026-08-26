import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from scripts.validate_page_data_cache import validate_page_data_cache


class PageDataCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        app.page_data_runtime_cache.clear()
        app.load_static_page_data_cache.clear()

    def tearDown(self) -> None:
        app.page_data_runtime_cache.clear()
        app.load_static_page_data_cache.clear()

    def test_request_page_and_form_cache_share_one_table_configuration(self) -> None:
        self.assertEqual(
            app.PAGE_CACHE_TABLES["request"],
            app.REQUEST_FORM_CACHE_TABLES,
        )

    def test_shipping_page_uses_category_cache(self) -> None:
        self.assertEqual(
            app.PAGE_CACHE_TABLES["shipping"],
            (app.CATEGORY_TABLE_NAME,),
        )

    def test_cached_category_keeps_shipping_fields(self) -> None:
        records = app.feishu_category_records_from_rows(
            [
                {
                    "record_id": "category-1",
                    "fields": {
                        "物料品类": "产品单页(Product Flyer)",
                        app.COMMERCIAL_INVOICE_NAME_FIELD: "Product Flyer",
                        app.PACKING_LIST_PRODUCT_TYPE_FIELD: "Flyers",
                    },
                }
            ]
        )

        self.assertEqual(records[0]["commercial_invoice_name"], "Product Flyer")
        self.assertEqual(records[0]["packing_list_product_type"], "Flyers")

    def test_gift_project_table_is_in_page_and_global_cache_configuration(self) -> None:
        self.assertIn(app.GIFT_PROJECT_TABLE_NAME, app.ALL_PAGE_CACHE_TABLES)
        self.assertIn(app.CULTURAL_MATERIAL_TABLE_NAME, app.ALL_PAGE_CACHE_TABLES)
        self.assertEqual(
            app.PAGE_CACHE_TABLES["cultural_request"],
            (
                app.CATEGORY_TABLE_NAME,
                app.MODEL_TABLE_NAME,
                app.CULTURAL_MATERIAL_TABLE_NAME,
                app.REGION_TABLE_NAME,
            ),
        )
        self.assertEqual(
            app.PAGE_CACHE_TABLES["gift_projects"],
            (
                app.CATEGORY_TABLE_NAME,
                app.MATERIAL_TABLE_NAME,
                app.GIFT_PROJECT_TABLE_NAME,
            ),
        )
        self.assertEqual(
            set(app.REQUEST_FORM_CACHE_TABLES),
            {
                app.CATEGORY_TABLE_NAME,
                app.MODEL_TABLE_NAME,
                app.LANGUAGE_TABLE_NAME,
                app.MATERIAL_TABLE_NAME,
            },
        )

    def test_page_cache_validator_includes_gift_project_catalog(self) -> None:
        category_rows = [
            {
                "record_id": "category-gift-1",
                "fields": {
                    "物料品类": "礼品袋",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                    "启用状态": app.STATUS_ACTIVE,
                },
            }
        ]
        material_rows = [
            {
                "record_id": "material-1",
                "fields": {"物料编码": "MAT-0001", "物料品类": "礼品袋"},
            }
        ]
        gift_project_rows: list[dict] = []
        cache = {
            "tables": {
                app.CATEGORY_TABLE_NAME: category_rows,
                app.MATERIAL_TABLE_NAME: material_rows,
                app.GIFT_PROJECT_TABLE_NAME: gift_project_rows,
            },
            "row_counts": {
                app.CATEGORY_TABLE_NAME: 1,
                app.MATERIAL_TABLE_NAME: 1,
                app.GIFT_PROJECT_TABLE_NAME: 0,
            },
        }

        stats = validate_page_data_cache(cache, require_data=True)

        self.assertEqual(stats["gift_categories"], 1)
        self.assertEqual(stats["gift_gallery_rows"], 1)
        self.assertEqual(stats["gift_project_rows"], 0)

    def test_page_cache_validator_rejects_missing_gift_project_table(self) -> None:
        cache = {
            "tables": {
                app.CATEGORY_TABLE_NAME: [],
                app.MATERIAL_TABLE_NAME: [],
            },
            "row_counts": {
                app.CATEGORY_TABLE_NAME: 0,
                app.MATERIAL_TABLE_NAME: 0,
            },
        }

        with self.assertRaisesRegex(ValueError, app.GIFT_PROJECT_TABLE_NAME):
            validate_page_data_cache(cache)

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

    def test_static_snapshot_reloads_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "page_data_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-07-15 12:00:00",
                        "tables": {app.MATERIAL_TABLE_NAME: [{"record_id": "old"}]},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(app, "PAGE_DATA_STATIC_CACHE_PATH", cache_path):
                first = app.load_static_page_data_cache()
                cache_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "generated_at": "2026-07-15 13:00:00",
                            "tables": {
                                app.MATERIAL_TABLE_NAME: [
                                    {"record_id": "new"},
                                    {"record_id": "new-2"},
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                second = app.load_static_page_data_cache()

        self.assertEqual(first["generated_at"], "2026-07-15 12:00:00")
        self.assertEqual(second["generated_at"], "2026-07-15 13:00:00")
        self.assertEqual(len(second["tables"][app.MATERIAL_TABLE_NAME]), 2)

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

    def test_newer_static_snapshot_overrides_older_runtime_cache(self) -> None:
        static_rows = [{"record_id": "deployed-new", "fields": {}}]
        runtime_rows = [{"record_id": "runtime-old", "fields": {}}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "page_data_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-08-13 15:00:00",
                        "tables": {app.MATERIAL_TABLE_NAME: static_rows},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(app, "PAGE_DATA_STATIC_CACHE_PATH", cache_path):
                app.load_static_page_data_cache.clear()
                runtime_cache = app.page_data_runtime_cache()
                runtime_cache["tables"] = {app.MATERIAL_TABLE_NAME: runtime_rows}
                runtime_cache["updated_at"] = {
                    app.MATERIAL_TABLE_NAME: "2026-08-13 14:00:00"
                }

                rows = app.page_data_cache_rows(app.MATERIAL_TABLE_NAME)
                source, updated_at = app.page_cache_status([app.MATERIAL_TABLE_NAME])

        self.assertEqual(rows, static_rows)
        self.assertEqual(source, "部署静态缓存")
        self.assertEqual(updated_at, "2026-08-13 15:00:00")

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
