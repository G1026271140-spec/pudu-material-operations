import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import app


def material_row(
    record_id: str,
    quantity: int,
    status: str = app.STATUS_ACTIVE,
    zero_since: str = "",
) -> dict:
    return {
        "record_id": record_id,
        "fields": {
            "物料编码": f"MAT-{record_id}",
            "物料品类": f"品类-{record_id}",
            "产品型号": "M1",
            "语种": "英语",
            "当前库存": quantity,
            "启用状态": status,
            app.INVENTORY_ZERO_SINCE_FIELD: zero_since,
        },
    }


def ledger_row(
    record_id: str,
    occurred_at: datetime,
    *,
    status: str = "有效",
    delta: int = -1,
) -> dict:
    return {
        "record_id": f"ledger-{record_id}",
        "fields": {
            "发生时间": app.feishu_timestamp(occurred_at),
            "操作状态": status,
            "物料编码": [{"record_ids": [record_id]}],
            "物料品类": f"品类-{record_id}",
            "产品型号": "M1",
            "语种": "英语",
            "变更前数量": 1,
            "变更后数量": 1 + delta,
            "库存变化": delta,
        },
    }


class InventoryStatusMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 21, 10, 30, 0)

    def test_plan_enables_nonzero_and_disables_only_expired_zero_rows(self) -> None:
        materials = [
            material_row("nonzero", 5, app.STATUS_INACTIVE, "2026-06-01 00:00:00"),
            material_row("expired", 0),
            material_row("recent", 0, zero_since="2026-07-10 10:30:01"),
            material_row("new-zero", 0),
            material_row("already-inactive", 0, app.STATUS_INACTIVE, "2026-06-01 00:00:00"),
        ]
        ledgers = [
            ledger_row("expired", self.now - timedelta(days=15)),
            ledger_row("expired", self.now - timedelta(days=20), status="已撤回"),
        ]

        plan = app.plan_inventory_status_maintenance(materials, ledgers, now=self.now)
        updates = {item["record_id"]: item["fields"] for item in plan["updates"]}

        self.assertEqual(updates["nonzero"]["启用状态"], app.STATUS_ACTIVE)
        self.assertEqual(updates["nonzero"][app.INVENTORY_ZERO_SINCE_FIELD], "")
        self.assertEqual(updates["expired"]["启用状态"], app.STATUS_INACTIVE)
        self.assertEqual(updates["expired"][app.INVENTORY_ZERO_SINCE_FIELD], "2026-07-06 10:30:00")
        self.assertNotIn("recent", updates)
        self.assertEqual(
            updates["new-zero"][app.INVENTORY_ZERO_SINCE_FIELD],
            "2026-07-21 10:30:00",
        )
        self.assertNotIn("already-inactive", updates)
        self.assertEqual([row["record_id"] for row in plan["enabled_rows"]], ["nonzero"])
        self.assertEqual([row["record_id"] for row in plan["disabled_rows"]], ["expired"])
        self.assertEqual(plan["initialized_zero_rows"], 1)

    def test_latest_valid_quantity_change_restarts_zero_timer(self) -> None:
        materials = [material_row("target", 0, zero_since="2026-06-01 00:00:00")]
        ledgers = [
            ledger_row("target", self.now - timedelta(days=20)),
            ledger_row("target", self.now - timedelta(days=2)),
        ]

        plan = app.plan_inventory_status_maintenance(materials, ledgers, now=self.now)

        self.assertEqual(plan["disabled_rows"], [])
        self.assertEqual(
            plan["updates"],
            [
                {
                    "record_id": "target",
                    "fields": {app.INVENTORY_ZERO_SINCE_FIELD: "2026-07-19 10:30:00"},
                }
            ],
        )

    def test_exactly_fourteen_days_is_not_yet_disabled(self) -> None:
        materials = [material_row("boundary", 0)]
        ledgers = [ledger_row("boundary", self.now - timedelta(days=14))]

        plan = app.plan_inventory_status_maintenance(materials, ledgers, now=self.now)

        self.assertEqual(plan["disabled_rows"], [])

    def test_executor_updates_then_notifies_administrators(self) -> None:
        disabled = app.inventory_status_row_summary(
            material_row("expired", 0),
            zero_since=self.now - timedelta(days=15),
        )
        plan = {
            "checked_at": "2026-07-21 10:30:00",
            "updates": [{"record_id": "expired", "fields": {"启用状态": app.STATUS_INACTIVE}}],
            "enabled_rows": [],
            "disabled_rows": [disabled],
            "initialized_zero_rows": 0,
            "material_count": 1,
            "ledger_count": 1,
        }
        with (
            patch.object(app, "ensure_inventory_zero_since_field", return_value=False),
            patch.object(app, "fresh_feishu_rows", side_effect=[[material_row("expired", 0)], [], []]),
            patch.object(app, "plan_inventory_status_maintenance", return_value=plan),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update,
            patch.object(
                app,
                "notify_enabled_admins_of_inventory_auto_disable",
                return_value=2,
            ) as notify,
        ):
            result = app.maintain_inventory_status(now=self.now)

        update.assert_called_once_with(app.MATERIAL_TABLE_NAME, plan["updates"])
        notify.assert_called_once_with([disabled], "2026-07-21 10:30:00")
        self.assertEqual(result["disabled_count"], 1)
        self.assertEqual(result["notification_count"], 2)

    def test_notification_failure_rolls_newly_disabled_rows_back(self) -> None:
        disabled = {"record_id": "expired"}
        plan = {
            "checked_at": "2026-07-21 10:30:00",
            "updates": [{"record_id": "expired", "fields": {"启用状态": app.STATUS_INACTIVE}}],
            "enabled_rows": [],
            "disabled_rows": [disabled],
            "initialized_zero_rows": 0,
            "material_count": 1,
            "ledger_count": 0,
        }
        update = Mock(side_effect=[1, 1])
        with (
            patch.object(app, "ensure_inventory_zero_since_field", return_value=False),
            patch.object(app, "fresh_feishu_rows", side_effect=[[material_row("expired", 0)], [], []]),
            patch.object(app, "plan_inventory_status_maintenance", return_value=plan),
            patch.object(app, "feishu_batch_update_record_fields", update),
            patch.object(
                app,
                "notify_enabled_admins_of_inventory_auto_disable",
                side_effect=RuntimeError("send failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "已恢复 1/1 条记录"):
                app.maintain_inventory_status(now=self.now)

        self.assertEqual(update.call_count, 2)
        self.assertEqual(
            update.call_args_list[1].args,
            (
                app.MATERIAL_TABLE_NAME,
                [{"record_id": "expired", "fields": {"启用状态": app.STATUS_ACTIVE}}],
            ),
        )

    def test_notification_card_contains_rule_and_material_details(self) -> None:
        row = {
            "material_code": "MAT-001",
            "product": "产品折页",
            "model": "BellaBot",
            "language": "英语",
            "zero_since": "2026-07-01 10:30:00",
        }

        card = app.inventory_auto_disable_notification_card([row], "2026-07-21 10:30:00")
        serialized = str(card)

        self.assertEqual(card["header"]["template"], "red")
        self.assertIn("超过 14 天", serialized)
        self.assertIn("MAT-001", serialized)
        self.assertIn("BellaBot", serialized)

    def test_notification_is_sent_to_every_enabled_administrator(self) -> None:
        client = Mock()
        card = {"header": {"template": "red"}}
        rows = [{"record_id": "expired"}]
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "inventory_auto_disable_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_inventory_auto_disable(
                rows,
                "2026-07-21 10:30:00",
            )

        self.assertEqual(count, 2)
        self.assertEqual(client.send_interactive_message.call_count, 2)
        client.send_interactive_message.assert_any_call("ou-a", card)
        client.send_interactive_message.assert_any_call("ou-b", card)


if __name__ == "__main__":
    unittest.main()
