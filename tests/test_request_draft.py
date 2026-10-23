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
    def test_preview_validation_skips_live_schedule_lookup(self) -> None:
        draft = valid_draft()
        draft["scheduling_version"] = 1
        with patch("order_scheduling_service.SchedulingService") as service:
            errors = app.validate_request_draft(
                draft,
                include_live_schedule_validation=False,
            )

        self.assertEqual(errors, [])
        service.assert_not_called()

    def test_request_validation_errors_use_prominent_toast(self) -> None:
        with patch.object(app.st, "toast") as toast:
            app.show_request_validation_toast(["请补充必填信息：申请人", "请至少加入一种申请物料"])

        toast.assert_called_once_with(
            "请补充必填信息：申请人；请至少加入一种申请物料",
            icon="⚠️",
            duration="long",
        )

    def test_english_request_options_show_only_parenthesized_english_name(self) -> None:
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN):
            self.assertEqual(
                app.request_option_display_label("产品单页(Product Flyer)"),
                "Product Flyer",
            )
            self.assertEqual(
                app.request_option_display_label("简中(Simplified Chinese)"),
                "Simplified Chinese",
            )
            self.assertEqual(app.request_option_display_label("BellaBot"), "BellaBot")

    def test_chinese_request_options_keep_original_business_value(self) -> None:
        value = "产品单页(Product Flyer)"
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_ZH):
            self.assertEqual(app.request_option_display_label(value), value)

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

    def test_queued_request_forces_pudu_freight_payer(self) -> None:
        queued = app.queued_material_request_payload(
            {"freight_payer": "申请部门承担"}, []
        )
        self.assertEqual(
            queued["request_payload"]["freight_payer"], app.DEFAULT_FREIGHT_PAYER
        )

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

    def test_draft_accepts_more_than_twenty_materials(self) -> None:
        draft = valid_draft()
        draft["lines"] = [
            {
                "product": f"物料 {index}",
                "model": "型号",
                "language": "英语",
                "quantity": 1,
                "remark": "",
            }
            for index in range(25)
        ]

        errors = app.validate_request_draft(draft)

        self.assertEqual(errors, [])

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
