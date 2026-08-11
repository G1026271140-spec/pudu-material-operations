from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class RequestRecordParsingTests(unittest.TestCase):
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
