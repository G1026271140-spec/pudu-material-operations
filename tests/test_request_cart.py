import unittest
from unittest.mock import patch

import app


class RequestCartTests(unittest.TestCase):
    def test_category_images_match_chinese_and_english_names(self) -> None:
        chinese_path = app.request_category_image_path("产品单页(Product Flyer)")
        english_path = app.request_category_image_path("Delivery Robot Product Brochure")

        self.assertIsNotNone(chinese_path)
        self.assertEqual(chinese_path.name, "product-flyer.webp")
        self.assertTrue(chinese_path.exists())
        self.assertIsNotNone(english_path)
        self.assertEqual(english_path.name, "delivery-brochure.webp")
        fridge_path = app.request_category_image_path("冰箱贴(Fridge Magnet)")
        self.assertIsNotNone(fridge_path)
        self.assertEqual(fridge_path.name, "fridge-magnet.webp")

    def test_category_without_image_uses_placeholder_path(self) -> None:
        self.assertIsNone(app.request_category_image_path("定制LOGO书包(Customized PUDU bag)"))

    def test_all_uploaded_category_images_match_current_category_names(self) -> None:
        expected_images = {
            "产品单页(Product Flyer )": "product-flyer.webp",
            "品牌手册(Product Brochure (All Banner)）": "brand-brochure.webp",
            "工业产品线手册IR(Industrial Product Line Brochure）": "industrial-brochure.webp",
            "清洁产品线手册CR(Cleaning Product Line Brochure）": "cleaning-brochure.webp",
            "配送线产品手册DR(Delivery Robot Product Brochure)": "delivery-brochure.webp",
            "具身线产品手册ER(Embodied AI Robot Product Brochure)": "embodied-brochure.webp",
            "产品易拉宝(Product Roll-Up)": "product-roll-up.webp",
            "公仔(Plush Toy)": "plush-toy.webp",
            "冰箱贴( Fridge Magnet)": "fridge-magnet.webp",
            "笔记本礼盒(Notebook Gift Box)": "notebook-gift-box.webp",
            "普渡logo无纺布手提袋(PUDU logo bag)": "pudu-logo-bag.webp",
            "扇子": "fan.webp",
        }

        for product, expected_name in expected_images.items():
            with self.subTest(product=product):
                image_path = app.request_category_image_path(product)
                self.assertIsNotNone(image_path)
                self.assertEqual(image_path.name, expected_name)
                self.assertTrue(image_path.exists())

    def test_chinese_category_label_hides_bilingual_suffix(self) -> None:
        with patch.object(app.st, "session_state", {app.UI_LANGUAGE_SESSION_KEY: app.LANGUAGE_ZH}):
            self.assertEqual(
                app.request_category_display_label(
                    "工业产品线手册IR(Industrial Product Line Brochure）"
                ),
                "工业产品线手册IR",
            )

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

    def test_successful_cart_addition_shows_right_side_toast_once(self) -> None:
        state = {
            "request_cart_added_toast": True,
            app.UI_LANGUAGE_SESSION_KEY: app.LANGUAGE_ZH,
        }
        with (
            patch.object(app.st, "session_state", state),
            patch.object(app.st, "toast") as toast,
        ):
            app.render_request_cart_added_toast()
            app.render_request_cart_added_toast()

        toast.assert_called_once_with("已加入购物车", icon="🛒", duration="short")
        self.assertNotIn("request_cart_added_toast", state)


if __name__ == "__main__":
    unittest.main()
