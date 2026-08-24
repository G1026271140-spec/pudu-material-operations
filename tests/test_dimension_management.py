from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import pandas as pd

import app


class DimensionManagementTests(unittest.TestCase):
    def test_association_search_matches_category_model_or_language_text(self) -> None:
        associations = pd.DataFrame([
            {"关联": False, "物料品类": "产品单页(Product Flyer)", "语种": "英语(English)"},
            {"关联": True, "物料品类": "手持充电电风扇", "语种": "德语(German)"},
        ])

        by_category = app.filter_dimension_association_dataframe(
            associations, "电风扇", "语种"
        )
        by_language = app.filter_dimension_association_dataframe(
            associations, "english", "语种"
        )

        self.assertEqual(by_category["物料品类"].tolist(), ["手持充电电风扇"])
        self.assertEqual(by_language["语种"].tolist(), ["英语(English)"])

    def test_association_edits_persist_across_search_filters(self) -> None:
        session_state = {
            "selection": [["品类A", "英语"]],
            "editor": {
                "edited_rows": {
                    0: {"关联": False},
                    1: {"关联": True},
                }
            },
        }
        with patch.object(app.st, "session_state", session_state):
            app.persist_dimension_association_edits(
                "selection",
                "editor",
                [["品类A", "英语"], ["品类B", "德语"]],
            )

        self.assertEqual(session_state["selection"], [["品类B", "德语"]])

    def test_association_pool_only_pairs_no_dimension_categories_with_no_dimension_value(self) -> None:
        categories = [
            {"category": "无需型号品类", "no_model": True, "no_language": False},
            {"category": "无需语种品类", "no_model": False, "no_language": True},
            {"category": "完整品类", "no_model": False, "no_language": False},
        ]

        self.assertEqual(
            app.dimension_association_category_names("model", categories, "P1"),
            ["无需语种品类", "完整品类"],
        )
        self.assertEqual(
            app.dimension_association_category_names("model", categories, app.NO_MODEL_TEXT),
            ["无需型号品类"],
        )
        self.assertEqual(
            app.dimension_association_category_names("language", categories, "英语"),
            ["无需型号品类", "完整品类"],
        )
        self.assertEqual(
            app.dimension_association_category_names("language", categories, app.NO_LANGUAGE_TEXT),
            ["无需语种品类"],
        )

    def test_model_association_plan_lists_create_update_and_delete(self) -> None:
        categories = [
            {"record_id": "cat-a", "category": "品类A"},
            {"record_id": "cat-b", "category": "品类B"},
        ]
        materials = [
            {"record_id": "mat-1", "material_code": "MAT-0001", "category": "品类A", "model": "P1", "language": "英语", "quantity": 3, "status": "启用", "request_visible": "显示"},
            {"record_id": "mat-2", "material_code": "MAT-0002", "category": "品类A", "model": "P1", "language": "中文", "quantity": 2, "status": "启用", "request_visible": "显示"},
        ]

        changes = app.dimension_association_plan(
            "model", "edit", "P1", "P1 Pro",
            [["品类A", "英语"], ["品类B", "英语"]],
            materials, categories,
        )

        self.assertCountEqual([item["action"] for item in changes], ["update", "delete", "create"])
        updated = next(item for item in changes if item["action"] == "update")
        created = next(item for item in changes if item["action"] == "create")
        self.assertEqual(updated["model"], "P1 Pro")
        self.assertEqual(created["category_record_id"], "cat-b")

    def test_delete_language_plan_contains_every_referenced_material(self) -> None:
        materials = [
            {"record_id": "a", "category": "A", "model": "M1", "language": "英语", "quantity": 1},
            {"record_id": "b", "category": "A", "model": "M2", "language": "英语", "quantity": 0},
            {"record_id": "c", "category": "A", "model": "M2", "language": "中文", "quantity": 0},
        ]
        changes = app.dimension_association_plan(
            "language", "delete", "英语", "英语", [], materials,
            [{"record_id": "cat", "category": "A"}],
        )
        self.assertEqual([item["record_id"] for item in changes], ["a", "b"])
        self.assertTrue(all(item["action"] == "delete" for item in changes))

    def test_material_model_name_is_resolved_from_linked_model_record(self) -> None:
        models = [
            {"record_id": "model-1", "fields": {"产品型号": "Pudu SwiftBot"}}
        ]
        materials = [
            {
                "record_id": "material-1",
                "fields": {
                    "产品型号": "SwiftBot",
                    "型号关联": [{"record_ids": ["model-1"]}],
                },
            }
        ]

        updates = app.material_model_name_updates(materials, models)
        normalized = app.material_rows_with_dimension_model_names(materials, models)

        self.assertEqual(
            updates,
            [
                {
                    "record_id": "material-1",
                    "fields": {"产品型号": "Pudu SwiftBot"},
                }
            ],
        )
        self.assertEqual(
            normalized[0]["fields"]["产品型号"],
            "Pudu SwiftBot",
        )

    def test_create_model_assigns_next_numeric_code(self) -> None:
        model_rows = [
            {"record_id": "m1", "fields": {"产品型号编码": "7", "产品型号": "P1", "启用状态": "启用"}}
        ]
        with (
            patch.object(app, "fresh_feishu_rows", return_value=model_rows),
            patch.object(app, "feishu_batch_create_records", return_value=[{"record_id": "m2"}]) as create,
        ):
            result = app.execute_dimension_management(
                {
                    "kind": "model", "operation": "create", "name": "P2",
                    "status": "启用", "product_line": "CR",
                }
            )

        create.assert_called_once_with(
            app.MODEL_TABLE_NAME,
            [{
                "产品型号": "P2", "启用状态": "启用",
                "中文页面名称": "P2", "英文页面名称": "P2",
                "产品线": "CR",
                "产品型号编码": "8",
            }],
        )
        self.assertEqual(result["created_count"], 1)

    def test_edit_model_updates_product_line_and_page_names(self) -> None:
        model_rows = [{
            "record_id": "m1",
            "fields": {
                "产品型号编码": "1", "产品型号": "P1", "启用状态": "启用",
                "产品线": "IR", "中文页面名称": "旧中文", "英文页面名称": "Old English",
            },
        }]
        with (
            patch.object(app, "fresh_feishu_rows", return_value=model_rows),
            patch.object(app, "feishu_update_record_fields") as update,
            patch.object(app, "feishu_batch_update_record_fields", return_value=0),
        ):
            app.execute_dimension_management({
                "kind": "model", "operation": "edit", "record_id": "m1",
                "name": "P1", "status": "启用", "product_line": "CR",
                "zh_page_name": "新中文", "en_page_name": "New English",
            })

        update.assert_called_once_with(
            app.MODEL_TABLE_NAME,
            "m1",
            {
                "产品型号": "P1", "启用状态": "启用",
                "中文页面名称": "新中文", "英文页面名称": "New English",
                "产品线": "CR",
            },
        )

    def test_model_management_page_includes_product_line_in_draft_and_preview(self) -> None:
        source = inspect.getsource(app.render_dimension_management_page)

        self.assertIn('"产品线"', source)
        self.assertIn('"old_product_line": default_product_line', source)
        self.assertIn('"product_line": str(product_line or "").strip()', source)

    def test_new_request_models_link_existing_rows_without_creating_duplicates(self) -> None:
        model_rows = [
            {"record_id": "model-flash", "fields": {"产品型号": "FlashBot", "启用状态": "启用"}},
            {"record_id": "model-t150", "fields": {"产品型号": "T150", "启用状态": "启用"}},
        ]
        category_rows = [
            {"record_id": "cat-flyer", "fields": {"物料品类": app.AUTO_REQUEST_MODEL_CATEGORIES[0]}},
        ]
        material_rows = [
            {
                "record_id": "material-flash-en",
                "fields": {"型号关联": []},
            },
        ]
        language_rows = [
            {"record_id": "language-en", "fields": {"语言种类": "英语(English)"}},
        ]

        def rows(table_name: str) -> list[dict]:
            return {
                app.MODEL_TABLE_NAME: model_rows,
                app.CATEGORY_TABLE_NAME: category_rows,
                app.MATERIAL_TABLE_NAME: material_rows,
                app.LANGUAGE_TABLE_NAME: language_rows,
            }[table_name]

        parsed = {
            "record_id": "material-flash-en",
            "material_code": "MAT-0001",
            "category": app.AUTO_REQUEST_MODEL_CATEGORIES[0],
            "model": "FlashBot",
            "language": "英语(English)",
        }
        with (
            patch.object(app, "fresh_feishu_rows", side_effect=rows),
            patch.object(app, "parse_feishu_inventory_record", return_value=parsed),
            patch.object(app, "next_material_codes_from_records", return_value=["MAT-0002", "MAT-0003"]),
            patch.object(app, "material_language_link_field_name", return_value="语种关联"),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "set_feishu_unit_price"),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update,
            patch.object(app, "feishu_batch_create_records", return_value=[{"record_id": "material-t150-en"}]) as create,
        ):
            result = app.sync_new_request_model_material_rows()

        update.assert_called_once_with(
            app.MATERIAL_TABLE_NAME,
            [{
                "record_id": "material-flash-en",
                "fields": {
                    "型号关联": ["model-flash"],
                    "启用状态": app.STATUS_ACTIVE,
                    app.REQUEST_PAGE_VISIBILITY_FIELD: app.REQUEST_PAGE_VISIBLE_VALUE,
                    app.INVENTORY_ZERO_SINCE_FIELD: 123456,
                },
            }],
        )
        created_fields = create.call_args.args[1]
        self.assertEqual(len(created_fields), 1)
        self.assertEqual(created_fields[0]["产品型号"], "T150")
        self.assertEqual(result, {
            "model_count": 2,
            "created_count": 1,
            "linked_count": 1,
            "models": ["FlashBot", "T150"],
        })

    def test_edit_language_updates_dimension_and_referenced_material_text(self) -> None:
        language_rows = [
            {"record_id": "l1", "fields": {"语言种类": "英语", "启用状态": "启用"}}
        ]
        material_rows = [
            {"record_id": "mat1", "fields": {"语种": "英语", "物料语种": ["l1"]}}
        ]

        def rows(table_name: str) -> list[dict]:
            return language_rows if table_name == app.LANGUAGE_TABLE_NAME else material_rows

        with (
            patch.object(app, "fresh_feishu_rows", side_effect=rows),
            patch.object(app, "feishu_update_record_fields") as update_dimension,
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_material,
        ):
            result = app.execute_dimension_management(
                {
                    "kind": "language", "operation": "edit", "record_id": "l1",
                    "name": "English", "status": "启用",
                }
            )

        update_dimension.assert_called_once_with(
            app.LANGUAGE_TABLE_NAME, "l1", {"语言种类": "English", "启用状态": "启用"}
        )
        update_material.assert_called_once_with(
            app.MATERIAL_TABLE_NAME,
            [{"record_id": "mat1", "fields": {"语种": "English"}}],
        )
        self.assertEqual(result["updated_material_count"], 1)

    def test_delete_referenced_model_cascades_to_material_master_data(self) -> None:
        model_rows = [
            {"record_id": "m1", "fields": {"产品型号编码": "1", "产品型号": "P1", "启用状态": "启用"}}
        ]
        material_rows = [
            {"record_id": "mat1", "fields": {"产品型号": "P1", "型号关联": ["m1"]}}
        ]

        def rows(table_name: str) -> list[dict]:
            return model_rows if table_name == app.MODEL_TABLE_NAME else material_rows

        with (
            patch.object(app, "fresh_feishu_rows", side_effect=rows),
            patch.object(app, "feishu_batch_delete_record_ids", side_effect=[1, 1]) as delete,
        ):
            result = app.execute_dimension_management(
                {"kind": "model", "operation": "delete", "record_id": "m1", "name": "P1"}
            )
        self.assertEqual(
            delete.call_args_list,
            [
                unittest.mock.call(app.MATERIAL_TABLE_NAME, ["mat1"]),
                unittest.mock.call(app.MODEL_TABLE_NAME, ["m1"]),
            ],
        )
        self.assertEqual(result["deleted_material_count"], 1)


if __name__ == "__main__":
    unittest.main()
