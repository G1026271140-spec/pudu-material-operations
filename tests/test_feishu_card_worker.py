from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import feishu_card_worker as worker


class FeishuCardWorkerTests(unittest.TestCase):
    def test_request_edit_callback_and_cache_service_are_removed(self) -> None:
        self.assertFalse(hasattr(worker, "handle_card_action"))
        self.assertFalse(hasattr(worker, "REQUEST_CACHE_REFRESH_SECONDS"))
        self.assertFalse(hasattr(worker, "request_cache_refresh_loop"))

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
