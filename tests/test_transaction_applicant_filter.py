import unittest
from unittest.mock import patch

import app


class TransactionApplicantFilterTests(unittest.TestCase):
    def test_request_applicant_supports_person_field_and_note_fallback(self) -> None:
        self.assertEqual(
            app.request_applicant_text({"申请人": {"name": "高鸿源", "email": "test@example.com"}}),
            "高鸿源",
        )
        self.assertEqual(
            app.request_applicant_text({"备注": "客户名称：示例客户\n申请人：销售甲\n物料用途：展会"}),
            "销售甲",
        )

    def test_transaction_inherits_applicant_through_request_line_relation(self) -> None:
        rows = {
            app.REQUEST_TABLE_NAME: [
                {
                    "record_id": "request-1",
                    "fields": {
                        "申请单号": "REQ-20260715-001",
                        "备注": "申请人：销售甲",
                    },
                }
            ],
            app.REQUEST_LINE_TABLE_NAME: [
                {
                    "record_id": "line-1",
                    "fields": {
                        "所属申请单": {"record_ids": ["request-1"], "text_arr": ["REQ-20260715-001"]},
                        "物料品类": "产品折页",
                        "产品型号": "BellaBot",
                        "语种": "英语",
                        "申请数量": 2,
                    },
                }
            ],
            app.LEDGER_TABLE_NAME: [
                {
                    "record_id": "ledger-1",
                    "fields": {
                        "关联明细": {"record_ids": ["line-1"]},
                        "发生时间": 1784073600000,
                        "流水类型": app.ACTION_RECEIVE,
                        "物料品类": "产品折页",
                        "产品型号": "BellaBot",
                        "语种": "英语",
                        "数量": 2,
                        "变更前数量": 1000,
                        "变更后数量": 998,
                        "操作状态": "有效",
                    },
                }
            ],
        }

        with (
            patch.object(app, "feishu_rows", side_effect=lambda table_name: rows.get(table_name, [])),
            patch.object(app, "feishu_material_rows", return_value=[]),
        ):
            records = app.load_feishu_transaction_records(limit=10)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["request_no"], "REQ-20260715-001")
        self.assertEqual(records[0]["requester"], "销售甲")


if __name__ == "__main__":
    unittest.main()
