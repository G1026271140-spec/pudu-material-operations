from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

import app


class RequestInventoryReviewTests(unittest.TestCase):
    def test_final_material_detail_text_lists_verified_lines(self) -> None:
        detail = app.request_material_detail_text(
            [
                {
                    "product": "公仔(Plush Toy)",
                    "model": "BellaBot",
                    "language": "无需语种",
                    "quantity": 2,
                },
                {
                    "product": "产品单页(Product Flyer)",
                    "model": "D7",
                    "language": "英语(English)",
                    "quantity": 10,
                },
                {"product": "忽略", "quantity": 0},
            ]
        )

        self.assertEqual(
            detail,
            f"01. 公仔(Plush Toy) / {app.request_model_display_label('BellaBot', language=app.LANGUAGE_ZH)} / 无需语种 × 2\n"
            "02. 产品单页(Product Flyer) / D7 / 英语(English) × 10",
        )

    def test_page_loader_reads_one_request_and_only_needed_line_fields(self) -> None:
        client = Mock()
        client.get_record.side_effect = [
            {
                "record_id": "request-1",
                "fields": {"申请明细": [{"record_ids": ["line-1"]}]},
            },
            {"record_id": "line-1", "fields": {}},
        ]

        with patch.object(app, "FeishuBitableClient", return_value=client) as client_class:
            request_row, lines = app.load_request_inventory_page_rows.__wrapped__(
                "request-1",
                "tbl-requests",
                "tbl-lines",
                ("所属申请单", "物料编码", "申请数量"),
                "app-id",
                "app-secret",
                "app-token",
            )

        client_class.assert_called_once()

        self.assertEqual(request_row["record_id"], "request-1")
        self.assertEqual([row["record_id"] for row in lines], ["line-1"])
        self.assertEqual(
            client.get_record.call_args_list,
            [
                call("tbl-requests", "request-1"),
                call("tbl-lines", "line-1"),
            ],
        )
        client.list_records.assert_not_called()

    def test_page_loader_uses_limited_field_fallback_for_legacy_request(self) -> None:
        client = Mock()
        client.get_record.return_value = {"record_id": "request-1", "fields": {}}
        client.list_records.return_value = [
            {
                "record_id": "line-1",
                "fields": {"所属申请单": [{"record_ids": ["request-1"]}]},
            },
            {
                "record_id": "line-2",
                "fields": {"所属申请单": [{"record_ids": ["request-2"]}]},
            },
        ]

        with patch.object(app, "FeishuBitableClient", return_value=client):
            _, lines = app.load_request_inventory_page_rows.__wrapped__(
                "request-1",
                "tbl-requests",
                "tbl-lines",
                ("所属申请单", "物料编码", "申请数量"),
                "app-id",
                "app-secret",
                "app-token",
            )

        self.assertEqual([row["record_id"] for row in lines], ["line-1"])
        client.list_records.assert_called_once_with(
            "tbl-lines",
            field_names=["所属申请单", "物料编码", "申请数量"],
        )

    def test_review_page_uses_fullscreen_application_loading_overlay(self) -> None:
        self.assertIn(
            "正在抓取申请单数据，请稍候...",
            app.render_request_inventory_review_page.__code__.co_consts,
        )

    def test_cached_allocation_catalog_uses_cache_and_keeps_current_disabled_item(self) -> None:
        cache = {"inventory_rows": [{"material_code": "MAT-1"}]}
        material_rows = [
            {
                "record_id": "mat-1",
                "fields": {
                    "物料编码": "MAT-1",
                    "物料品类": "产品单页",
                    "产品型号": "D7",
                    "语种": "英语",
                    "当前库存": 4,
                    "启用状态": "启用",
                    "申领页显示": "是",
                },
            },
            {
                "record_id": "mat-current",
                "fields": {
                    "物料编码": "MAT-OLD",
                    "物料品类": "旧物料",
                    "产品型号": "旧型号",
                    "语种": "无需语种",
                    "当前库存": 0,
                    "启用状态": "停用",
                    "申领页显示": "否",
                },
            },
            {
                "record_id": "mat-hidden",
                "fields": {
                    "物料编码": "MAT-HIDDEN",
                    "物料品类": "隐藏物料",
                    "启用状态": "启用",
                    "申领页显示": "是",
                },
            },
        ]

        records = app.cached_allocation_material_records(
            cache,
            material_rows,
            current_material_ids={"mat-current"},
        )

        self.assertEqual([record["record_id"] for record in records], ["mat-1", "mat-current"])
        self.assertEqual(records[0]["quantity"], 4)

    def test_requester_inventory_edit_notification_is_structured_card(self) -> None:
        client = Mock()
        request = {"request_no": "REQ-1", "requester_open_id": "ou-user"}
        before = [
            {"product": "公仔", "model": "BellaBot", "language": "无需语种", "quantity": 1}
        ]
        after = [
            {
                "product": "公仔",
                "model": "KettyBot Pro",
                "language": "无需语种",
                "quantity": 1,
                "current_stock": 0,
            }
        ]
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(
                app,
                "enabled_admin_open_ids",
                return_value=["ou_admin_1", "ou_admin_2"],
            ),
        ):
            app.notify_requester_of_inventory_edit(request, before, after, "原型号库存不足")

        client.send_interactive_message.assert_called_once()
        card = client.send_interactive_message.call_args.args[1]
        serialized = str(card)
        self.assertIn("营销物料申请已调整", serialized)
        self.assertIn("修改前", serialized)
        self.assertIn("修改后", serialized)
        self.assertNotIn("当前库存", serialized)
        self.assertNotIn("库存不足，需要制作", serialized)
        self.assertIn("原型号库存不足", serialized)
        self.assertIn(app.INVENTORY_REVIEW_CONFIRMED, serialized)
        self.assertIn("如有疑问或其他需求，请联系", serialized)
        self.assertIn("<at id=ou_admin_1></at>", serialized)
        self.assertIn("<at id=ou_admin_2></at>", serialized)
        contact_element = card["body"]["elements"][-1]
        self.assertEqual(set(contact_element), {"tag", "content"})
        client.send_text_message.assert_not_called()

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
        self.assertIn("material_0", serialized)
        self.assertNotIn("model_0", serialized)
        self.assertNotIn("language_0", serialized)
        self.assertNotIn("CC1", serialized)
        self.assertNotIn("其他品类", serialized)

    def test_combined_dimension_selection_maps_directly_to_material_row(self) -> None:
        context = {
            "request": {"inventory_review_version": 1},
            "lines": [
                {
                    "record_id": "line-1",
                    "material_record_id": "mat-1",
                    "product": "产品单页",
                    "model": "MT1 Vac",
                    "language": "英语",
                    "quantity": 1,
                    "remark": "",
                }
            ],
            "material_rows": [
                {
                    "record_id": "mat-2",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "BellaBot",
                        "语种": "简中",
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
                {"material_0": "mat-2", "change_note": "切换版本"},
            )

        self.assertEqual(draft["lines"][0]["material_record_id"], "mat-2")

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
                    "product": "公仔",
                    "model": "BellaBot",
                    "language": "无需语种",
                    "quantity": 2,
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
        self.assertEqual(request_fields["申请物料最后修改人"], [{"id": "ou_admin"}])
        self.assertEqual(request_fields["申请物料最后修改时间"], 123456)
        self.assertEqual(
            request_fields["物料明细文字信息"],
            f"01. 公仔 / {app.request_model_display_label('BellaBot', language=app.LANGUAGE_ZH)} / 无需语种 × 2",
        )
        notify.assert_called_once()
        self.assertTrue(result["confirmed"])

    def test_editing_request_also_marks_inventory_as_confirmed(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "status": app.REQUEST_STATUS_PENDING,
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 0,
            },
            "lines": [
                {
                    "record_id": "line-1",
                    "material_record_id": "mat-1",
                    "product": "产品单页",
                    "model": "D7",
                    "language": "英语",
                    "quantity": 2,
                    "remark": "",
                }
            ],
            "material_rows": [
                {
                    "record_id": "mat-1",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "D7",
                        "语种": "英语",
                        "当前库存": 5,
                    },
                }
            ],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields"),
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "ensure_request_change_record_fields"),
            patch.object(app, "feishu_batch_create_records"),
            patch.object(app, "notify_requester_of_inventory_edit"),
            patch.object(app, "notify_enabled_admins_of_material_request"),
        ):
            app.execute_request_inventory_edit(
                {
                    "request_id": "request-1",
                    "expected_version": 0,
                    "operator_open_id": "ou_admin",
                    "change_note": "调整型号语种",
                    "lines": [
                        {"material_record_id": "mat-1", "quantity": 2, "remark": ""}
                    ],
                }
            )

        request_fields = update_request.call_args.args[2]
        self.assertEqual(
            request_fields["物料明细文字信息"],
            "01. 产品单页 / D7 / 英语 × 2",
        )

    def test_retry_after_persisted_edit_recovers_both_notifications(self) -> None:
        context = {
            "request": {
                "request_no": "REQ-1",
                "status": app.REQUEST_STATUS_PENDING,
                "inventory_review_status": app.INVENTORY_REVIEW_CONFIRMED,
                "inventory_review_version": 1,
                "inventory_change_note": "库存不足，调整型号",
            },
            "lines": [],
            "result": app.INVENTORY_RESULT_SUFFICIENT,
        }
        draft = {
            "request_id": "request-1",
            "expected_version": 0,
            "change_note": "库存不足，调整型号",
            "before_lines": [],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "notify_requester_of_inventory_edit") as notify_requester,
            patch.object(app, "notify_enabled_admins_of_material_request") as notify_admins,
            patch.object(app, "feishu_update_record_fields") as update_request,
        ):
            result = app.execute_request_inventory_edit(draft)

        self.assertTrue(result["recovered_notifications"])
        notify_requester.assert_called_once()
        notify_admins.assert_called_once()
        update_request.assert_not_called()
        update_request(
            "request-table",
            "request-1",
            {
                "库存审查状态": app.INVENTORY_REVIEW_CONFIRMED,
                "库存审查人": [{"id": "ou_admin"}],
                "库存审查时间": 123456,
            },
        )

        request_fields = update_request.call_args.args[2]
        self.assertEqual(request_fields["库存审查状态"], app.INVENTORY_REVIEW_CONFIRMED)
        self.assertEqual(request_fields["库存审查人"], [{"id": "ou_admin"}])
        self.assertEqual(request_fields["库存审查时间"], 123456)


if __name__ == "__main__":
    unittest.main()
