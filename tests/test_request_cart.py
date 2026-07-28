import unittest
from unittest.mock import patch

import app


class RequestCartTests(unittest.TestCase):
    def test_catalog_search_matches_bilingual_product_name(self) -> None:
        products = ["产品单页(Product Flyer)", "冰箱贴(Fridge Magnet)"]

        self.assertEqual(
            app.filter_request_catalog_products(products, "fridge"),
            ["冰箱贴(Fridge Magnet)"],
        )
        self.assertEqual(
            app.filter_request_catalog_products(products, "产品"),
            ["产品单页(Product Flyer)"],
        )

    def test_adding_the_same_material_merges_quantity(self) -> None:
        lines = [
            {
                "product": "冰箱贴(Fridge Magnet)",
                "model": "无型号",
                "language": "英语(English)",
                "quantity": 2,
                "remark": "old",
            }
        ]
        next_line = {
            "product": "冰箱贴(Fridge Magnet)",
            "model": "无型号",
            "language": "英语(English)",
            "quantity": 3,
            "remark": "new",
        }

        updated, merged = app.add_request_material_to_cart(lines, next_line)

        self.assertTrue(merged)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["quantity"], 5)
        self.assertEqual(updated[0]["remark"], "new")
        self.assertEqual(lines[0]["quantity"], 2)

    def test_adding_a_new_material_keeps_existing_lines(self) -> None:
        lines = [
            {
                "product": "冰箱贴(Fridge Magnet)",
                "model": "无型号",
                "language": "英语(English)",
                "quantity": 1,
                "remark": "",
            }
        ]
        next_line = {
            "product": "产品单页(Product Flyer)",
            "model": "P1",
            "language": "英语(English)",
            "quantity": 4,
            "remark": "",
        }

        updated, merged = app.add_request_material_to_cart(lines, next_line)

        self.assertFalse(merged)
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1], next_line)

    def test_multi_select_only_builds_valid_inventory_combinations(self) -> None:
        context = {
            "product_model_languages": {
                ("产品手册", "P1"): ["英语", "日语"],
                ("产品手册", "P2"): ["英语"],
            }
        }

        lines = app.build_request_cart_selection_lines(
            context,
            "产品手册",
            ["P1", "P2"],
            ["英语", "日语"],
            3,
            "展会",
        )

        self.assertEqual(
            [(line["model"], line["language"]) for line in lines],
            [("P1", "英语"), ("P1", "日语"), ("P2", "英语")],
        )
        self.assertTrue(all(line["quantity"] == 3 for line in lines))
        self.assertTrue(all(line["remark"] == "展会" for line in lines))

    def test_enabling_one_multi_select_turns_the_other_off(self) -> None:
        state = {
            "model_multi": True,
            "language_multi": True,
        }

        with patch.object(app.st, "session_state", state):
            app.enforce_request_cart_exclusive_multi_select(
                "model_multi",
                "language_multi",
            )

        self.assertTrue(state["model_multi"])
        self.assertFalse(state["language_multi"])
        self.assertTrue(state["request_form_cache_locked"])


if __name__ == "__main__":
    unittest.main()
