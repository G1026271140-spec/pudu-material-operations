from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
        self.assertIn("0 = remove", serialized)
        compact_columns = worker.input_columns({}, {}, weights=(1, 2))
        self.assertEqual(
            [column["weight"] for column in compact_columns["columns"]],
            [1, 2],
        )

    def test_cached_request_hides_material_line_removed_by_quantity_zero(self) -> None:
        cached_line = {
            **self.lines[0],
            "request_no": "REQ-TEST-1",
            "status": worker.inventory_app.REQUEST_LINE_STATUS_PENDING,
        }
        with worker.REQUEST_CACHE_LOCK:
            original_cache = {
                "requests": list(worker.REQUEST_CACHE["requests"]),
                "lines": list(worker.REQUEST_CACHE["lines"]),
            }
            worker.REQUEST_CACHE["requests"] = [dict(self.request)]
            worker.REQUEST_CACHE["lines"] = [cached_line]
        try:
            worker.update_cached_request_after_save(
                "REQ-TEST-1",
                {},
                [{"record_id": "rec_line_1", "quantity": 0, "remark": ""}],
            )
            self.assertEqual(
                cached_line["status"],
                worker.inventory_app.REQUEST_LINE_STATUS_WITHDRAWN,
            )
        finally:
            with worker.REQUEST_CACHE_LOCK:
                worker.REQUEST_CACHE.clear()
                worker.REQUEST_CACHE.update(original_cache)

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

    def test_processing_card_explains_background_save(self) -> None:
        card = worker.processing_card(
            "REQ-TEST-1",
            english=False,
            withdrawing=False,
        )

        serialized = str(card)
        self.assertIn("正在保存修改", serialized)
        self.assertIn("完成后机器人会发送通知", serialized)

    def test_background_action_returns_immediately_and_deduplicates(self) -> None:
        started = threading.Event()
        release = threading.Event()
        action_key = "save:REQ-TEST-BACKGROUND"

        def operation() -> None:
            started.set()
            release.wait(timeout=2)

        before = time.perf_counter()
        self.assertTrue(worker.run_background_action(action_key, operation))
        elapsed = time.perf_counter() - before
        self.assertTrue(started.wait(timeout=1))
        self.assertLess(elapsed, 0.2)
        self.assertFalse(worker.run_background_action(action_key, operation))
        release.set()
        for _ in range(20):
            with worker.BACKGROUND_ACTION_LOCK:
                if action_key not in worker.BACKGROUND_ACTIONS:
                    break
            time.sleep(0.01)
        with worker.BACKGROUND_ACTION_LOCK:
            self.assertNotIn(action_key, worker.BACKGROUND_ACTIONS)

    def test_direct_image_message_starts_inventory_query(self) -> None:
        event = SimpleNamespace(
            sender=SimpleNamespace(sender_type="user"),
            message=SimpleNamespace(
                message_id="om-inventory-test",
                message_type="image",
                chat_type="p2p",
                mentions=None,
                content='{"image_key":"img-test"}',
            ),
        )
        data = SimpleNamespace(event=event)
        thread = Mock()
        with worker.INVENTORY_MESSAGE_LOCK:
            worker.INVENTORY_MESSAGE_IDS.discard("om-inventory-test")
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            worker.handle_inventory_message(data)

        thread_class.assert_called_once()
        self.assertEqual(
            thread_class.call_args.kwargs["args"],
            ("om-inventory-test", ["img-test"], []),
        )
        thread.start.assert_called_once_with()

    def test_direct_text_message_starts_inventory_query(self) -> None:
        event = SimpleNamespace(
            sender=SimpleNamespace(sender_type="user"),
            message=SimpleNamespace(
                message_id="om-inventory-text",
                message_type="text",
                chat_type="p2p",
                mentions=None,
                content='{"text":"产品单页 BellaBot 英语库存多少"}',
            ),
        )
        thread = Mock()
        with worker.INVENTORY_MESSAGE_LOCK:
            worker.INVENTORY_MESSAGE_IDS.discard("om-inventory-text")
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            worker.handle_inventory_message(SimpleNamespace(event=event))

        self.assertEqual(
            thread_class.call_args.kwargs["args"],
            ("om-inventory-text", [], ["产品单页 BellaBot 英语库存多少"]),
        )
        thread.start.assert_called_once_with()

    def test_group_image_without_mention_is_ignored(self) -> None:
        event = SimpleNamespace(
            sender=SimpleNamespace(sender_type="user"),
            message=SimpleNamespace(
                message_id="om-group-image",
                message_type="image",
                chat_type="group",
                mentions=[],
                content='{"image_key":"img-test"}',
            ),
        )
        with patch.object(worker.threading, "Thread") as thread_class:
            worker.handle_inventory_message(SimpleNamespace(event=event))

        thread_class.assert_not_called()

    def test_unrelated_direct_text_does_not_start_inventory_query(self) -> None:
        event = SimpleNamespace(
            sender=SimpleNamespace(sender_type="user"),
            message=SimpleNamespace(
                message_id="om-unrelated-text",
                message_type="text",
                chat_type="p2p",
                mentions=None,
                content='{"text":"你好，今天怎么样"}',
            ),
        )
        with patch.object(worker.threading, "Thread") as thread_class:
            worker.handle_inventory_message(SimpleNamespace(event=event))

        thread_class.assert_not_called()

    def test_inventory_message_reads_live_rows_and_replies_with_card(self) -> None:
        client = Mock()
        client.download_message_resource.return_value = b"image"
        client.recognize_image_text.return_value = ["产品单页", "BellaBot", "英语", "2"]
        material_rows = [{"record_id": "material-1", "fields": {}}]
        category_rows = [
            {"record_id": "category-1", "fields": {"物料品类": "产品单页", "启用状态": "启用"}}
        ]
        inventory_records = [
            {
                "category": "产品单页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 10,
            }
        ]
        query = worker.inventory_query_bot.InventoryQuery("产品单页", "BellaBot", "英语", 2)
        result = worker.inventory_query_bot.InventoryQueryResult(query, "available", 10)
        card = {"schema": "2.0"}

        def fresh_rows(table_name: str) -> list[dict]:
            if table_name == worker.inventory_app.MATERIAL_TABLE_NAME:
                return material_rows
            if table_name == worker.inventory_app.CATEGORY_TABLE_NAME:
                return category_rows
            raise AssertionError(table_name)

        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
            patch.object(worker.inventory_app, "fresh_feishu_rows", side_effect=fresh_rows),
            patch.object(
                worker.inventory_app,
                "feishu_inventory_records_from_rows",
                return_value=inventory_records,
            ) as records_from_rows,
            patch.object(
                worker.inventory_query_bot,
                "parse_inventory_queries",
                return_value=[query],
            ),
            patch.object(
                worker.inventory_query_bot,
                "match_inventory_queries",
                return_value=[result],
            ),
            patch.object(worker.inventory_query_bot, "inventory_result_card", return_value=card),
        ):
            worker.process_inventory_message("om-live", ["img-live"])

        records_from_rows.assert_called_once_with(
            material_rows,
            category_rows,
            active_only=True,
        )
        client.reply_interactive_message.assert_called_once_with(
            "om-live",
            card,
            idempotency_key="inventory-result:om-live",
        )

    def test_unrelated_text_message_is_silently_ignored(self) -> None:
        client = Mock()
        category_rows = [
            {"record_id": "category-1", "fields": {"物料品类": "产品单页", "启用状态": "启用"}}
        ]

        def fresh_rows(table_name: str) -> list[dict]:
            return category_rows if table_name == worker.inventory_app.CATEGORY_TABLE_NAME else []

        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
            patch.object(worker.inventory_app, "fresh_feishu_rows", side_effect=fresh_rows),
        ):
            worker.process_inventory_message("om-chat", [], ["你好"])

        client.reply_text_message.assert_not_called()
        client.reply_interactive_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
