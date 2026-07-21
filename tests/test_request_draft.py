import unittest
from unittest.mock import patch

import pandas as pd

import app


def valid_draft() -> dict[str, object]:
    return {
        "department": "市场部",
        "requester": "申请人",
        "customer_name": "客户",
        "country": "国家",
        "recipient_info": "收件信息",
        "freight_payer": "申请部门承担",
        "material_usage": "展会使用",
        "attachments": [],
        "lines": [
            {
                "product": "物料",
                "model": "型号",
                "language": "英语",
                "quantity": 2,
                "remark": "",
            }
        ],
    }


class RequestDraftTests(unittest.TestCase):
    def test_freight_payer_options_include_pudu(self) -> None:
        self.assertIn("普渡付款(PUDU)", app.FREIGHT_PAYER_OPTIONS)
        self.assertEqual(app.DEFAULT_FREIGHT_PAYER, "普渡付款(PUDU)")

    def test_new_request_defaults_to_pudu_freight_payer(self) -> None:
        session_state: dict[str, object] = {}
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app, "get_secret_value", side_effect=lambda _name, default="": default),
        ):
            app.initialize_request_form_state()

        self.assertEqual(session_state["request_freight_payer"], "普渡付款(PUDU)")

    def test_product_line_manuals_are_displayed_together(self) -> None:
        products = app.sort_request_products(
            [
                "产品单页(Product Flyer)",
                "工业产品线手册IR(Industrial Product Line Brochure)",
                "清洁产品线手册CR(Cleaning Product Line Brochure)",
                "产品易拉宝(Product Roll-Up)",
                "配送线产品手册DR(Delivery Robot Product Brochure)",
                "具身线产品手册ER(Embodied AI Robot Product Brochure)",
            ]
        )

        self.assertEqual(
            products[1:5],
            [
                "工业产品线手册IR(Industrial Product Line Brochure)",
                "清洁产品线手册CR(Cleaning Product Line Brochure)",
                "配送线产品手册DR(Delivery Robot Product Brochure)",
                "具身线产品手册ER(Embodied AI Robot Product Brochure)",
            ],
        )

    def test_valid_draft_passes_without_errors(self) -> None:
        self.assertEqual(app.validate_request_draft(valid_draft()), [])

    def test_draft_requires_business_fields_and_materials(self) -> None:
        draft = valid_draft()
        draft["requester"] = ""
        draft["country"] = ""
        draft["lines"] = []

        errors = app.validate_request_draft(draft)

        self.assertTrue(any("申请人" in error and "国家" in error for error in errors))
        self.assertTrue(any("至少加入一种" in error for error in errors))

    def test_draft_rejects_more_than_twenty_materials(self) -> None:
        draft = valid_draft()
        draft["lines"] = [
            {
                "product": f"物料 {index}",
                "model": "型号",
                "language": "英语",
                "quantity": 1,
                "remark": "",
            }
            for index in range(app.MAX_REQUEST_LINE_COUNT + 1)
        ]

        errors = app.validate_request_draft(draft)

        self.assertTrue(any("最多可添加 20 种" in error for error in errors))

    def test_attachment_merge_keeps_latest_file_with_same_name(self) -> None:
        merged = app.merge_request_attachments(
            [{"name": "address.xlsx", "content": b"old", "content_type": "old/type"}],
            [{"name": "address.xlsx", "content": b"new", "content_type": "new/type"}],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["content"], b"new")
        self.assertEqual(merged[0]["content_type"], "new/type")

    def test_material_table_updates_quantity_remark_and_selection(self) -> None:
        lines = [
            {
                "product": "物料",
                "model": "型号",
                "language": "英语",
                "quantity": 2,
                "remark": "",
            }
        ]
        edited = pd.DataFrame(
            [
                {
                    "选择": True,
                    "序号": 1,
                    "物料品类": "物料",
                    "产品型号": "型号",
                    "语种": "英语",
                    "数量": 8,
                    "备注": "优先发放",
                }
            ]
        )

        updated, selected = app.apply_request_material_table_edits(lines, edited)

        self.assertEqual(updated[0]["quantity"], 8)
        self.assertEqual(updated[0]["remark"], "优先发放")
        self.assertEqual(selected, [0])


if __name__ == "__main__":
    unittest.main()
