from __future__ import annotations

import unittest

from scripts import feishu_card_worker as worker


class FeishuCardWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = {
            "request_no": "REQ-TEST-1",
            "customer_name": "Test Customer",
            "country": "US",
            "recipient_info": "John / +1 555 0100",
            "freight_payer": "Sales",
            "material_usage": "Demo",
        }
        self.lines = [
            {
                "record_id": "rec_line_1",
                "product": "产品单页(Product Flyer)",
                "model": "BellaBot",
                "language": "英语(English)",
                "quantity": 2,
                "remark": "Urgent",
            }
        ]

    def test_editor_card_contains_editable_request_form(self) -> None:
        card = worker.editor_card(self.request, self.lines, english=True)

        self.assertEqual(card["schema"], "2.0")
        form = card["body"]["elements"][1]
        self.assertEqual(form["tag"], "form")
        serialized = str(form)
        self.assertIn("qty_0", serialized)
        self.assertIn("remark_0", serialized)
        self.assertIn("save_request", serialized)
        self.assertIn("withdraw_request", serialized)
        self.assertIn("rec_line_1", serialized)

    def test_withdrawal_requires_explicit_confirmation(self) -> None:
        card = worker.confirm_withdraw_card("REQ-TEST-1", english=False)

        serialized = str(card)
        self.assertIn("确认撤回", serialized)
        self.assertIn("confirm_withdraw", serialized)
        self.assertIn("open_request_editor", serialized)


if __name__ == "__main__":
    unittest.main()
