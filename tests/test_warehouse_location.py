from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import app


class WarehouseLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shelves = [
            {
                "shelf_code": "H001",
                "ground_location": "进门左侧",
                "description": "中文货架",
                "materials": [],
                "rows": [
                    {
                        "row_code": "W-02",
                        "description": "产品单页",
                        "materials": [
                            {
                                "material_code": "MAT-001",
                                "category": "产品折页",
                                "model": "BellaBot",
                                "language": "简中",
                            }
                        ],
                    }
                ],
            },
            {
                "shelf_code": "G003",
                "ground_location": "右侧靠墙",
                "description": "礼品区",
                "materials": [
                    {
                        "material_code": "MAT-002",
                        "category": "公仔",
                        "model": "CC1 PRO",
                        "language": "无需语种",
                    }
                ],
                "rows": [],
            },
        ]

    def test_search_finds_material_and_only_keeps_matching_row(self) -> None:
        result = app.filter_warehouse_location_shelves(self.shelves, query="BellaBot")

        self.assertEqual([item["shelf_code"] for item in result], ["H001"])
        self.assertEqual([row["row_code"] for row in result[0]["visible_rows"]], ["W-02"])
        self.assertEqual(result[0]["visible_rows"][0]["visible_materials"][0]["material_code"], "MAT-001")

    def test_search_supports_shelf_location_and_explicit_shelf_filter(self) -> None:
        by_location = app.filter_warehouse_location_shelves(self.shelves, query="靠墙")
        by_shelf = app.filter_warehouse_location_shelves(self.shelves, shelf_code="H001")

        self.assertEqual([item["shelf_code"] for item in by_location], ["G003"])
        self.assertEqual([item["shelf_code"] for item in by_shelf], ["H001"])

    def test_published_cache_contains_no_inventory_quantity_fields(self) -> None:
        cache = app.load_warehouse_location_cache()
        serialized = json.dumps(cache, ensure_ascii=False)

        self.assertNotIn("当前库存", serialized)
        self.assertNotIn("库存数量", serialized)
        self.assertNotIn('"quantity"', serialized)
        self.assertGreater(len(cache.get("shelves") or []), 0)

    def test_shelves_with_materials_are_sorted_first(self) -> None:
        shelves = [
            {"shelf_code": "H004", "materials": [], "rows": []},
            {"shelf_code": "H001", "materials": [], "rows": [{"materials": [{"material_code": "A"}]}]},
            {"shelf_code": "G003", "materials": [{"material_code": "B"}, {"material_code": "C"}], "rows": []},
        ]

        result = app.sort_warehouse_location_shelves(shelves)

        self.assertEqual([item["shelf_code"] for item in result], ["G003", "H001", "H004"])
        self.assertEqual(app.warehouse_shelf_material_count(result[0]), 2)

    def test_warehouse_rows_are_labeled_as_levels(self) -> None:
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_ZH):
            self.assertEqual(app.warehouse_row_level_label("W-01"), "最上层")
            self.assertEqual(app.warehouse_row_level_label("MM1-04"), "第 4 层")
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN):
            self.assertEqual(app.warehouse_row_level_label("W-01"), "Top Level")
            self.assertEqual(app.warehouse_row_level_label("M01L-03"), "Level 3")

    def test_warehouse_location_text_has_english_translation(self) -> None:
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN):
            self.assertEqual(
                app.warehouse_display_text("（地面）右侧靠墙（后半）"),
                "Floor area, right wall (rear half)",
            )

    def test_warehouse_anchor_slug_is_stable(self) -> None:
        self.assertEqual(app.warehouse_anchor_slug("H001"), "h001")
        self.assertEqual(app.warehouse_anchor_slug(" M01L-04 "), "m01l-04")


if __name__ == "__main__":
    unittest.main()
