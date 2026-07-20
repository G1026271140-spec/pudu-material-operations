from __future__ import annotations

import unittest
from unittest.mock import call, patch

import app


class ApprovalLiveDataTests(unittest.TestCase):
    def test_approval_live_data_reads_each_table_directly(self) -> None:
        rows = {
            app.REQUEST_TABLE_NAME: [{"record_id": "request-1", "fields": {}}],
            app.REQUEST_LINE_TABLE_NAME: [{"record_id": "line-1", "fields": {}}],
            app.MATERIAL_TABLE_NAME: [{"record_id": "material-1", "fields": {}}],
        }
        with patch.object(
            app,
            "fresh_feishu_rows",
            side_effect=lambda table_name: rows[table_name],
        ) as fresh_rows:
            live_data = app.fetch_approval_live_data()

        self.assertEqual(live_data["row_count"], 3)
        self.assertEqual(
            fresh_rows.call_args_list,
            [
                call(app.REQUEST_TABLE_NAME),
                call(app.REQUEST_LINE_TABLE_NAME),
                call(app.MATERIAL_TABLE_NAME),
            ],
        )

    def test_request_fields_fall_back_to_structured_note(self) -> None:
        rows = [
            {
                "record_id": "request-1",
                "fields": {
                    "申请单号": "REQ-1",
                    "备注": (
                        "客户名称：Impact\n"
                        "国家：USA\n"
                        "收件人信息：300 Wilson Road\nVance Tiller\n"
                        "运费承担者：普渡付款(PUDU)\n"
                        "物料用途：拉美活动\n"
                        "申请人：销售甲"
                    ),
                },
            }
        ]

        records = app.load_feishu_request_records(rows)

        self.assertEqual(records[0]["customer_name"], "Impact")
        self.assertEqual(records[0]["country"], "USA")
        self.assertEqual(records[0]["recipient_info"], "300 Wilson Road\nVance Tiller")
        self.assertEqual(records[0]["freight_payer"], "普渡付款(PUDU)")
        self.assertEqual(records[0]["material_usage"], "拉美活动")
        self.assertEqual(records[0]["requester"], "销售甲")


if __name__ == "__main__":
    unittest.main()
