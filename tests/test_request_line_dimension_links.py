from __future__ import annotations

import unittest
from unittest.mock import patch

import app
from scripts.repair_request_line_dimension_links import build_repairs


class RequestLineDimensionLinkTests(unittest.TestCase):
    def test_link_fields_are_copied_from_material_record(self) -> None:
        table_fields = {
            "品类": {"type": 18},
            "产品型号": {"type": 18},
            "语种": {"type": 18},
            "物料编码": {"type": 21},
        }
        material_row = {
            "record_id": "material-1",
            "fields": {
                "物料编码": "MAT-001",
                "品类关联": [{"id": "category-1"}],
                "型号关联": [{"id": "model-1"}],
                "语种关联": [{"id": "language-1"}],
            },
        }
        fields: dict[str, object] = {}

        with patch.object(app, "feishu_table_fields", return_value=table_fields):
            app.set_request_line_material_fields(
                fields,
                material_row,
                "产品折页",
                "BellaBot",
                "英语",
            )

        self.assertEqual(
            fields,
            {
                "品类": ["category-1"],
                "产品型号": ["model-1"],
                "语种": ["language-1"],
                "物料编码": ["material-1"],
            },
        )

    def test_plain_dimension_fields_keep_display_values(self) -> None:
        table_fields = {
            "物料品类": {"type": 1},
            "产品型号": {"type": 1},
            "语种": {"type": 1},
            "物料编码": {"type": 1},
        }
        fields: dict[str, object] = {}

        with patch.object(app, "feishu_table_fields", return_value=table_fields):
            app.set_request_line_material_fields(
                fields,
                {"record_id": "material-1", "fields": {"物料编码": "MAT-001"}},
                "产品折页",
                "BellaBot",
                "英语",
            )

        self.assertEqual(
            fields,
            {
                "物料品类": "产品折页",
                "产品型号": "BellaBot",
                "语种": "英语",
                "物料编码": "MAT-001",
            },
        )

    def test_historical_repairs_support_raw_api_record_ids(self) -> None:
        materials = [
            {
                "record_id": "material-1",
                "fields": {
                    "品类关联": [{"record_ids": ["category-1"]}],
                    "型号关联": [{"record_ids": ["model-1"]}],
                    "语种关联": [{"record_ids": ["language-1"]}],
                },
            }
        ]
        request_lines = [
            {
                "record_id": "line-1",
                "fields": {"物料编码": [{"record_ids": ["material-1"]}]},
            }
        ]

        repairs, unresolved = build_repairs(materials, request_lines)

        self.assertEqual(unresolved, [])
        self.assertEqual(
            repairs,
            [
                {
                    "record_id": "line-1",
                    "fields": {
                        "品类": ["category-1"],
                        "产品型号": ["model-1"],
                        "语种": ["language-1"],
                    },
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
