from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import app
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class BotNotificationTests(unittest.TestCase):
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

    def test_only_enabled_administrators_are_notification_recipients(self) -> None:
        rows = [
            {
                "record_id": "admin-enabled",
                "fields": {
                    "用户账号": [{"id": "ou_admin"}],
                    "角色": "管理员",
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

    def test_notify_sends_once_to_each_enabled_administrator(self) -> None:
        client = Mock()
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-a", "ou-b"]),
            patch.object(app, "material_request_notification_text", return_value="提醒"),
        ):
            count = app.notify_enabled_admins_of_material_request("REQ-1", {}, [])

        self.assertEqual(count, 2)
        self.assertEqual(client.send_text_message.call_count, 2)
        client.send_text_message.assert_any_call("ou-a", "提醒")
        client.send_text_message.assert_any_call("ou-b", "提醒")

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
