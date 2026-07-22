from __future__ import annotations

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
