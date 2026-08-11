from __future__ import annotations

from datetime import datetime
import json
import unittest
from unittest.mock import MagicMock, call, patch

import app


class RestockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.material_row = {
            "record_id": "material-1",
            "fields": {
                "物料编码": "MAT-1",
                "物料品类": "产品折页",
                "产品型号": "BellaBot",
                "语种": "英语",
                "当前库存": 12,
                "启用状态": app.STATUS_ACTIVE,
            },
        }
        self.category_row = {
            "record_id": "category-1",
            "fields": {"物料品类": "产品折页", "启用状态": app.STATUS_ACTIVE},
        }
        self.draft = {
            "restock_no": "RST-20260721-ABC123",
            "operator": "管理员甲",
            "purchase_order_no": "PO-1001",
            "note": "展会备货",
            "submission_token": "abc123",
            "lines": [
                {
                    "product": "产品折页",
                    "model": "BellaBot",
                    "language": "英语",
                    "quantity": 8,
                    "remark": "第一批",
                }
            ],
        }

    def fresh_rows(self, table_name: str) -> list[dict]:
        if table_name == app.MATERIAL_TABLE_NAME:
            return [self.material_row]
        if table_name == app.CATEGORY_TABLE_NAME:
            return [self.category_row]
        return []

    def test_restock_number_is_stable_for_token_and_day(self) -> None:
        occurred_at = datetime(2026, 7, 21, 10, 30)

        value = app.build_restock_no("abc123-extra", occurred_at)

        self.assertEqual(value, "RST-20260721-ABC123")

    def test_submit_restock_increases_inventory_and_writes_ledger(self) -> None:
        client = MagicMock()
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=self.fresh_rows),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_rows,
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "ledger-1"}],
            ) as create_rows,
        ):
            result = app.submit_inventory_restock(self.draft)

        self.assertEqual(result[0]["before_quantity"], 12)
        self.assertEqual(result[0]["after_quantity"], 20)
        update_rows.assert_called_once_with(
            app.MATERIAL_TABLE_NAME,
            [
                {
                    "record_id": "material-1",
                    "fields": {"当前库存": 20, "启用状态": app.STATUS_ACTIVE},
                }
            ],
        )
        ledger_fields = create_rows.call_args.args[1][0]
        self.assertEqual(create_rows.call_args.args[0], app.LEDGER_TABLE_NAME)
        self.assertEqual(ledger_fields["流水类型"], app.ACTION_PURCHASE)
        self.assertEqual(ledger_fields["数量"], 8)
        self.assertEqual(ledger_fields["变更前数量"], 12)
        self.assertEqual(ledger_fields["变更后数量"], 20)
        self.assertEqual(ledger_fields["幂等键"], "restock:abc123:1")
        self.assertIn("补库单 RST-20260721-ABC123", ledger_fields["备注"])
        self.assertIn("采购单号：PO-1001", ledger_fields["备注"])

    def test_restock_rolls_inventory_back_when_ledger_write_fails(self) -> None:
        client = MagicMock()
        update_rows = MagicMock(side_effect=[1, 1])
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=self.fresh_rows),
            patch.object(app, "feishu_batch_update_record_fields", update_rows),
            patch.object(
                app,
                "feishu_batch_create_records",
                side_effect=RuntimeError("ledger failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "ledger failed"):
                app.submit_inventory_restock(self.draft)

        self.assertEqual(update_rows.call_count, 2)
        self.assertEqual(
            update_rows.call_args_list[1],
            call(
                app.MATERIAL_TABLE_NAME,
                [
                    {
                        "record_id": "material-1",
                        "fields": {
                            "当前库存": 12,
                            "启用状态": app.STATUS_ACTIVE,
                        },
                    }
                ],
            ),
        )

    def test_restock_reactivates_inactive_combination(self) -> None:
        client = MagicMock()
        inactive_row = {
            **self.material_row,
            "fields": {**self.material_row["fields"], "启用状态": app.STATUS_INACTIVE},
        }

        def inactive_rows(table_name: str) -> list[dict]:
            if table_name == app.MATERIAL_TABLE_NAME:
                return [inactive_row]
            if table_name == app.CATEGORY_TABLE_NAME:
                return [self.category_row]
            return []

        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=inactive_rows),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_rows,
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "ledger-1"}],
            ),
        ):
            result = app.submit_inventory_restock(self.draft)

        self.assertEqual(result[0]["before_status"], app.STATUS_INACTIVE)
        self.assertEqual(
            update_rows.call_args.args[1][0]["fields"]["启用状态"],
            app.STATUS_ACTIVE,
        )

    def test_restock_card_contains_inventory_changes(self) -> None:
        completed = [
            {
                **self.draft["lines"][0],
                "before_quantity": 12,
                "after_quantity": 20,
            }
        ]

        card = app.material_restock_notification_card(self.draft, completed)

        serialized = json.dumps(card, ensure_ascii=False)
        self.assertEqual(card["header"]["template"], "green")
        for expected in (
            "RST-20260721-ABC123",
            "管理员甲",
            "PO-1001",
            "展会备货",
            "产品折页 / BellaBot / 英语",
            "补库 8，库存 12 → 20",
            "第一批",
        ):
            self.assertIn(expected, serialized)

    def test_restock_notification_goes_to_every_enabled_admin(self) -> None:
        client = MagicMock()
        card = {"header": {"template": "green"}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "material_restock_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_restock(self.draft, [])

        self.assertEqual(count, 2)
        client.send_interactive_message.assert_has_calls(
            [call("ou-a", card), call("ou-b", card)]
        )

    def test_restock_uses_page_cache_and_exposes_category_definition(self) -> None:
        self.category_row["fields"]["品类定义"] = app.CATEGORY_DEFINITION_PRINT

        def cached_rows(table_name: str) -> list[dict]:
            if table_name == app.CATEGORY_TABLE_NAME:
                return [self.category_row]
            if table_name == app.MATERIAL_TABLE_NAME:
                return [self.material_row]
            return []

        with (
            patch.object(app, "safe_feishu_rows", side_effect=cached_rows),
            patch.object(
                app,
                "page_cache_status",
                return_value=("部署静态缓存", "2026-08-11 12:00:00"),
            ),
        ):
            context = app.get_restock_selection_context()

        self.assertEqual(context["cache_source"], "page_data_cache")
        self.assertEqual(context["products"], ["产品折页"])
        self.assertEqual(
            context["category_definition_by_product"],
            {"产品折页": app.CATEGORY_DEFINITION_PRINT},
        )
        self.assertTrue(
            app.selection_context_has_inventory_combination(
                context,
                "产品折页",
                "BellaBot",
                "英语",
            )
        )


if __name__ == "__main__":
    unittest.main()
