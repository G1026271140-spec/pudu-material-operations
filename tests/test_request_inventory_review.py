from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class RequestInventoryReviewTests(unittest.TestCase):
    def test_card_edit_form_keeps_category_and_only_offers_its_dimensions(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 2,
            },
            "lines": [
                {
                    "product": "产品单页",
                    "model": "BellaBot",
                    "language": "中文",
                    "quantity": 5,
                }
            ],
            "material_rows": [
                {
                    "record_id": "mat-1",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "BellaBot",
                        "语种": "中文",
                        "启用状态": "启用",
                    },
                },
                {
                    "record_id": "mat-2",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "D7",
                        "语种": "英语",
                        "启用状态": "启用",
                    },
                },
                {
                    "record_id": "mat-3",
                    "fields": {
                        "物料品类": "其他品类",
                        "产品型号": "CC1",
                        "语种": "日语",
                        "启用状态": "启用",
                    },
                },
            ],
        }
        with patch.object(app, "request_inventory_review_context", return_value=context):
            card = app.request_inventory_card_edit_form("request-1")

        serialized = str(card)
        self.assertIn("品类和申请数量保持不变", serialized)
        self.assertIn("BellaBot", serialized)
        self.assertIn("D7", serialized)
        self.assertNotIn("CC1", serialized)
        self.assertNotIn("其他品类", serialized)

    def test_card_edit_draft_resolves_selected_model_language_combination(self) -> None:
        context = {
            "request": {"inventory_review_version": 1},
            "lines": [
                {
                    "record_id": "line-1",
                    "material_record_id": "mat-1",
                    "product": "产品单页",
                    "model": "BellaBot",
                    "language": "中文",
                    "quantity": 5,
                    "remark": "保留备注",
                }
            ],
            "material_rows": [
                {
                    "record_id": "mat-2",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "D7",
                        "语种": "英语",
                        "启用状态": "启用",
                    },
                }
            ],
        }
        with patch.object(app, "request_inventory_review_context", return_value=context):
            draft = app.request_inventory_card_edit_draft(
                "request-1",
                1,
                "ou-admin",
                {"model_0": "D7", "language_0": "英语", "change_note": "改为英文版本"},
            )

        self.assertEqual(draft["lines"][0]["material_record_id"], "mat-2")
        self.assertEqual(draft["lines"][0]["quantity"], 5)
        self.assertEqual(draft["lines"][0]["remark"], "保留备注")
        self.assertEqual(draft["change_note"], "改为英文版本")

    def test_zero_and_negative_inventory_are_insufficient(self) -> None:
        self.assertEqual(
            app.request_inventory_review_result(
                [
                    {"quantity": 1, "current_stock": 0},
                    {"quantity": 1, "current_stock": -2},
                ]
            ),
            app.INVENTORY_RESULT_INSUFFICIENT,
        )
        self.assertEqual(
            app.request_inventory_review_result(
                [
                    {"quantity": 1, "current_stock": 2},
                    {"quantity": 3, "current_stock": 1},
                ]
            ),
            app.INVENTORY_RESULT_PARTIAL,
        )

    def test_confirm_rechecks_inventory_and_writes_review_fields(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 2,
            },
            "lines": [
                {
                    "record_id": "line-1",
                    "current_stock": 0,
                    "inventory_status": "库存不足，需要制作",
                }
            ],
            "result": app.INVENTORY_RESULT_INSUFFICIENT,
        }
        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou_admin"]),
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_lines,
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "notify_enabled_admins_of_material_request", return_value=1) as notify,
        ):
            result = app.execute_request_inventory_confirm(
                {
                    "request_id": "request-1",
                    "expected_version": 2,
                    "operator_open_id": "ou_admin",
                }
            )

        update_lines.assert_called_once_with(
            app.REQUEST_LINE_TABLE_NAME,
            [
                {
                    "record_id": "line-1",
                    "fields": {
                        "库存审查时库存": "0",
                        "库存满足状态": "库存不足，需要制作",
                    },
                }
            ],
        )
        request_fields = update_request.call_args.args[2]
        self.assertEqual(request_fields["库存审查状态"], app.INVENTORY_REVIEW_CONFIRMED)
        self.assertEqual(request_fields["库存审查结论"], app.INVENTORY_RESULT_INSUFFICIENT)
        self.assertEqual(request_fields["库存审查人"], [{"id": "ou_admin"}])
        notify.assert_called_once()
        self.assertTrue(result["confirmed"])


if __name__ == "__main__":
    unittest.main()
