from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import app


class InventoryReviewReminderTests(unittest.TestCase):
    def test_schedule_options_are_anchored_at_ten_am(self) -> None:
        options = app.inventory_review_reminder_schedule_options(
            datetime(2026, 8, 28, 14, 30)
        )

        self.assertEqual(options[0], ("tomorrow", "明天上午10:00", datetime(2026, 8, 29, 10, 0)))
        self.assertEqual(options[-1], ("2months", "2个月后上午10:00", datetime(2026, 10, 27, 10, 0)))

    def test_inventory_card_contains_embedded_reminder_select(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 0,
            },
            "lines": [],
            "result": "",
            "snapshot_at": "2026-08-28 10:00:00",
        }

        card = app.material_request_notification_card(
            "REQ-1", {}, [], review_context=context
        )
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertIn("选择再次核实库存的时间", serialized)
        self.assertIn("save_inventory_reminder__request-1", serialized)
        self.assertNotIn("adjust_inventory_review_time", serialized)

    def test_schedule_update_writes_plan_and_pending_status(self) -> None:
        context = {
            "request": {
                "request_no": "REQ-1",
                "status": app.REQUEST_STATUS_PENDING,
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
            }
        }
        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(app, "feishu_client") as client,
            patch.object(app, "feishu_table_id", return_value="table-1"),
            patch.object(app, "load_feishu_request_records", return_value=[context["request"]]),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_update_record_fields") as update,
        ):
            result = app.execute_inventory_review_reminder_schedule(
                "request-1",
                "ou-admin",
                "1week",
                now=datetime(2026, 8, 28, 14, 30),
            )

        self.assertEqual(result["scheduled_at"], datetime(2026, 9, 4, 10, 0))
        self.assertEqual(
            update.call_args.args[2][app.INVENTORY_REVIEW_REMINDER_STATUS_FIELD],
            app.INVENTORY_REVIEW_REMINDER_PENDING,
        )

    def test_due_reminder_and_weekly_digest_are_enqueued_idempotently(self) -> None:
        due_ms = int(datetime(2026, 8, 28, 9, 0).timestamp() * 1000)
        row = {
            "record_id": "request-1",
            "fields": {
                "申请类型": "普通物料申请",
                "审批状态": app.REQUEST_STATUS_PENDING,
                "库存审查状态": app.INVENTORY_REVIEW_PENDING,
                app.INVENTORY_REVIEW_REMINDER_STATUS_FIELD: app.INVENTORY_REVIEW_REMINDER_PENDING,
                app.INVENTORY_REVIEW_REMINDER_AT_FIELD: due_ms,
            },
        }
        enqueue = Mock(side_effect=[(Mock(), True), (Mock(), True)])
        with (
            patch.object(app, "fresh_feishu_rows", return_value=[row]),
            patch.object(app, "enqueue_feishu_background_write", enqueue),
        ):
            created = app.enqueue_inventory_review_scheduled_tasks(
                datetime(2026, 8, 31, 10, 5)
            )

        self.assertEqual(created, 2)
        self.assertEqual(
            enqueue.call_args_list[0].kwargs["idempotency_key"],
            f"inventory-review-reminder:request-1:{due_ms}",
        )
        self.assertEqual(
            enqueue.call_args_list[1].kwargs["idempotency_key"],
            "weekly-inventory-review:2026-W36",
        )


if __name__ == "__main__":
    unittest.main()
