import unittest

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


if __name__ == "__main__":
    unittest.main()
