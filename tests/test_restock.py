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

    def test_finished_restock_line_keeps_current_entry_values(self) -> None:
        session_state: dict[str, object] = {
            "restock_material_edit_index": 2,
            "restock_line_editor_reset": True,
            "restock_line_category_definition": app.CATEGORY_DEFINITION_PRINT,
            "restock_line_product": "产品单页(Product Flyer)",
            "restock_line_model": "BellaBot",
            "restock_line_language": "英语(English)",
            "restock_line_quantity": 500,
            "restock_line_remark": "同批次补库",
        }

        app.finish_restock_line_entry(session_state)

        self.assertIsNone(session_state["restock_material_edit_index"])
        self.assertNotIn("restock_line_editor_reset", session_state)
        self.assertEqual(
            {
                key: session_state[key]
                for key in (
                    "restock_line_category_definition",
                    "restock_line_product",
                    "restock_line_model",
                    "restock_line_language",
                    "restock_line_quantity",
                    "restock_line_remark",
                )
            },
            {
                "restock_line_category_definition": app.CATEGORY_DEFINITION_PRINT,
                "restock_line_product": "产品单页(Product Flyer)",
                "restock_line_model": "BellaBot",
                "restock_line_language": "英语(English)",
                "restock_line_quantity": 500,
                "restock_line_remark": "同批次补库",
            },
        )

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

    def test_reduce_mode_allows_negative_inventory_and_writes_receive_ledger(self) -> None:
        client = MagicMock()
        draft = {**self.draft, "mode": "reduce"}
        draft["lines"] = [{**self.draft["lines"][0], "quantity": 20}]
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=self.fresh_rows),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_rows,
            patch.object(app, "feishu_batch_create_records", return_value=[{"record_id": "ledger-1"}]) as create_rows,
        ):
            result = app.submit_inventory_restock(draft)

        self.assertEqual(result[0]["before_quantity"], 12)
        self.assertEqual(result[0]["after_quantity"], -8)
        self.assertEqual(update_rows.call_args.args[1][0]["fields"]["当前库存"], -8)
        ledger_fields = create_rows.call_args.args[1][0]
        self.assertEqual(ledger_fields["流水类型"], app.ACTION_RECEIVE)
        self.assertEqual(ledger_fields["变更后数量"], -8)
        self.assertIn("减库单 RST-20260721-ABC123", ledger_fields["备注"])

    def test_reduce_notification_uses_red_header_and_reduce_wording(self) -> None:
        card = app.material_restock_notification_card(
            {**self.draft, "mode": "reduce"},
            [{**self.draft["lines"][0], "before_quantity": 12, "after_quantity": 4}],
        )
        serialized = json.dumps(card, ensure_ascii=False)
        self.assertEqual(card["header"]["template"], "red")
        self.assertIn("减库已完成", serialized)
        self.assertEqual(card["schema"], "2.0")
        detail_table = next(
            element for element in card["body"]["elements"]
            if element.get("tag") == "table"
        )
        self.assertEqual(detail_table["rows"][0]["quantity"], 8)
        self.assertEqual(detail_table["rows"][0]["inventory_change"], "12 → 4")

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
            f"产品折页 / {app.request_model_display_label('BellaBot', language=app.LANGUAGE_ZH)} / 英语",
            "第一批",
        ):
            self.assertIn(expected, serialized)
        detail_table = next(
            element for element in card["body"]["elements"]
            if element.get("tag") == "table"
        )
        self.assertEqual(detail_table["rows"][0]["quantity"], 8)
        self.assertEqual(detail_table["rows"][0]["inventory_change"], "12 → 20")

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

    def test_restock_notification_skips_unavailable_admin(self) -> None:
        client = MagicMock()
        client.send_interactive_message.side_effect = [
            app.FeishuBitableError(
                'Feishu HTTP 400: {"code":230013,"msg":"Bot has NO availability to this user"}'
            ),
            "om-success",
        ]
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(
                app,
                "enabled_admin_open_ids",
                return_value=["ou-unavailable", "ou-ok"],
            ),
        ):
            count = app.notify_enabled_admins_of_restock(self.draft, [])

        self.assertEqual(count, 1)
        self.assertEqual(client.send_interactive_message.call_count, 2)

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

    def test_inventory_records_prefer_linked_category_name(self) -> None:
        material_row = {
            **self.material_row,
            "fields": {
                **self.material_row["fields"],
                "物料品类": "展会服装",
                "品类关联": [{"record_ids": ["category-clothes"]}],
                "产品型号": app.NO_MODEL_TEXT,
                "语种": app.NO_LANGUAGE_TEXT,
            },
        }
        category_row = {
            "record_id": "category-clothes",
            "fields": {
                "物料品类": "展会服装（Clothes）",
                "品类定义": app.CATEGORY_DEFINITION_GIFT,
                "是否无需型号": "是",
                "是否无需语种": "是",
                "启用状态": app.STATUS_INACTIVE,
            },
        }

        records = app.feishu_inventory_records_from_rows(
            [material_row],
            [category_row],
            active_only=False,
        )

        self.assertEqual(records[0]["category"], "展会服装（Clothes）")

    def test_restock_context_includes_default_combination_for_empty_category(self) -> None:
        category_row = {
            "record_id": "category-gift",
            "fields": {
                "物料品类": "定制帽子",
                "品类定义": app.CATEGORY_DEFINITION_GIFT,
                "是否无需型号": "是",
                "是否无需语种": "是",
                "启用状态": app.STATUS_INACTIVE,
            },
        }

        def cached_rows(table_name: str) -> list[dict]:
            if table_name == app.CATEGORY_TABLE_NAME:
                return [category_row]
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

        self.assertEqual(context["products"], ["定制帽子"])
        self.assertEqual(
            app.restock_scoped_models(context, "定制帽子"),
            (True, [app.NO_MODEL_TEXT]),
        )
        self.assertTrue(
            app.selection_context_has_inventory_combination(
                context,
                "定制帽子",
                app.NO_MODEL_TEXT,
                app.NO_LANGUAGE_TEXT,
            )
        )

    def test_restock_scoped_models_handles_only_no_model_inventory_value(self) -> None:
        context = {
            "product_models": {"展会服装": [app.NO_MODEL_TEXT]},
            "no_model_product_keys": set(),
        }

        result = app.restock_scoped_models(context, "展会服装")

        self.assertEqual(result, (True, [app.NO_MODEL_TEXT]))

    def test_restock_creates_missing_default_material_before_purchase(self) -> None:
        category_row = {
            "record_id": "category-hat",
            "fields": {
                "物料品类": "定制帽子",
                "品类定义": app.CATEGORY_DEFINITION_GIFT,
                "是否无需型号": "是",
                "是否无需语种": "是",
                "启用状态": app.STATUS_INACTIVE,
            },
        }
        draft = {
            **self.draft,
            "lines": [
                {
                    "product": "定制帽子",
                    "model": app.NO_MODEL_TEXT,
                    "language": app.NO_LANGUAGE_TEXT,
                    "quantity": 1000,
                    "remark": "首次补库",
                }
            ],
        }

        def fresh_rows(table_name: str) -> list[dict]:
            if table_name == app.CATEGORY_TABLE_NAME:
                return [category_row]
            return []

        def create_rows(table_name: str, rows: list[dict]) -> list[dict]:
            if table_name == app.MATERIAL_TABLE_NAME:
                return [{"record_id": "material-hat"}]
            if table_name == app.LEDGER_TABLE_NAME:
                return [{"record_id": "ledger-hat"}]
            return []

        with (
            patch.object(app, "feishu_client", return_value=MagicMock()),
            patch.object(app, "fresh_feishu_rows", side_effect=fresh_rows),
            patch.object(
                app,
                "ensure_feishu_model_records",
                return_value=("型号关联", {app.NO_MODEL_TEXT: "model-none"}),
            ),
            patch.object(
                app,
                "ensure_feishu_language_records",
                return_value=("语种关联", {app.NO_LANGUAGE_TEXT: "language-none"}),
            ),
            patch.object(app, "set_feishu_unit_price"),
            patch.object(app, "set_feishu_customs_code"),
            patch.object(app, "feishu_batch_create_records", side_effect=create_rows) as create,
            patch.object(
                app,
                "feishu_batch_update_record_fields",
                side_effect=lambda _table, rows: len(rows),
            ) as update,
        ):
            result = app.submit_inventory_restock(draft)

        self.assertEqual(result[0]["material_code"], "MAT-0001")
        self.assertEqual(result[0]["before_quantity"], 0)
        self.assertEqual(result[0]["after_quantity"], 1000)
        material_create = next(
            call_item
            for call_item in create.call_args_list
            if call_item.args[0] == app.MATERIAL_TABLE_NAME
        )
        self.assertEqual(material_create.args[1][0]["品类关联"], ["category-hat"])
        material_update = next(
            call_item
            for call_item in update.call_args_list
            if call_item.args[0] == app.MATERIAL_TABLE_NAME
        )
        self.assertEqual(material_update.args[1][0]["fields"]["当前库存"], 1000)


if __name__ == "__main__":
    unittest.main()
