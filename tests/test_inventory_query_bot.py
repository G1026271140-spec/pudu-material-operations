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

    def test_extracts_text_from_text_and_post_content(self) -> None:
        self.assertEqual(
            bot.extract_message_text('{"text":"查库存 产品单页 BellaBot 英语"}'),
            "查库存 产品单页 BellaBot 英语",
        )
        post = {
            "zh_cn": {
                "title": "库存查询",
                "content": [[{"tag": "text", "text": "产品单页 BellaBot 英语 5个"}]],
            }
        }
        self.assertEqual(
            bot.extract_message_text(post),
            "库存查询\n产品单页 BellaBot 英语 5个",
        )
        self.assertTrue(bot.has_inventory_query_intent("产品单页 BellaBot 英语 5个"))
        self.assertTrue(bot.has_inventory_query_intent("查一下这个物料库存"))
        self.assertTrue(bot.has_inventory_query_intent("Bella"))
        self.assertFalse(bot.has_inventory_query_intent("你好，今天怎么样"))
        self.assertTrue(bot.dimension_equal("简中", "简体中文(Simplified Chinese)"))

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

    def test_text_query_supports_natural_quantity_and_inventory_only_lookup(self) -> None:
        queries_with_quantity = bot.parse_inventory_queries(
            ["查库存 产品单页 BellaBot 英语 5个"],
            self.records,
            require_quantity=False,
        )
        queries_without_quantity = bot.parse_inventory_queries(
            ["产品单页 BellaBot 英语库存多少"],
            self.records,
            require_quantity=False,
        )

        self.assertEqual(queries_with_quantity[0].quantity, 5)
        self.assertEqual(queries_without_quantity[0].quantity, 0)
        result = bot.match_inventory_queries(queries_without_quantity, self.records)[0]
        self.assertEqual((result.status, result.available), ("found", 12))

    def test_fuzzy_text_search_matches_partial_terms_and_language_synonym(self) -> None:
        queries = bot.parse_inventory_queries(
            ["查库存 单页 Bella 英文 5个"],
            self.records,
            require_quantity=False,
            allow_fuzzy=True,
        )
        expanded = bot.expand_fuzzy_inventory_queries(queries, self.records)
        results = bot.match_inventory_queries(expanded, self.records)

        self.assertEqual(queries[0].search_text, "单页 Bella 英文")
        self.assertEqual(queries[0].quantity, 5)
        self.assertEqual(expanded[0].language, "英语(English)")
        self.assertEqual((results[0].status, results[0].available), ("available", 12))

    def test_fuzzy_search_tolerates_small_model_typo_and_rejects_noise(self) -> None:
        typo_records = bot.fuzzy_search_inventory("CC1 PR0 英语", self.records)
        noise_records = bot.fuzzy_search_inventory("完全不存在的东西", self.records)

        self.assertEqual(typo_records[0]["model"], "CC1 PRO")
        self.assertEqual(noise_records, [])

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

    def test_card_marks_quantityless_text_query_as_found(self) -> None:
        results = bot.match_inventory_queries(
            [bot.InventoryQuery("产品单页", "BellaBot", "英语", 0)],
            self.records,
        )

        card = bot.inventory_result_card(results)
        row = card["body"]["elements"][1]["rows"][0]

        self.assertEqual(row["requested"], "-")
        self.assertEqual(row["stock"], "12")
        self.assertEqual(row["status"], "已找到")

    def test_card_identifies_fuzzy_results(self) -> None:
        query = bot.InventoryQuery(
            "产品单页(Product Flyer)",
            "BellaBot",
            "英语(English)",
            0,
            "单页 Bella 英文",
        )
        card = bot.inventory_result_card(bot.match_inventory_queries([query], self.records))

        self.assertIn("模糊匹配", card["body"]["elements"][2]["content"])
        self.assertIn("单页 Bella 英文", card["body"]["elements"][2]["content"])


if __name__ == "__main__":
    unittest.main()
