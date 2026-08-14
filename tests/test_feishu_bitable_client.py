from __future__ import annotations

import unittest
from unittest.mock import patch

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class FeishuBitableClientTests(unittest.TestCase):
    def test_create_table_returns_direct_data_payload(self) -> None:
        client = FeishuBitableClient(
            FeishuBitableConfig("app-id", "app-secret", "app-token")
        )
        response = {
            "code": 0,
            "data": {
                "table_id": "tbl-queue",
                "default_view_id": "vew-queue",
                "field_id_list": ["fld-task-id"],
            },
        }

        with patch.object(client, "_request", return_value=response) as request:
            table = client.create_table(
                "后台任务队列",
                [{"field_name": "任务ID", "type": 1}],
                default_view_name="任务列表",
            )

        self.assertEqual(table["table_id"], "tbl-queue")
        request.assert_called_once()

    def test_paged_get_accepts_null_items_for_empty_table(self) -> None:
        client = FeishuBitableClient(
            FeishuBitableConfig("app-id", "app-secret", "app-token")
        )

        with patch.object(
            client,
            "_request",
            return_value={"code": 0, "data": {"items": None, "has_more": False}},
        ):
            records = client.list_records("tbl-empty")

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
