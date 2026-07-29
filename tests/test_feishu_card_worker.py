from __future__ import annotations

import unittest
from unittest.mock import patch

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
        self.assertEqual(serialized.count("Product Flyer"), 1)
        self.assertIn("Remark (optional)", serialized)
        compact_columns = worker.input_columns({}, {}, weights=(1, 2))
        self.assertEqual(
            [column["weight"] for column in compact_columns["columns"]],
            [1, 2],
        )

    def test_withdrawal_requires_explicit_confirmation(self) -> None:
        card = worker.confirm_withdraw_card("REQ-TEST-1", english=False)

        serialized = str(card)
        self.assertIn("确认撤回", serialized)
        self.assertIn("confirm_withdraw", serialized)
        self.assertIn("open_request_editor", serialized)

    def test_request_context_uses_warmed_cache_without_live_read(self) -> None:
        cached_request = {
            **self.request,
            "record_id": "rec_request_1",
            "requester_open_id": "ou_requester",
            "status": worker.inventory_app.REQUEST_STATUS_PENDING,
        }
        cached_line = {
            **self.lines[0],
            "request_no": "REQ-TEST-1",
            "status": worker.inventory_app.REQUEST_LINE_STATUS_PENDING,
        }
        with worker.REQUEST_CACHE_LOCK:
            original_cache = dict(worker.REQUEST_CACHE)
            worker.REQUEST_CACHE.clear()
            worker.REQUEST_CACHE.update(
                {"requests": [cached_request], "lines": [cached_line]}
            )
            worker.REQUEST_CACHE_READY.set()
        try:
            with patch.object(
                worker.inventory_app,
                "fetch_request_maintenance_live_data",
                side_effect=AssertionError("live read must not run during callback"),
            ):
                request, lines = worker.request_context(
                    "REQ-TEST-1",
                    "ou_requester",
                )
        finally:
            with worker.REQUEST_CACHE_LOCK:
                worker.REQUEST_CACHE.clear()
                worker.REQUEST_CACHE.update(original_cache)
                if not original_cache.get("requests") and not original_cache.get("lines"):
                    worker.REQUEST_CACHE_READY.clear()

        self.assertEqual(request["request_no"], "REQ-TEST-1")
        self.assertEqual([line["record_id"] for line in lines], ["rec_line_1"])


if __name__ == "__main__":
    unittest.main()
