from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app


class ApprovalIssuanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.material_row = {
            "record_id": "material-2",
            "fields": {
                "物料编码": "MAT-2",
                "物料品类": "替代品类",
                "产品型号": "M2",
                "语种": "英语",
                "当前库存": 3,
                "启用状态": app.STATUS_ACTIVE,
            },
        }
        self.category_row = {
            "record_id": "category-2",
            "fields": {"物料品类": "替代品类", "启用状态": app.STATUS_ACTIVE},
        }
        self.request = {"record_id": "request-1", "request_no": "REQ-1"}

    def test_issue_can_replace_material_and_create_negative_inventory(self) -> None:
        client = MagicMock()
        line = {
            "record_id": "line-1",
            "product": "替代品类",
            "model": "M2",
            "language": "英语",
            "quantity": 5,
            "actual_issue_qty": 7,
            "previous_actual_issue_qty": 0,
            "previous_product": "原品类",
            "previous_model": "M1",
            "previous_language": "英语",
            "status": app.REQUEST_LINE_STATUS_PENDING,
        }

        def fresh_rows(table_name: str) -> list[dict]:
            if table_name == app.MATERIAL_TABLE_NAME:
                return [self.material_row]
            if table_name == app.CATEGORY_TABLE_NAME:
                return [self.category_row]
            return []

        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=fresh_rows),
            patch.object(app, "feishu_table_id", side_effect=lambda table_name: table_name),
            patch.object(app, "feishu_update_record_fields") as update_fields,
            patch.object(app, "create_feishu_ledger") as create_ledger,
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_accepts_plain_value", return_value=True),
        ):
            logs = app.issue_request_lines(self.request, [line], "替代发放")

        client.update_record.assert_called_once_with(
            app.MATERIAL_TABLE_NAME,
            "material-2",
            {"当前库存": -4},
        )
        create_ledger.assert_called_once()
        self.assertEqual(logs[0][7], -4)
        line_fields = update_fields.call_args_list[0].args[2]
        self.assertEqual(line_fields["实际发放物料编码"], "MAT-2")
        self.assertEqual(line_fields["实际发放物料品类"], "替代品类")
        self.assertEqual(line_fields["实际发放产品型号"], "M2")
        self.assertEqual(line_fields["实际发放语种"], "英语")
        self.assertEqual(line_fields["实际发放数量"], 7)

    def test_partially_issued_line_cannot_switch_material(self) -> None:
        client = MagicMock()
        line = {
            "record_id": "line-1",
            "product": "替代品类",
            "model": "M2",
            "language": "英语",
            "quantity": 5,
            "actual_issue_qty": 3,
            "previous_actual_issue_qty": 2,
            "previous_product": "原品类",
            "previous_model": "M1",
            "previous_language": "英语",
            "status": app.REQUEST_LINE_STATUS_PENDING,
        }

        def fresh_rows(table_name: str) -> list[dict]:
            if table_name == app.MATERIAL_TABLE_NAME:
                return [self.material_row]
            if table_name == app.CATEGORY_TABLE_NAME:
                return [self.category_row]
            return []

        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", side_effect=fresh_rows),
        ):
            with self.assertRaisesRegex(RuntimeError, "已经发生部分发放"):
                app.issue_request_lines(self.request, [line], "")


if __name__ == "__main__":
    unittest.main()
