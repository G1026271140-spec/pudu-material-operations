from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class ModelDimensionLinkTests(unittest.TestCase):
    def test_existing_model_record_is_reused(self) -> None:
        with (
            patch.object(
                app,
                "feishu_table_fields",
                return_value={"产品型号 2": {"type": 21}},
            ),
            patch.object(
                app,
                "feishu_schema",
                return_value={"tables": {app.MODEL_TABLE_NAME: {"table_id": "models"}}},
            ),
            patch.object(
                app,
                "fresh_feishu_rows",
                return_value=[
                    {
                        "record_id": "model-1",
                        "fields": {"产品型号编码": "22", "产品型号": "BG1"},
                    }
                ],
            ),
            patch.object(app, "feishu_batch_create_records") as create_records,
        ):
            link_field, model_ids = app.ensure_feishu_model_records(["BG1"])

        self.assertEqual(link_field, "产品型号 2")
        self.assertEqual(model_ids, {"BG1": "model-1"})
        create_records.assert_not_called()

    def test_missing_model_record_is_created_with_next_code(self) -> None:
        with (
            patch.object(
                app,
                "feishu_table_fields",
                return_value={"产品型号 2": {"type": 21}},
            ),
            patch.object(
                app,
                "feishu_schema",
                return_value={"tables": {app.MODEL_TABLE_NAME: {"table_id": "models"}}},
            ),
            patch.object(
                app,
                "fresh_feishu_rows",
                return_value=[
                    {
                        "record_id": "model-1",
                        "fields": {"产品型号编码": "22", "产品型号": "BG1"},
                    }
                ],
            ),
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "model-2"}],
            ) as create_records,
        ):
            link_field, model_ids = app.ensure_feishu_model_records(["New Model"])

        self.assertEqual(link_field, "产品型号 2")
        self.assertEqual(model_ids, {"New Model": "model-2"})
        create_records.assert_called_once_with(
            app.MODEL_TABLE_NAME,
            [
                {
                    "产品型号编码": "23",
                    "产品型号": "New Model",
                    "启用状态": app.STATUS_ACTIVE,
                }
            ],
        )

    def test_model_link_is_added_to_material_fields(self) -> None:
        fields: dict[str, object] = {"产品型号": "BG1"}

        app.add_material_model_link(
            fields,
            "BG1",
            "产品型号 2",
            {"BG1": "model-1"},
        )

        self.assertEqual(fields["产品型号 2"], ["model-1"])

    def test_existing_language_record_is_reused(self) -> None:
        with (
            patch.object(
                app,
                "feishu_table_fields",
                return_value={"语种关联": {"type": 21}},
            ),
            patch.object(
                app,
                "feishu_schema",
                return_value={"tables": {app.LANGUAGE_TABLE_NAME: {"table_id": "languages"}}},
            ),
            patch.object(
                app,
                "fresh_feishu_rows",
                return_value=[
                    {
                        "record_id": "language-1",
                        "fields": {"语言种类": "英语(English)", "启用状态": app.STATUS_ACTIVE},
                    }
                ],
            ),
            patch.object(app, "feishu_batch_create_records") as create_records,
        ):
            link_field, language_ids = app.ensure_feishu_language_records(["英语(English)"])

        self.assertEqual(link_field, "语种关联")
        self.assertEqual(language_ids, {"英语(English)": "language-1"})
        create_records.assert_not_called()

    def test_missing_language_record_is_created(self) -> None:
        with (
            patch.object(
                app,
                "feishu_table_fields",
                return_value={"语种关联": {"type": 21}},
            ),
            patch.object(
                app,
                "feishu_schema",
                return_value={"tables": {app.LANGUAGE_TABLE_NAME: {"table_id": "languages"}}},
            ),
            patch.object(app, "fresh_feishu_rows", return_value=[]),
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "language-2"}],
            ) as create_records,
        ):
            link_field, language_ids = app.ensure_feishu_language_records(["无需语种"])

        self.assertEqual(link_field, "语种关联")
        self.assertEqual(language_ids, {"无需语种": "language-2"})
        create_records.assert_called_once_with(
            app.LANGUAGE_TABLE_NAME,
            [
                {
                    "语言种类": "无需语种",
                    "启用状态": app.STATUS_ACTIVE,
                }
            ],
        )

    def test_language_link_is_added_to_material_fields(self) -> None:
        fields: dict[str, object] = {"语种": "英语(English)"}

        app.add_material_language_link(
            fields,
            "英语(English)",
            "语种关联",
            {"英语(English)": "language-1"},
        )

        self.assertEqual(fields["语种关联"], ["language-1"])


if __name__ == "__main__":
    unittest.main()
