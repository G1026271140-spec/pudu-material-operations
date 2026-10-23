import unittest
from unittest.mock import Mock

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class FeishuBitableBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        self.client._request = Mock(return_value={"data": {"records": [{"record_id": "r1"}]}})

    def test_batch_update_uses_record_ids_and_fields(self) -> None:
        result = self.client.batch_update_records(
            "table-a",
            [{"record_id": "r1", "fields": {"当前库存": 12}}],
        )

        self.assertEqual(result, [{"record_id": "r1"}])
        self.assertEqual(
            self.client._request.call_args.kwargs["payload"],
            {"records": [{"record_id": "r1", "fields": {"当前库存": 12}}]},
        )

    def test_batch_delete_keeps_consistency_check_enabled(self) -> None:
        self.client.batch_delete_records("table-a", ["r1", "r2"])

        self.assertEqual(
            self.client._request.call_args.kwargs,
            {
                "params": {"ignore_consistency_check": "false"},
                "payload": {"records": ["r1", "r2"]},
            },
        )


if __name__ == "__main__":
    unittest.main()
