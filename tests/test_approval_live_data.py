from __future__ import annotations

import unittest
from unittest.mock import call, patch

import app


class ApprovalLiveDataTests(unittest.TestCase):
    def test_request_maintenance_reads_live_request_tables(self) -> None:
        rows = {
            app.REQUEST_TABLE_NAME: [
                {
                    "record_id": "request-1",
                    "fields": {
                        "申请单号": "REQ-1",
                        "申请人": "销售甲",
                        "审批状态": app.REQUEST_STATUS_PENDING,
                    },
                }
            ],
            app.REQUEST_LINE_TABLE_NAME: [],
            app.MATERIAL_TABLE_NAME: [],
        }
        with patch.object(
            app,
            "fresh_feishu_rows",
            side_effect=lambda table_name: rows[table_name],
        ) as fresh_rows:
            live_data = app.fetch_request_maintenance_live_data()

        self.assertEqual(live_data["row_count"], 1)
        self.assertEqual(live_data["requests"][0]["request_no"], "REQ-1")
        self.assertEqual(
            fresh_rows.call_args_list,
            [
                call(app.REQUEST_TABLE_NAME),
                call(app.REQUEST_LINE_TABLE_NAME),
                call(app.MATERIAL_TABLE_NAME),
            ],
        )

    def test_withdraw_pending_request_updates_request_and_lines(self) -> None:
        request = {"record_id": "request-1", "request_no": "REQ-1"}
        rows = {
            app.REQUEST_TABLE_NAME: [
                {
                    "record_id": "request-1",
                    "fields": {
                        "申请单号": "REQ-1",
                        "审批状态": app.REQUEST_STATUS_PENDING,
                    },
                }
            ],
            app.REQUEST_LINE_TABLE_NAME: [
                {
                    "record_id": "line-1",
                    "fields": {
                        "所属申请单": [{"record_ids": ["request-1"]}],
                        "明细状态": app.REQUEST_LINE_STATUS_PENDING,
                    },
                }
            ],
        }
        with (
            patch.object(
                app,
                "fresh_feishu_rows",
                side_effect=lambda table_name: rows[table_name],
            ),
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
        ):
            app.withdraw_pending_feishu_request(request)

        update_request.assert_called_once_with(
            app.REQUEST_TABLE_NAME,
            "request-1",
            {"审批状态": app.REQUEST_STATUS_WITHDRAWN},
        )
        update_lines.assert_called_once()
        self.assertEqual(
            update_lines.call_args.args[1][0]["fields"]["明细状态"],
            app.REQUEST_LINE_STATUS_WITHDRAWN,
        )

    def test_pending_request_update_can_remove_one_material_line(self) -> None:
        request = {"record_id": "request-1", "request_no": "REQ-1"}
        rows = {
            app.REQUEST_TABLE_NAME: [
                {
                    "record_id": "request-1",
                    "fields": {
                        "申请单号": "REQ-1",
                        "审批状态": app.REQUEST_STATUS_PENDING,
                    },
                }
            ],
            app.REQUEST_LINE_TABLE_NAME: [
                {
                    "record_id": "line-1",
                    "fields": {
                        "所属申请单": [{"record_ids": ["request-1"]}],
                        "明细状态": app.REQUEST_LINE_STATUS_PENDING,
                    },
                },
                {
                    "record_id": "line-2",
                    "fields": {
                        "所属申请单": [{"record_ids": ["request-1"]}],
                        "明细状态": app.REQUEST_LINE_STATUS_PENDING,
                    },
                },
            ],
        }
        with (
            patch.object(
                app,
                "fresh_feishu_rows",
                side_effect=lambda table_name: rows[table_name],
            ),
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
        ):
            app.update_pending_feishu_request(
                request,
                {"客户名称": "Updated"},
                [
                    {"record_id": "line-1", "quantity": 3, "remark": ""},
                    {"record_id": "line-2", "quantity": 0, "remark": ""},
                ],
            )

        update_request.assert_called_once_with(
            app.REQUEST_TABLE_NAME,
            "request-1",
            {"客户名称": "Updated"},
        )
        updates_by_id = {
            item["record_id"]: item["fields"]
            for item in update_lines.call_args.args[1]
        }
        self.assertEqual(updates_by_id["line-1"]["申请数量"], 3)
        self.assertEqual(
            updates_by_id["line-2"],
            {"明细状态": app.REQUEST_LINE_STATUS_WITHDRAWN},
        )

    def test_pending_request_update_must_keep_one_material_line(self) -> None:
        request = {"record_id": "request-1", "request_no": "REQ-1"}
        rows = {
            app.REQUEST_TABLE_NAME: [
                {
                    "record_id": "request-1",
                    "fields": {
                        "申请单号": "REQ-1",
                        "审批状态": app.REQUEST_STATUS_PENDING,
                    },
                }
            ],
            app.REQUEST_LINE_TABLE_NAME: [
                {
                    "record_id": "line-1",
                    "fields": {
                        "所属申请单": [{"record_ids": ["request-1"]}],
                        "明细状态": app.REQUEST_LINE_STATUS_PENDING,
                    },
                }
            ],
        }
        with (
            patch.object(
                app,
                "fresh_feishu_rows",
                side_effect=lambda table_name: rows[table_name],
            ),
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
        ):
            with self.assertRaisesRegex(RuntimeError, "至少需要保留一条"):
                app.update_pending_feishu_request(
                    request,
                    {},
                    [{"record_id": "line-1", "quantity": 0, "remark": ""}],
                )

        update_request.assert_not_called()
        update_lines.assert_not_called()

    def test_approval_live_data_reads_each_table_directly(self) -> None:
        rows = {
            app.REQUEST_TABLE_NAME: [{"record_id": "request-1", "fields": {}}],
            app.REQUEST_LINE_TABLE_NAME: [{"record_id": "line-1", "fields": {}}],
            app.MATERIAL_TABLE_NAME: [{"record_id": "material-1", "fields": {}}],
            app.CATEGORY_TABLE_NAME: [{"record_id": "category-1", "fields": {}}],
            app.MODEL_TABLE_NAME: [{"record_id": "model-1", "fields": {}}],
        }
        with patch.object(
            app,
            "fresh_feishu_rows",
            side_effect=lambda table_name: rows[table_name],
        ) as fresh_rows:
            live_data = app.fetch_approval_live_data()

        self.assertEqual(live_data["row_count"], 5)
        self.assertEqual(
            fresh_rows.call_args_list,
            [
                call(app.REQUEST_TABLE_NAME),
                call(app.REQUEST_LINE_TABLE_NAME),
                call(app.MATERIAL_TABLE_NAME),
                call(app.CATEGORY_TABLE_NAME),
                call(app.MODEL_TABLE_NAME),
            ],
        )

    def test_inventory_shortage_is_based_on_requested_quantity(self) -> None:
        self.assertTrue(app.inventory_is_insufficient(101, 100))
        self.assertFalse(app.inventory_is_insufficient(100, 100))
        self.assertFalse(app.inventory_is_insufficient(99, 100))

    def test_approval_inventory_context_only_contains_active_combinations(self) -> None:
        live_data = {
            "category_rows": [
                {"record_id": "c1", "fields": {"物料品类": "启用品类", "启用状态": app.STATUS_ACTIVE}},
                {"record_id": "c2", "fields": {"物料品类": "停用品类", "启用状态": app.STATUS_INACTIVE}},
            ],
            "model_rows": [
                {"record_id": "m1", "fields": {"产品型号": "M1", "启用状态": app.STATUS_ACTIVE}},
                {"record_id": "m2", "fields": {"产品型号": "M2", "启用状态": app.STATUS_INACTIVE}},
            ],
            "material_rows": [
                {
                    "record_id": "i1",
                    "fields": {
                        "物料编码": "MAT-1",
                        "物料品类": "启用品类",
                        "产品型号": "M1",
                        "语种": "英语",
                        "当前库存": 10,
                        "启用状态": app.STATUS_ACTIVE,
                    },
                },
                {
                    "record_id": "i2",
                    "fields": {
                        "物料编码": "MAT-2",
                        "物料品类": "停用品类",
                        "产品型号": "M1",
                        "语种": "英语",
                        "当前库存": 10,
                        "启用状态": app.STATUS_ACTIVE,
                    },
                },
                {
                    "record_id": "i3",
                    "fields": {
                        "物料编码": "MAT-3",
                        "物料品类": "启用品类",
                        "产品型号": "M2",
                        "语种": "法语",
                        "当前库存": 10,
                        "启用状态": app.STATUS_INACTIVE,
                    },
                },
            ],
        }

        context = app.approval_inventory_context(live_data)

        self.assertEqual(context["products"], ["启用品类"])
        self.assertEqual(context["models"], ["M1"])
        self.assertEqual(context["languages"], ["英语"])
        self.assertEqual(list(context["by_key"]), [("启用品类", "M1", "英语")])

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
