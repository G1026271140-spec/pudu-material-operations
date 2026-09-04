from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import feishu_card_worker as worker


class FeishuCardWorkerTests(unittest.TestCase):
    def test_async_edit_load_updates_original_card_message(self) -> None:
        client = Mock()
        card = {"schema": "2.0"}
        with (
            patch.object(worker.inventory_app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(worker.inventory_app, "request_inventory_card_edit_form", return_value=card),
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
        ):
            worker.process_card_action_async(
                action_key="edit_request_inventory",
                action_name="",
                value={"request_id": "request-1"},
                form_value={},
                operator_open_id="ou-admin",
                message_id="om-card-1",
            )

        client.update_interactive_message.assert_called_once_with("om-card-1", card)

    def test_inventory_edit_button_returns_immediately_and_starts_background_load(self) -> None:
        thread = Mock()
        event = SimpleNamespace(
            action=SimpleNamespace(
                name="",
                value={"action": "edit_request_inventory", "request_id": "request-1"},
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        self.assertEqual(response.toast.type, "success")
        self.assertIn("正在处理", response.toast.content)
        self.assertEqual(thread_class.call_args.kwargs["target"], worker.process_card_action_async)
        self.assertEqual(thread_class.call_args.kwargs["kwargs"]["message_id"], "om-card-1")
        thread.start.assert_called_once_with()

    def test_inline_inventory_edit_form_starts_background_processing(self) -> None:
        task = SimpleNamespace(task_id="abcdef123456")
        thread = Mock()
        form_value = {"model_0": "D7", "language_0": "英语", "change_note": "调整版本"}
        event = SimpleNamespace(
            action=SimpleNamespace(
                name="save_inventory_edit__request-1__2",
                value={},
                form_value=form_value,
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        kwargs = thread_class.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["action_name"], "save_inventory_edit__request-1__2")
        self.assertEqual(kwargs["form_value"], form_value)
        self.assertEqual(response.toast.type, "success")
        thread.start.assert_called_once_with()

    def test_inventory_confirm_callback_returns_before_queue_work(self) -> None:
        thread = Mock()
        event = SimpleNamespace(
            action=SimpleNamespace(
                value={
                    "action": "confirm_request_inventory",
                    "request_id": "request-1",
                    "version": 2,
                }
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        self.assertEqual(
            thread_class.call_args.kwargs["kwargs"]["action_key"],
            "confirm_request_inventory",
        )
        self.assertEqual(response.toast.type, "success")
        thread.start.assert_called_once_with()
        self.assertFalse(hasattr(worker, "REQUEST_CACHE_REFRESH_SECONDS"))
        self.assertFalse(hasattr(worker, "request_cache_refresh_loop"))

    def test_inventory_confirm_callback_accepts_form_button_name_without_value(self) -> None:
        thread = Mock()
        event = SimpleNamespace(
            action=SimpleNamespace(
                name="confirm_request_inventory__request-1__2",
                value={},
                form_value={"ship_date": "2026-09-09"},
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        self.assertEqual(response.toast.type, "success")
        kwargs = thread_class.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["action_key"], "confirm_request_inventory")
        self.assertEqual(kwargs["value"]["request_id"], "request-1")
        self.assertEqual(kwargs["value"]["version"], "2")
        thread.start.assert_called_once_with()

    def test_inventory_confirm_executes_directly_without_queue_write(self) -> None:
        with (
            patch.object(worker.inventory_app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(worker.inventory_app, "execute_request_inventory_confirm") as confirm,
            patch.object(worker.inventory_app, "enqueue_feishu_background_write") as enqueue,
        ):
            worker.process_card_action_async(
                action_key="confirm_request_inventory",
                action_name="",
                value={"request_id": "request-1", "version": 2},
                form_value={},
                operator_open_id="ou-admin",
                message_id="om-card-1",
            )

        confirm.assert_called_once_with(
            {
                "request_id": "request-1",
                "expected_version": 2,
                "operator_open_id": "ou-admin",
            }
        )
        enqueue.assert_not_called()

    def test_inventory_reject_deletes_request_and_updates_card(self) -> None:
        client = Mock()
        result = {"request_no": "REQ-1", "requester": "销售甲", "rejected": True}
        with (
            patch.object(worker.inventory_app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(worker.inventory_app, "execute_request_inventory_reject", return_value=result) as reject,
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
            patch.object(worker.inventory_app, "material_request_rejection_card", return_value={"schema": "2.0"}) as card,
        ):
            worker.process_card_action_async(
                action_key="reject_request_inventory",
                action_name="",
                value={"request_id": "request-1", "request_no": "REQ-1", "version": 2},
                form_value={},
                operator_open_id="ou-admin",
                message_id="om-card-1",
            )

        reject.assert_called_once_with(
            {
                "request_id": "request-1",
                "expected_version": 2,
                "operator_open_id": "ou-admin",
            }
        )
        card.assert_called_once_with("REQ-1", "销售甲")
        client.update_interactive_message.assert_called_once_with("om-card-1", {"schema": "2.0"})

    def test_inventory_reject_callback_is_supported(self) -> None:
        thread = Mock()
        event = SimpleNamespace(
            action=SimpleNamespace(
                value={
                    "action": "reject_request_inventory",
                    "request_id": "request-1",
                    "version": 2,
                }
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        self.assertEqual(response.toast.type, "success")
        self.assertEqual(
            thread_class.call_args.kwargs["kwargs"]["action_key"],
            "reject_request_inventory",
        )
        thread.start.assert_called_once_with()

    def test_reminder_schedule_form_submission_is_accepted(self) -> None:
        thread = Mock()
        event = SimpleNamespace(
            action=SimpleNamespace(
                name="save_inventory_reminder__request-1",
                value={},
                form_value={"reminder_schedule": "2weeks"},
            ),
            operator=SimpleNamespace(open_id="ou-admin"),
            context=SimpleNamespace(open_message_id="om-card-1"),
        )
        with patch.object(worker.threading, "Thread", return_value=thread) as thread_class:
            response = worker.handle_card_action(SimpleNamespace(event=event))

        self.assertEqual(response.toast.type, "success")
        self.assertEqual(
            thread_class.call_args.kwargs["kwargs"]["action_name"],
            "save_inventory_reminder__request-1",
        )
        thread.start.assert_called_once_with()

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
            active_only=False,
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
