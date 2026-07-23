from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import app
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class BotNotificationTests(unittest.TestCase):
    def test_category_edit_card_is_wide_and_contains_change_details(self) -> None:
        draft = {
            "old_product": "旧冰箱贴",
            "product": "新冰箱贴",
            "edited_at": "2026-07-22 10:00:00",
            "current_records": [{
                "model": "BellaBot", "language": "英语", "quantity": 10,
                "unit_price": 1.5, "customs_code": "A1", "status": app.STATUS_ACTIVE,
            }],
            "targets": [{
                "model": "BellaBot", "language": "英语", "quantity": 15,
                "unit_price": 2, "customs_code": "A2", "status": app.STATUS_INACTIVE,
            }],
        }
        result = {
            "target_count": 1, "created_count": 0, "deleted_count": 0,
            "quantity_difference": 5,
        }

        card = app.category_edit_notification_card(draft, result)
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertTrue(card["config"]["wide_screen_mode"])
        self.assertEqual(card["header"]["template"], "blue")
        for expected in ("旧冰箱贴", "新冰箱贴", "BellaBot / 英语", "10 → 15", "1.5 → 2"):
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

    def test_notification_contains_summary_and_approval_link(self) -> None:
        payload = {
            "requester": "销售甲",
            "department": "海外销售部",
            "customer_name": "示例客户",
            "country": "德国",
            "material_usage": "展会使用",
        }
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 3,
            }
        ]

        with patch.object(app, "material_approval_url", return_value="https://example.test/?view=approval"):
            text = app.material_request_notification_text("REQ-1", payload, lines)

        self.assertIn("REQ-1", text)
        self.assertIn("销售甲", text)
        self.assertIn("1 种，共 3 件", text)
        self.assertIn("产品折页 / BellaBot / 英语 × 3", text)
        self.assertIn("https://example.test/?view=approval", text)

    def test_notification_card_contains_full_request_and_approval_button(self) -> None:
        payload = {
            "title": "展会使用-销售甲-营销物料领取",
            "requester": "销售甲",
            "department": "海外销售部",
            "customer_name": "示例客户",
            "country": "德国",
            "recipient_info": "销售甲，12345，示例地址",
            "freight_payer": "普渡付款(PUDU)",
            "material_usage": "柏林展会",
            "attachments": [{"name": "收件信息.pdf"}],
        }
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 3,
                "remark": "现场派发",
            }
        ]

        with patch.object(
            app,
            "material_approval_url",
            return_value="https://example.test/?view=approval",
        ):
            card = app.material_request_notification_card("REQ-1", payload, lines)

        serialized = json.dumps(card, ensure_ascii=False)
        self.assertEqual(card["header"]["template"], "orange")
        for expected in (
            "REQ-1",
            "销售甲",
            "海外销售部",
            "示例客户",
            "德国",
            "销售甲，12345，示例地址",
            "普渡付款(PUDU)",
            "柏林展会",
            "收件信息.pdf",
            "产品折页 / BellaBot / 英语 × 3",
            "现场派发",
        ):
            self.assertIn(expected, serialized)
        action = card["elements"][-1]["actions"][0]
        self.assertEqual(action["url"], "https://example.test/?view=approval")
        self.assertEqual(action["type"], "primary")

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
            patch.object(app, "sales_request_received_notification_card", return_value=card),
        ):
            count = app.notify_sales_request_received("REQ-1", payload, [])

        self.assertEqual(count, 1)
        client.send_interactive_message.assert_called_once_with("ou_sales", card)

        client.reset_mock()
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_sales_open_ids", return_value=["ou_other_sales"]),
        ):
            count = app.notify_sales_request_received("REQ-1", payload, [])

        self.assertEqual(count, 0)
        client.send_interactive_message.assert_not_called()

    def test_foreign_applicant_receives_english_request_card(self) -> None:
        payload = {
            "requester": "John Smith",
            "material_usage": "Trade show",
        }
        card = app.sales_request_received_notification_card(
            "REQ-EN-1", payload, [{"quantity": 3}]
        )
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["header"]["title"]["content"], "Material Request Received")
        self.assertIn("Request No.: REQ-EN-1", serialized)
        self.assertIn("Applicant: John Smith", serialized)
        self.assertNotIn("申请单号", serialized)

    def test_chinese_applicant_keeps_chinese_request_card(self) -> None:
        card = app.sales_request_received_notification_card(
            "REQ-ZH-1", {"requester": "张三"}, [{"quantity": 1}]
        )

        self.assertEqual(card["header"]["title"]["content"], "营销物料申请已进入处理流程")

    def test_completed_notification_contains_requested_and_actual_quantities(self) -> None:
        request = {
            "request_no": "REQ-1",
            "status": app.REQUEST_STATUS_PARTIAL,
        }
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 5,
                "actual_issue_qty": 3,
            }
        ]

        text = app.sales_request_completed_notification_text(request, lines, "剩余待采购")

        self.assertIn(app.REQUEST_STATUS_PARTIAL, text)
        self.assertIn("申请 5，实际发放 3", text)
        self.assertIn("剩余待采购", text)

    def test_completed_notification_shows_changed_actual_material(self) -> None:
        request = {"request_no": "REQ-1", "status": app.REQUEST_STATUS_ISSUED}
        lines = [
            {
                "product": "产品折页",
                "model": "BellaBot",
                "language": "英语",
                "quantity": 5,
                "actual_product": "产品单页",
                "actual_model": "KettyBot Pro",
                "actual_language": "德语",
                "actual_issue_qty": 6,
            }
        ]

        text = app.sales_request_completed_notification_text(request, lines, "替换发放")

        self.assertIn("申请：产品折页 / BellaBot / 英语 × 5", text)
        self.assertIn("实际发放：产品单页 / KettyBot Pro / 德语 × 6", text)
        self.assertIn("替换发放", text)

    def test_completed_notification_only_goes_to_original_sales_applicant(self) -> None:
        client = Mock()
        request = {"requester_open_id": "ou_sales", "request_no": "REQ-1"}
        card = {"header": {"template": "green"}}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_sales_open_ids", return_value=["ou_sales"]),
            patch.object(app, "sales_request_completed_notification_card", return_value=card),
        ):
            count = app.notify_sales_request_completed(request, [], "")

        self.assertEqual(count, 1)
        client.send_interactive_message.assert_called_once_with("ou_sales", card)

    def test_foreign_applicant_receives_english_completed_card(self) -> None:
        request = {
            "request_no": "REQ-EN-2",
            "requester": "John Smith",
            "status": app.REQUEST_STATUS_PARTIAL,
        }
        lines = [{
            "product": "产品单页(Product Flyer)",
            "model": "BellaBot",
            "language": "英语(English)",
            "quantity": 5,
            "actual_issue_qty": 3,
        }]

        card = app.sales_request_completed_notification_card(request, lines, "Pending restock")
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["header"]["title"]["content"], "Material Request Completed")
        self.assertIn("Result: Partially Issued", serialized)
        self.assertIn("Product Flyer / BellaBot / English: requested 5, issued 3", serialized)
        self.assertNotIn("产品单页", serialized)

    def test_request_records_keep_applicant_open_id_for_completion_feedback(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
