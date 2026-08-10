from __future__ import annotations

import unittest

from scripts import inventory_query_bot as bot


class InventoryQueryBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            {
                "material_code": "M-001",
                "category": "产品单页(Product Flyer)",
                "model": "BellaBot",
                "language": "英语(English)",
                "quantity": 12,
            },
            {
                "material_code": "M-002",
                "category": "产品单页(Product Flyer)",
                "model": "BellaBot",
                "language": "法语(French)",
                "quantity": 2,
            },
            {
                "material_code": "M-003",
                "category": "产品折页",
                "model": "CC1 PRO",
                "language": "英语(English)",
                "quantity": 8,
            },
        ]

    def test_extracts_image_keys_from_image_and_post_content(self) -> None:
        content = {
            "image_key": "img-main",
            "content": [[{"tag": "img", "image_key": "img-post"}]],
        }

        self.assertEqual(bot.extract_image_keys(content), ["img-main", "img-post"])
        self.assertEqual(
            bot.extract_image_keys('{"image_key":"img-json"}'),
            ["img-json"],
        )

    def test_parses_ocr_table_cells_using_live_catalog_names(self) -> None:
        queries = bot.parse_inventory_queries(
            [
                "物料品类",
                "产品型号",
                "语种",
                "数量",
                "产品单页",
                "BellaBot",
                "英语",
                "5",
                "产品折页",
                "CC1 PRO",
                "法语",
                "10",
            ],
            self.records,
        )

        self.assertEqual(
            queries,
            [
                bot.InventoryQuery(
                    "产品单页(Product Flyer)",
                    "BellaBot",
                    "英语(English)",
                    5,
                ),
                bot.InventoryQuery("产品折页", "CC1 PRO", "法语(French)", 10),
            ],
        )

    def test_labelled_line_preserves_unknown_combination(self) -> None:
        queries = bot.parse_inventory_queries(
            ["品类：产品单页 型号：BellaBot 语种：德语 数量：3"],
            self.records,
        )

        self.assertEqual(
            queries,
            [
                bot.InventoryQuery(
                    "产品单页(Product Flyer)",
                    "BellaBot",
                    "德语",
                    3,
                )
            ],
        )

    def test_matches_available_insufficient_and_missing_with_similar_items(self) -> None:
        queries = [
            bot.InventoryQuery("产品单页", "BellaBot", "英语", 5),
            bot.InventoryQuery("产品折页", "CC1 PRO", "英语", 10),
            bot.InventoryQuery("产品单页", "BellaBot", "德语", 3),
        ]

        results = bot.match_inventory_queries(queries, self.records)

        self.assertEqual(
            [(result.status, result.available) for result in results],
            [("available", 12), ("insufficient", 8), ("missing", 0)],
        )
        self.assertEqual(results[2].similar[0]["category"], "产品单页(Product Flyer)")
        self.assertEqual(results[2].similar[0]["model"], "BellaBot")

    def test_card_uses_card_2_table_and_similar_note(self) -> None:
        results = bot.match_inventory_queries(
            [
                bot.InventoryQuery("产品单页", "BellaBot", "英语", 5),
                bot.InventoryQuery("产品单页", "BellaBot", "德语", 3),
            ],
            self.records,
        )

        card = bot.inventory_result_card(results)

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["config"]["width_mode"], "fill")
        self.assertEqual(card["header"]["template"], "blue")
        table = card["body"]["elements"][1]
        self.assertEqual(table["tag"], "table")
        self.assertEqual(len(table["rows"]), 2)
        self.assertEqual(table["rows"][0]["status"], "库存充足")
        self.assertEqual(table["rows"][1]["status"], "无此组合")
        self.assertIn("相似库存组合", card["body"]["elements"][2]["content"])


if __name__ == "__main__":
    unittest.main()
