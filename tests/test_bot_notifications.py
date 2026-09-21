from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import Mock, patch

import app
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


def elements_with_tag(value: object, tag: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    if isinstance(value, dict):
        if value.get("tag") == tag:
            matches.append(value)
        for child in value.values():
            matches.extend(elements_with_tag(child, tag))
    elif isinstance(value, list):
        for child in value:
            matches.extend(elements_with_tag(child, tag))
    return matches


class BotNotificationTests(unittest.TestCase):
    def test_notification_tables_do_not_use_automatic_column_width(self) -> None:
        self.assertNotIn('"width": "auto"', inspect.getsource(app))

    def test_all_material_detail_notification_cards_use_tables(self) -> None:
        material_line = {
            "product": "产品单页",
            "model": "T300",
            "language": "英语",
            "quantity": 2,
        }
        cards = [
            app.material_restock_notification_card(
                {"mode": "restock", "restock_no": "RST-1", "operator": "管理员"},
                [{**material_line, "before_quantity": 1, "after_quantity": 3}],
            ),
            app.approval_writeback_notification_card(
                "REQ-1",
                "APPROVAL-1",
                [{**material_line, "actual_issue_qty": 2, "status": "已发放", "current_stock": 8}],
                succeeded=True,
            ),
            app.dimension_management_notification_card(
                {
                    "kind": "model",
                    "operation": "edit",
                    "name": "T300",
                    "changes": [{
                        "action": "update",
                        "material_code": "MAT-1",
                        "category": "产品单页",
                        "model": "T300",
                        "language": "英语",
                        "quantity": 8,
                        "status": app.STATUS_ACTIVE,
                        "request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
                    }],
                },
                {},
            ),
            app.category_create_notification_card(
                {"product": "产品单页"},
                {"targets": [{**material_line, "unit_price": 1, "status": app.STATUS_ACTIVE}]},
            ),
            app.category_delete_notification_card(
                {"records": [{**material_line, "material_code": "MAT-1", "category": "产品单页"}]}
            ),
            app.inventory_auto_disable_notification_card(
                [{**material_line, "material_code": "MAT-1", "zero_since": "2026-09-01"}],
                "2026-09-20",
            ),
            app._cultural_request_card(
                "CUL-1", "申请人", [{"product": "夹克", "model": "XL", "region": "中国", "quantity": 1}], applicant=True
            ),
            app.cultural_management_notification_card("edit", "夹克", "XL", "中国"),
        ]

        for card in cards:
            card = app._feishu_normalize_card_tables(card)
            with self.subTest(title=card["header"]["title"]["content"]):
                self.assertEqual(card["schema"], "2.0")
                tables = elements_with_tag(card, "table")
                self.assertGreaterEqual(len(tables), 1)
                self.assertGreaterEqual(len(tables[0]["rows"]), 1)
                for table in tables:
                    self.assertTrue(
                        all(column.get("width") != "auto" for column in table["columns"])
                    )
                    expected_names = [f"c{index}" for index in range(len(table["columns"]))]
                    self.assertEqual(
                        [column["name"] for column in table["columns"]],
                        expected_names,
                    )
                    self.assertTrue(
                        all(set(row).issubset(expected_names) for row in table["rows"])
                    )

    def test_category_edit_card_is_wide_and_contains_change_details(self) -> None:
        draft = {
            "old_product": "旧冰箱贴",
            "product": "新冰箱贴",
            "edited_at": "2026-07-22 10:00:00",
            "category_status": app.STATUS_ACTIVE,
            "category_request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
            "old_category_zh_page_name": "旧中文名",
            "category_zh_page_name": "新中文名",
            "old_category_en_page_name": "Old English Name",
            "category_en_page_name": "New English Name",
            "current_records": [{
                "model": "BellaBot", "language": "英语", "quantity": 10,
                "unit_price": 1.5, "customs_code": "A1", "status": app.STATUS_ACTIVE,
                "request_visible": app.REQUEST_PAGE_HIDDEN_VALUE,
            }],
            "targets": [{
                "model": "BellaBot", "language": "英语", "quantity": 15,
                "unit_price": 2, "customs_code": "A2", "status": app.STATUS_INACTIVE,
                "request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
            }],
        }
        result = {
            "target_count": 1, "created_count": 0, "deleted_count": 0,
            "quantity_difference": 5,
        }

        card = app.category_edit_notification_card(draft, result)
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["config"]["width_mode"], "fill")
        self.assertEqual(card["header"]["template"], "blue")
        for expected in (
            "旧冰箱贴",
            "新冰箱贴",
            "BellaBot / 英语",
            "10 → 15",
            "1.5 → 2",
            "否 → 是",
            "中文页面名称：旧中文名 → 新中文名",
            "英文页面名称：Old English Name → New English Name",
        ):
            self.assertIn(expected, serialized)

    def test_category_edit_change_rows_marks_unchanged_fields_and_keeps_unchanged_rows_filterable(self) -> None:
        draft = {
            "current_records": [
                {"model": "BG1", "language": "英语", "quantity": 10, "unit_price": 1.5,
                 "customs_code": "A1", "status": app.STATUS_ACTIVE},
                {"model": "BG1", "language": "日语", "quantity": 0, "unit_price": 1.5,
                 "customs_code": "A1", "status": app.STATUS_ACTIVE},
            ],
            "targets": [
                {"model": "BG1", "language": "英语", "quantity": 20, "unit_price": 1.5,
                 "customs_code": "A1", "status": app.STATUS_ACTIVE},
                {"model": "BG1", "language": "日语", "quantity": 0, "unit_price": 1.5,
                 "customs_code": "A1", "status": app.STATUS_ACTIVE},
            ],
        }

        rows = app.category_edit_change_rows(draft)
        changed_rows = [row for row in rows if row["操作"] != "保留"]

        self.assertEqual(len(changed_rows), 1)
        self.assertEqual(changed_rows[0]["库存变化"], "10 → 20")
        self.assertEqual(changed_rows[0]["单价变化"], "—")
        self.assertEqual(changed_rows[0]["状态变化"], "—")
        self.assertEqual(changed_rows[0]["海关编码变化"], "—")

    def test_category_edit_notification_goes_to_each_enabled_admin(self) -> None:
        client = Mock()
        card = {"config": {"wide_screen_mode": True}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "category_edit_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_category_edit({}, {})

        self.assertEqual(count, 2)
        client.send_interactive_message.assert_any_call("ou-a", card)
        client.send_interactive_message.assert_any_call("ou-b", card)

    def test_category_notification_skips_unavailable_admin_and_continues(self) -> None:
        client = Mock()
        client.send_interactive_message.side_effect = [
            app.FeishuBitableError(
                'Feishu HTTP 400: {"code":230013,"msg":"Bot has NO availability to this user"}'
            ),
            "om-success",
        ]
        card = {"config": {"wide_screen_mode": True}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-unavailable", "ou-ok"]),
            patch.object(app, "category_edit_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_category_edit({}, {})

        self.assertEqual(count, 1)
        self.assertEqual(client.send_interactive_message.call_count, 2)

    def test_category_notification_keeps_unexpected_errors_visible(self) -> None:
        client = Mock()
        client.send_interactive_message.side_effect = app.FeishuBitableError(
            'Feishu HTTP 400: {"code":230001,"msg":"invalid request"}'
        )
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-admin"]),
        ):
            with self.assertRaisesRegex(app.FeishuBitableError, "230001"):
                app.notify_enabled_admins_of_category_edit({}, {})

    def test_category_create_card_contains_initial_inventory_details(self) -> None:
        draft = {
            "product": "新品类",
            "category_status": app.STATUS_ACTIVE,
            "category_request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
            "created_at": "2026-07-27 18:00:00",
            "category_zh_page_name": "新品类中文",
            "category_en_page_name": "New Category",
            "category_definition": app.CATEGORY_DEFINITION_PRINT,
        }
        result = {
            "target_count": 2,
            "target_quantity": 25,
            "models": ["M1"],
            "languages": ["英语", "日语"],
            "targets": [
                {
                    "model": "M1", "language": "英语", "quantity": 20,
                    "unit_price": 1.5, "customs_code": "4911101000",
                    "status": app.STATUS_ACTIVE,
                    "request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
                },
                {
                    "model": "M1", "language": "日语", "quantity": 5,
                    "unit_price": 2, "customs_code": "", "status": app.STATUS_INACTIVE,
                    "request_visible": app.REQUEST_PAGE_HIDDEN_VALUE,
                },
            ],
        }

        card = app.category_create_notification_card(draft, result)
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["config"]["width_mode"], "fill")
        self.assertEqual(card["header"]["template"], "green")
        self.assertEqual(card["header"]["title"]["content"], "物料编辑通知｜新物料品类已创建")
        for expected in (
            "新品类", "2026-07-27 18:00:00", "库存组合 2 条",
            "初始库存 25 件", "M1 / 英语", "4911101000", "M1 / 日语", "停用",
            "品类在申领页显示", "申领页",
            "新品类中文", "New Category",
        ):
            self.assertIn(expected, serialized)

    def test_category_create_notification_goes_to_each_enabled_admin(self) -> None:
        client = Mock()
        card = {"config": {"wide_screen_mode": True}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "category_create_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_category_create({}, {})

        self.assertEqual(count, 2)
        client.send_interactive_message.assert_any_call("ou-a", card)
        client.send_interactive_message.assert_any_call("ou-b", card)

    def test_category_delete_card_contains_deleted_material_details(self) -> None:
        draft = {
            "delete_kind": "material_rows",
            "category_names": ["产品单页"],
            "deleted_at": "2026-08-13 15:00:00",
            "records": [
                {
                    "material_code": "MAT-0001",
                    "category": "产品单页",
                    "model": "BellaBot",
                    "language": "韩语(Korean)",
                    "quantity": 0,
                    "status": app.STATUS_ACTIVE,
                }
            ],
        }

        card = app.category_delete_notification_card(draft)
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["config"]["width_mode"], "fill")
        self.assertEqual(card["header"]["template"], "red")
        for expected in (
            "删除物料行",
            "MAT-0001",
            "产品单页 / BellaBot / 韩语(Korean)",
            "库存",
            "启用",
        ):
            self.assertIn(expected, serialized)

    def test_category_delete_notification_goes_to_each_enabled_admin(self) -> None:
        client = Mock()
        card = {"config": {"wide_screen_mode": True}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "category_delete_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_category_delete({})

        self.assertEqual(count, 2)
        client.send_interactive_message.assert_any_call("ou-a", card)
        client.send_interactive_message.assert_any_call("ou-b", card)

    def test_client_sends_text_message_to_open_id(self) -> None:
        client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        client._request = Mock(
            return_value={"data": {"message_id": "om-example"}}
        )

        message_id = client.send_text_message("ou-admin", "申请提醒")

        self.assertEqual(message_id, "om-example")
        call = client._request.call_args
        self.assertEqual(call.args[:2], ("POST", "/im/v1/messages"))
        self.assertEqual(call.kwargs["params"], {"receive_id_type": "open_id"})
        self.assertEqual(call.kwargs["payload"]["receive_id"], "ou-admin")
        self.assertEqual(
            json.loads(call.kwargs["payload"]["content"]),
            {"text": "申请提醒"},
        )

    def test_client_sends_interactive_message_to_open_id(self) -> None:
        client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        client._request = Mock(return_value={"data": {"message_id": "om-card"}})
        card = {"header": {"title": {"tag": "plain_text", "content": "申请单"}}}

        message_id = client.send_interactive_message("ou-admin", card)

        self.assertEqual(message_id, "om-card")
        call = client._request.call_args
        self.assertEqual(call.args[:2], ("POST", "/im/v1/messages"))
        self.assertEqual(call.kwargs["params"], {"receive_id_type": "open_id"})
        self.assertEqual(call.kwargs["payload"]["receive_id"], "ou-admin")
        self.assertEqual(call.kwargs["payload"]["msg_type"], "interactive")
        self.assertEqual(json.loads(call.kwargs["payload"]["content"]), card)

    def test_compat_sender_supports_cached_client_without_message_methods(self) -> None:
        legacy_client = Mock(spec=["_request"])
        legacy_client._request.side_effect = [
            {"data": {"message_id": "om-card"}},
            {"data": {"message_id": "om-text"}},
        ]
        card = {"header": {"title": {"tag": "plain_text", "content": "补库单"}}}

        card_message_id = app.send_feishu_interactive_message(
            legacy_client,
            "ou-admin",
            card,
        )
        text_message_id = app.send_feishu_text_message(
            legacy_client,
            "ou-sales",
            "处理完成",
        )

        self.assertEqual(card_message_id, "om-card")
        self.assertEqual(text_message_id, "om-text")
        card_call, text_call = legacy_client._request.call_args_list
        self.assertEqual(card_call.args[:2], ("POST", "/im/v1/messages"))
        self.assertEqual(card_call.kwargs["payload"]["msg_type"], "interactive")
        self.assertEqual(json.loads(card_call.kwargs["payload"]["content"]), card)
        self.assertEqual(text_call.kwargs["payload"]["msg_type"], "text")
        self.assertEqual(
            json.loads(text_call.kwargs["payload"]["content"]),
            {"text": "处理完成"},
        )

    def test_only_enabled_administrators_are_notification_recipients(self) -> None:
        rows = [
            {
                "record_id": "admin-enabled",
                "fields": {
                    "用户账号": [{"id": "ou_admin"}],
                    "角色": ["管理员", "销售"],
                    "是否启用": "是",
                },
            },
            {
                "record_id": "admin-disabled",
                "fields": {
                    "用户账号": [{"id": "ou_disabled"}],
                    "角色": "管理员",
                    "是否启用": "否",
                },
            },
            {
                "record_id": "sales-enabled",
                "fields": {
                    "用户账号": [{"id": "ou_sales"}],
                    "角色": "销售",
                    "是否启用": "是",
                },
            },
        ]

        with patch.object(app, "fresh_feishu_rows", return_value=rows) as fresh_rows:
            recipients = app.enabled_admin_open_ids()

        self.assertEqual(recipients, ["ou_admin"])
        fresh_rows.assert_called_once_with(app.USER_PERMISSION_TABLE_NAME)

    def test_multi_select_roles_are_recognized(self) -> None:
        rows = [
            {
                "record_id": "multi-role-user",
                "fields": {
                    "用户账号": [{"id": "ou_both"}],
                    "角色": ["销售", "管理员"],
                    "是否启用": "是",
                },
            }
        ]

        with patch.object(app, "fresh_feishu_rows", return_value=rows):
            self.assertEqual(app.enabled_admin_open_ids(), ["ou_both"])
        with patch.object(app, "fresh_feishu_rows", return_value=rows):
            self.assertEqual(app.enabled_sales_open_ids(), ["ou_both"])

    def test_enabled_sales_are_read_from_permission_table(self) -> None:
        rows = [
            {
                "record_id": "sales-enabled",
                "fields": {
                    "用户账号": [{"id": "ou_sales"}],
                    "角色": "销售",
                    "是否启用": "是",
                },
            },
            {
                "record_id": "admin-enabled",
                "fields": {
                    "用户账号": [{"id": "ou_admin"}],
                    "角色": "管理员",
                    "是否启用": "是",
                },
            },
        ]

        with patch.object(app, "fresh_feishu_rows", return_value=rows):
            recipients = app.enabled_sales_open_ids()

        self.assertEqual(recipients, ["ou_sales"])

    def test_new_applicant_is_created_with_sales_role_only(self) -> None:
        rows = [
            {
                "record_id": "existing-admin",
                "fields": {
                    "用户编号": "2",
                    "用户账号": [{"id": "ou_admin"}],
                    "角色": ["管理员", "销售"],
                    "是否启用": "是",
                },
            }
        ]
        created = {"record_id": "new-sales"}
        with (
            patch.object(app, "fresh_feishu_rows", return_value=rows),
            patch.object(app, "feishu_create_record", return_value=created) as create_record,
        ):
            result = app.ensure_requester_sales_permission(
                {"requester_open_id": "ou_new_sales"}
            )

        self.assertEqual(result, "created")
        create_record.assert_called_once_with(
            app.USER_PERMISSION_TABLE_NAME,
            {
                "用户编号": "3",
                "用户账号": [{"id": "ou_new_sales"}],
                "角色": ["销售"],
                "是否启用": "是",
            },
        )
        self.assertNotIn("管理员", create_record.call_args.args[1]["角色"])

    def test_existing_sales_applicant_is_not_duplicated(self) -> None:
        rows = [
            {
                "record_id": "existing-sales",
                "fields": {
                    "用户账号": [{"id": "ou_sales"}],
                    "角色": ["销售"],
                    "是否启用": "是",
                },
            }
        ]
        with (
            patch.object(app, "fresh_feishu_rows", return_value=rows),
            patch.object(app, "feishu_create_record") as create_record,
            patch.object(app, "feishu_update_record_fields") as update_record,
        ):
            result = app.ensure_requester_sales_permission(
                {"requester_open_id": "ou_sales"}
            )

        self.assertEqual(result, "existing")
        create_record.assert_not_called()
        update_record.assert_not_called()

    def test_existing_user_keeps_roles_when_sales_role_is_added(self) -> None:
        rows = [
            {
                "record_id": "existing-user",
                "fields": {
                    "用户账号": [{"id": "ou_existing"}],
                    "角色": ["管理员"],
                    "是否启用": "是",
                },
            }
        ]
        with (
            patch.object(app, "fresh_feishu_rows", return_value=rows),
            patch.object(app, "feishu_create_record") as create_record,
            patch.object(app, "feishu_update_record_fields") as update_record,
        ):
            result = app.ensure_requester_sales_permission(
                {"requester_open_id": "ou_existing"}
            )

        self.assertEqual(result, "updated")
        create_record.assert_not_called()
        update_record.assert_called_once_with(
            app.USER_PERMISSION_TABLE_NAME,
            "existing-user",
            {"角色": ["管理员", "销售"]},
        )

    def test_invalid_applicant_open_id_never_writes_permission_record(self) -> None:
        with (
            patch.object(app, "fresh_feishu_rows") as fresh_rows,
            patch.object(app, "feishu_create_record") as create_record,
            patch.object(app, "feishu_update_record_fields") as update_record,
        ):
            with self.assertRaisesRegex(RuntimeError, "未关联有效的飞书账号"):
                app.ensure_requester_sales_permission({"requester_open_id": ""})

        fresh_rows.assert_not_called()
        create_record.assert_not_called()
        update_record.assert_not_called()

    def test_admin_notification_text_contains_details_without_approval_link(self) -> None:
        payload = {
            "requester": "销售甲",
            "department": "海外销售部",
            "customer_name": "示例客户",
            "country": "德国",
            "material_usage": "展会使用",
            "request_reason": "代理商支持",
        }
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 3,
                "unit_price_rmb": 12.5,
                "subtotal_rmb": 37.5,
            }
        ]

        text = app.material_request_notification_text("REQ-1", payload, lines)

        self.assertIn("REQ-1", text)
        self.assertIn("销售甲", text)
        self.assertIn(
            f"产品折页 / {app.request_model_display_label('BellaBot', language=app.LANGUAGE_ZH)} / 英语 × 3",
            text,
        )
        self.assertIn("来自海外销售部的销售甲的营销物料即将进入审批流程", text)
        self.assertIn("申请原因：代理商支持", text)
        self.assertIn("代理商名称/国家：示例客户 / 德国", text)
        self.assertIn("申请总金额：¥37.50", text)
        self.assertNotIn("申请合计", text)
        self.assertNotIn("审批与发放页面", text)

    def test_admin_notification_card_has_inventory_review_and_actions(self) -> None:
        payload = {
            "title": "展会使用-销售甲-营销物料领取",
            "requester": "销售甲",
            "department": "海外销售部",
            "customer_name": "示例客户",
            "country": "德国",
            "recipient_info": "销售甲，12345，示例地址",
            "freight_payer": "普渡付款(PUDU)",
            "material_usage": "柏林展会",
            "request_reason": "代理商支持",
        }
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 3,
                "remark": "现场派发",
                "unit_price_rmb": 12.5,
                "subtotal_rmb": 37.5,
            }
        ]

        review_context = {
            "request": {
                "record_id": "request-1",
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 0,
                "material_usage_time": "2026-09-30 00:00:00",
            },
            "lines": [{**lines[0], "current_stock": 2}],
            "result": app.INVENTORY_RESULT_INSUFFICIENT,
            "snapshot_at": "2026-08-18 10:00:00",
        }
        with (
            patch.object(
                app, "get_secret_value", return_value="https://local.example.test/"
            ) as get_secret_value,
            patch.object(app, "request_review_access_token", return_value="signed-token"),
        ):
            card = app.material_request_notification_card(
                "REQ-1",
                payload,
                lines,
                review_context=review_context,
                operator_open_id="ou-admin",
            )

        serialized = json.dumps(card, ensure_ascii=False)
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["template"], "orange")
        self.assertEqual(
            card["header"]["title"]["content"],
            "营销物料申请库存确认",
        )
        for expected in (
            "REQ-1",
            "销售甲",
            "海外销售部",
            "示例客户",
            "德国",
            "销售甲，12345，示例地址",
            "普渡付款(PUDU)",
            "柏林展会",
            "代理商支持",
            "申请总金额",
            "¥37.50",
            "物料使用时间",
            "2026-09-30 00:00:00",
            f"产品折页 / {app.request_model_display_label('BellaBot', language=app.LANGUAGE_ZH)} / 英语",
            "库存不足，需要制作",
            "调整配货方案",
            "按原申请确认",
            "驳回申请",
        ):
            self.assertIn(expected, serialized)
        self.assertNotIn("打开审批与发放", serialized)
        self.assertIn("allocation=request", serialized)
        self.assertIn("https://local.example.test/", serialized)
        self.assertNotIn("streamlit.app", serialized)
        get_secret_value.assert_called_with(
            "LOCAL_APP_URL", app.DEFAULT_LOCAL_APP_URL
        )
        self.assertIn("signed-token", serialized)
        self.assertIn('"type": "open_url"', serialized)
        self.assertIn('"action": "confirm_request_inventory"', serialized)
        self.assertIn('"tag": "button"', serialized)
        self.assertNotIn('"tag": "action"', serialized)
        self.assertEqual(card["config"]["width_mode"], "fill")
        inventory_table = next(
            element
            for element in card["body"]["elements"]
            if element.get("tag") == "table"
        )
        self.assertEqual(inventory_table["page_size"], 10)
        self.assertEqual(len(inventory_table["rows"]), 1)
        self.assertEqual(inventory_table["rows"][0]["requested"], 3)
        self.assertEqual(inventory_table["rows"][0]["stock"], 2)
        self.assertIn("现场派发", inventory_table["rows"][0]["specification"])
        self.assertEqual(inventory_table["columns"][0]["width"], "80px")
        confirm_form = next(
            element
            for element in card["body"]["elements"]
            if element.get("tag") == "form"
            and element.get("name") == "request_inventory_confirm_form"
        )
        date_picker = next(
            element
            for element in confirm_form["elements"]
            if element.get("tag") == "date_picker"
        )
        self.assertNotIn("label", date_picker)
        confirm_button = next(
            element
            for element in confirm_form["elements"]
            if element.get("tag") == "button"
        )
        self.assertEqual(confirm_button["name"], "confirm_request_inventory__request-1__0")
        application_section = card["body"]["elements"][1]
        field_grid = application_section["columns"][0]["elements"][1]
        first_field = field_grid["columns"][0]["elements"][0]["columns"][0]
        self.assertEqual(first_field["vertical_spacing"], "2px")
        self.assertEqual(first_field["elements"][0]["text"]["text_size"], "notation")
        self.assertEqual(first_field["elements"][0]["text"]["text_color"], "grey-500")
        self.assertEqual(first_field["elements"][1]["text"]["text_size"], "normal")
        self.assertEqual(field_grid["columns"][0]["vertical_spacing"], "16px")

    def test_large_admin_notification_uses_one_paginated_inventory_table(self) -> None:
        lines = [
            {
                "product": f"物料品类 {index}",
                "model": "T300",
                "language": "英语",
                "quantity": index,
                "current_stock": index - 1,
            }
            for index in range(1, 46)
        ]

        card = app.material_request_notification_card(
            "REQ-LARGE",
            {"requester": "销售甲", "department": "海外销售部"},
            lines,
            review_context={
                "request": {
                    "record_id": "request-large",
                    "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                    "inventory_review_version": 0,
                },
                "lines": lines,
                "result": app.INVENTORY_RESULT_INSUFFICIENT,
                "snapshot_at": "2026-09-17 10:00:00",
            },
        )

        tables = [
            element
            for element in card["body"]["elements"]
            if element.get("tag") == "table"
        ]
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0]["rows"]), 45)
        self.assertEqual(tables[0]["page_size"], 10)
        self.assertLess(len(card["body"]["elements"]), 12)

    def test_confirmed_inventory_card_hides_all_actions(self) -> None:
        payload = {"requester": "销售甲", "department": "海外销售部"}
        lines = [
            {
                "product": "产品单页",
                "model": "D7",
                "language": "英语",
                "quantity": 2,
                "current_stock": 5,
            }
        ]
        card = app.material_request_notification_card(
            "REQ-1",
            payload,
            lines,
            review_context={
                "request": {
                    "record_id": "request-1",
                    "inventory_review_status": app.INVENTORY_REVIEW_CONFIRMED,
                    "inventory_review_version": 1,
                },
                "lines": lines,
                "result": app.INVENTORY_RESULT_SUFFICIENT,
                "snapshot_at": "2026-08-18 10:00:00",
            },
        )

        serialized = json.dumps(card, ensure_ascii=False)
        self.assertIn(app.INVENTORY_REVIEW_CONFIRMED, serialized)
        self.assertNotIn("调整配货方案", serialized)
        self.assertNotIn("按原申请确认", serialized)
        self.assertNotIn('"tag": "button"', serialized)

    def test_notify_sends_once_to_each_enabled_administrator(self) -> None:
        client = Mock()
        card = {"header": {"template": "orange"}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "material_request_notification_card", return_value=card),
        ):
            count = app.notify_enabled_admins_of_material_request("REQ-1", {}, [])

        self.assertEqual(count, 2)
        self.assertEqual(client.send_interactive_message.call_count, 2)
        client.send_interactive_message.assert_any_call("ou-a", card)
        client.send_interactive_message.assert_any_call("ou-b", card)

    def test_request_received_notification_only_goes_to_enabled_sales_applicant(self) -> None:
        client = Mock()
        payload = {"requester_open_id": "ou_sales"}
        card = {"header": {"template": "blue"}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_sales_open_ids", return_value=["ou_sales"]),
            patch.object(app, "enabled_admin_open_ids", return_value=[]),
            patch.object(app, "sales_request_received_notification_card", return_value=card),
        ):
            count = app.notify_sales_request_received("REQ-1", payload, [])

        self.assertEqual(count, 1)
        client.send_interactive_message.assert_called_once_with("ou_sales", card)

        client.reset_mock()
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_sales_open_ids", return_value=["ou_other_sales"]),
            patch.object(app, "enabled_admin_open_ids", return_value=[]),
        ):
            count = app.notify_sales_request_received("REQ-1", payload, [])

        self.assertEqual(count, 0)
        client.send_interactive_message.assert_not_called()

    def test_request_received_notification_also_goes_to_enabled_admin_applicant(self) -> None:
        client = Mock()
        payload = {"requester_open_id": "ou_admin"}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_sales_open_ids", return_value=[]),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou_admin"]),
        ):
            count = app.notify_sales_request_received("REQ-ADMIN", payload, [])
        self.assertEqual(count, 1)
        client.send_interactive_message.assert_called_once()

    def test_foreign_applicant_receives_english_request_card(self) -> None:
        payload = {
            "requester": "John Smith",
            "material_usage": "Trade show",
        }
        card = app.sales_request_received_notification_card(
            "REQ-EN-1", payload, [{"quantity": 3}]
        )
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(
            card["header"]["title"]["content"],
            "Your marketing material request is being reviewed for inventory availability and will enter the approval process after confirmation",
        )
        self.assertIn("Request No.", serialized)
        self.assertIn("REQ-EN-1", serialized)
        self.assertIn("Applicant", serialized)
        self.assertIn("John Smith", serialized)
        self.assertNotIn("申请单号", serialized)
        self.assertNotIn("Modify or withdraw", serialized)
        self.assertNotIn("open_request_editor", serialized)
        self.assertNotIn("Total requested", serialized)

    def test_chinese_applicant_keeps_chinese_request_card(self) -> None:
        card = app.sales_request_received_notification_card(
            "REQ-ZH-1",
            {"requester": "张三", "material_usage": "展会"},
            [
                {
                    "product": "产品单页",
                    "model": "BellaBot",
                    "language": "英语",
                    "quantity": 1,
                }
            ],
        )
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(
            card["header"]["title"]["content"],
            "您提交的营销物料申请正在进行库存确认，确认后将进入审批流程",
        )
        self.assertEqual(
            card["config"]["summary"]["content"],
            "您提交的营销物料申请正在进行库存确认，确认后将进入审批流程",
        )
        body_elements = card["body"]["elements"]
        self.assertIn("物料明细", json.dumps(body_elements[0], ensure_ascii=False))
        self.assertIn("申请信息", json.dumps(body_elements[1], ensure_ascii=False))
        self.assertLess(serialized.index("物料明细"), serialized.index("申请信息"))
        detail_table = next(
            element
            for element in body_elements[0]["columns"][0]["elements"]
            if element.get("tag") == "table"
        )
        self.assertEqual(detail_table["rows"][0]["quantity"], 1)
        self.assertIn("产品单页", detail_table["rows"][0]["specification"])
        self.assertIn("英语", detail_table["rows"][0]["specification"])
        self.assertNotIn("申请合计", serialized)
        self.assertNotIn("修改或撤回本条申请", serialized)
        self.assertNotIn("open_request_editor", serialized)
        self.assertNotIn('"tag": "button"', serialized)

    def test_request_records_keep_applicant_open_id(self) -> None:
        rows = [
            {
                "record_id": "request-a",
                "fields": {
                    "申请单号": "REQ-1",
                    "申请人": [{"id": "ou_sales", "name": "销售甲"}],
                },
            }
        ]
        with patch.object(app, "feishu_rows", return_value=rows):
            records = app.load_feishu_request_records()

        self.assertEqual(records[0]["requester_open_id"], "ou_sales")

    def test_reused_submission_is_not_marked_as_new(self) -> None:
        existing_row = {
            "record_id": "request-a",
            "fields": {"申请单号": "REQ-1"},
        }
        with (
            patch.object(app, "refresh_feishu_schema_cache"),
            patch.object(app, "find_completed_submission", return_value=(existing_row, 2)),
        ):
            result = app.submit_feishu_material_request(
                {"submission_token": "token-1"},
                [{"quantity": 1}],
            )

        self.assertEqual(result, ("REQ-1", 2, False))

    def test_normal_material_request_sets_request_type(self) -> None:
        source = inspect.getsource(app.submit_feishu_material_request)

        self.assertIn('"申请类型": "普通物料申请"', source)
        self.assertNotIn('"申请类型": "文化周边申请"', source)


if __name__ == "__main__":
    unittest.main()
