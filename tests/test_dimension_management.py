from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class DimensionManagementTests(unittest.TestCase):
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
                {"kind": "model", "operation": "create", "name": "P2", "status": "启用"}
            )

        create.assert_called_once_with(
            app.MODEL_TABLE_NAME,
            [{"产品型号": "P2", "启用状态": "启用", "产品型号编码": "8"}],
        )
        self.assertEqual(result["created_count"], 1)

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
