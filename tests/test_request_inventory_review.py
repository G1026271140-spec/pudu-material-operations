from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

import app


class RequestInventoryReviewTests(unittest.TestCase):
    def test_expired_admin_card_is_replaced_and_new_message_id_is_saved(self) -> None:
        client = Mock()
        client.update_interactive_message.side_effect = RuntimeError(
            "Feishu HTTP 400: code 230031 Message has expired"
        )
        context = {
            "request": {
                "record_id": "request-1",
                "inventory_message_ids": ["old-message", "orphaned-old-message"],
            }
        }
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "material_request_notification_card", return_value={"card": True}),
            patch.object(app, "send_feishu_interactive_message", return_value="new-message") as send,
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_update_record_fields") as update_request,
        ):
            count = app.notify_enabled_admins_of_material_request(
                "REQ-1", {"request_no": "REQ-1"}, []
            )

        self.assertEqual(count, 1)
        send.assert_called_once_with(client, "ou-admin", {"card": True})
        self.assertEqual(
            update_request.call_args.args[2]["库存确认消息ID"],
            '["new-message"]',
        )

    def test_allocation_retry_skips_lines_already_in_committed_order_batch(self) -> None:
        service = Mock()
        service.snapshot.return_value = {"snapshot": True}
        service.grouped_requests.return_value = {
            "request-1": {
                "fingerprint": "fp-1",
                "lines": [
                    {"id": "line-1", "fields": {"下单表生成状态": "已生成"}}
                ],
            }
        }
        with (
            patch.object(app, "feishu_has_field", return_value=False),
            patch.object(app, "feishu_client", return_value=Mock()),
            patch("order_scheduling_service.SchedulingService", return_value=service),
        ):
            result = app.apply_inventory_allocation_schedule(
                "request-1",
                [{
                    "line_id": "line-1",
                    "category_definition": app.CATEGORY_DEFINITION_PRINT,
                    "order_required": True,
                }],
                "ou-admin",
                "allocation:request-1:0",
                validated_line_ids={"line-1"},
            )

        self.assertEqual(result["generated_order_lines"], 0)
        service.record_schedule.assert_not_called()

    def test_only_printed_materials_can_enter_order_and_auto_restock(self) -> None:
        service = Mock()
        with (
            patch.object(app, "feishu_has_field", return_value=False),
            patch.object(app, "feishu_client", return_value=Mock()),
            patch("order_scheduling_service.SchedulingService", return_value=service),
        ):
            result = app.apply_inventory_allocation_schedule(
                "request-1",
                [
                    {
                        "line_id": "gift-line",
                        "category_definition": app.CATEGORY_DEFINITION_GIFT,
                        "order_required": True,
                    },
                    {
                        "line_id": "culture-line",
                        "category_definition": app.CATEGORY_DEFINITION_CULTURAL,
                        "order_required": True,
                    },
                ],
                "ou-admin",
                "allocation:request-1:0",
                validated_line_ids={"gift-line", "culture-line"},
            )

        self.assertEqual(result["generated_order_lines"], 0)
        self.assertEqual(result["arrived_without_order_lines"], 2)
        service.record_schedule.assert_not_called()
        self.assertTrue(
            app.allocation_line_requires_order(app.CATEGORY_DEFINITION_PRINT, True)
        )
        self.assertFalse(
            app.allocation_line_requires_order(app.CATEGORY_DEFINITION_GIFT, True)
        )
        self.assertFalse(
            app.allocation_line_requires_order(app.CATEGORY_DEFINITION_CULTURAL, True)
        )

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
            category_rows=[
                {"record_id": "cat-print", "fields": {"物料品类": "产品单页", "品类定义": app.CATEGORY_DEFINITION_PRINT}},
                {"record_id": "cat-old", "fields": {"物料品类": "旧物料", "品类定义": app.CATEGORY_DEFINITION_GIFT}},
            ],
        )

        self.assertEqual([record["record_id"] for record in records], ["mat-1", "mat-current"])
        self.assertEqual(records[0]["quantity"], 4)
        self.assertEqual(records[0]["category_definition"], app.CATEGORY_DEFINITION_PRINT)
        self.assertEqual(records[1]["category_definition"], app.CATEGORY_DEFINITION_GIFT)

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

        self.assertEqual(client.send_interactive_message.call_count, 3)
        recipients = [call.args[0] for call in client.send_interactive_message.call_args_list]
        self.assertEqual(recipients, ["ou-user", "ou_admin_1", "ou_admin_2"])
        card = client.send_interactive_message.call_args_list[0].args[1]
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

    def test_inventory_edit_notification_does_not_duplicate_requester_admin(self) -> None:
        client = Mock()
        request = {"request_no": "REQ-1", "requester_open_id": "ou-both"}
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-both", "ou-admin"]),
        ):
            count = app.notify_requester_of_inventory_edit(
                request,
                [{"product": "公仔", "model": "BellaBot", "language": "无需语种", "quantity": 1}],
                [{"product": "公仔", "model": "KettyBot Pro", "language": "无需语种", "quantity": 1}],
                "调整型号",
            )

        self.assertEqual(count, 2)
        self.assertEqual(
            [call.args[0] for call in client.send_interactive_message.call_args_list],
            ["ou-both", "ou-admin"],
        )

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
        self.assertEqual(draft["lines"][0]["line_record_id"], "line-1")

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
        self.assertEqual(draft["lines"][0]["line_record_id"], "line-1")
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
                        "审批通过数量": 2,
                        "实际发放数量": 2,
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

    def test_confirm_repairs_issued_quantity_when_request_is_already_confirmed(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "inventory_review_status": app.INVENTORY_REVIEW_CONFIRMED,
                "inventory_review_version": 0,
            },
            "lines": [
                {
                    "record_id": "line-1",
                    "quantity": 7,
                    "approved_qty": 7,
                    "actual_issue_qty": 0,
                    "current_stock": 20,
                    "inventory_status": app.INVENTORY_RESULT_SUFFICIENT,
                }
            ],
            "result": app.INVENTORY_RESULT_SUFFICIENT,
        }
        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou_admin"]),
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_lines,
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "notify_enabled_admins_of_material_request") as notify,
        ):
            result = app.execute_request_inventory_confirm(
                {
                    "request_id": "request-1",
                    "expected_version": 0,
                    "operator_open_id": "ou_admin",
                }
            )

        self.assertEqual(
            update_lines.call_args.args[1][0]["fields"]["实际发放数量"], 7
        )
        self.assertTrue(result["already_confirmed"])
        self.assertEqual(result["repaired_line_count"], 1)
        update_request.assert_not_called()
        notify.assert_not_called()

    def test_reject_deletes_request_lines_and_notifies_requester(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "requester": "销售甲",
                "requester_open_id": "ou-user",
                "status": app.REQUEST_STATUS_PENDING,
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 2,
            },
            "lines": [{"record_id": "line-1"}, {"record_id": "line-2"}],
        }
        client = Mock()
        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_batch_delete_record_ids", return_value=2) as delete_lines,
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "feishu_table_id", side_effect=lambda name: f"tbl-{name}"),
            patch.object(app, "notify_requester_of_inventory_rejection", return_value=1) as notify,
        ):
            result = app.execute_request_inventory_reject(
                {
                    "request_id": "request-1",
                    "expected_version": 2,
                    "operator_open_id": "ou-admin",
                }
            )

        delete_lines.assert_called_once_with(app.REQUEST_LINE_TABLE_NAME, ["line-1", "line-2"])
        client.delete_record.assert_called_once_with(
            f"tbl-{app.REQUEST_TABLE_NAME}", "request-1"
        )
        notify.assert_called_once_with(context["request"])
        self.assertTrue(result["rejected"])
        self.assertEqual(result["deleted_line_count"], 2)

    def test_complete_writeback_deletes_only_request_custom_materials(self) -> None:
        context = {
            "request": {"request_no": "REQ-1", "status": "已发放"},
            "request_row": {
                "record_id": "request-1",
                "fields": {"临时物料清理状态": "待清理"},
            },
            "lines": [
                {"material_record_id": "mat-custom", "status": "已发放"},
                {"material_record_id": "mat-normal", "status": "已发放"},
            ],
            "material_rows": [
                {
                    "record_id": "mat-custom",
                    "fields": {
                        "是否临时物料": True,
                        "备注": "自定义物料申请:token:key",
                    },
                },
                {
                    "record_id": "mat-normal",
                    "fields": {"是否临时物料": False, "备注": ""},
                },
                {
                    "record_id": "mat-other",
                    "fields": {
                        "是否临时物料": True,
                        "备注": "自定义物料申请:other:key",
                    },
                },
            ],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_batch_delete_record_ids", return_value=1) as delete,
            patch.object(app, "feishu_update_record_fields") as update_request,
        ):
            deleted = app.cleanup_custom_materials_for_request("REQ-1")

        self.assertEqual(deleted, 1)
        delete.assert_called_once_with(app.MATERIAL_TABLE_NAME, ["mat-custom"])
        update_request.assert_called_once_with(
            app.REQUEST_TABLE_NAME,
            "request-1",
            {"临时物料清理状态": "已清理"},
        )

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
                    "line_no": "REQ-1-03",
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
                },
                {
                    "record_id": "mat-2",
                    "fields": {
                        "物料品类": "产品单页",
                        "产品型号": "T300",
                        "语种": "英语",
                        "当前库存": 8,
                    },
                },
            ],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "ensure_request_change_record_fields"),
            patch.object(app, "feishu_batch_create_records") as create_lines,
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
                        {"material_record_id": "mat-1", "quantity": 3, "remark": ""},
                        {"material_record_id": "mat-2", "quantity": 4, "remark": ""},
                    ],
                }
            )

        updated_line_fields = update_lines.call_args.args[1][0]["fields"]
        created_line_fields = next(
            call.args[1][0]
            for call in create_lines.call_args_list
            if call.args[0] == app.REQUEST_LINE_TABLE_NAME
            and call.args[1]
            and "申请数量" in call.args[1][0]
        )
        self.assertEqual(updated_line_fields["申请数量"], 3)
        self.assertEqual(updated_line_fields["实际发放数量"], 3)
        self.assertEqual(created_line_fields["申请数量"], 4)
        self.assertEqual(created_line_fields["实际发放数量"], 4)
        self.assertEqual(created_line_fields["明细编号"], "REQ-1-04")
        request_fields = update_request.call_args.args[2]
        self.assertEqual(
            request_fields["物料明细文字信息"],
            "01. 产品单页 / D7 / 英语 × 3\n02. 产品单页 / T300 / 英语 × 4",
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

    def test_queued_edit_overwrites_manual_review_status_and_version(self) -> None:
        context = {
            "request": {
                "request_no": "REQ-1",
                "status": "已完成",
                "inventory_review_status": app.INVENTORY_REVIEW_CONFIRMED,
                "inventory_review_version": 7,
                "inventory_change_note": "后台人工备注",
            },
            "lines": [{
                "record_id": "line-manually-replaced",
                "line_no": "REQ-1-01",
                "material_record_id": "mat-old",
                "product": "产品单页",
                "model": "D7",
                "language": "英语",
                "quantity": 2,
                "remark": "",
            }],
            "material_rows": [{
                "record_id": "mat-new",
                "fields": {
                    "物料品类": "产品单页",
                    "产品型号": "T300",
                    "语种": "英语",
                    "当前库存": 8,
                },
            }],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
            patch.object(app, "feishu_batch_create_records") as create_records,
            patch.object(app, "feishu_batch_delete_record_ids"),
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "ensure_request_change_record_fields"),
            patch.object(app, "fresh_feishu_rows", return_value=[]),
            patch.object(app, "notify_requester_of_inventory_edit"),
            patch.object(app, "notify_enabled_admins_of_material_request"),
        ):
            result = app.execute_request_inventory_edit({
                "request_id": "request-1",
                "expected_version": 0,
                "operator_open_id": "ou_admin",
                "change_note": "以队列目标覆盖",
                "lines": [{
                    "line_record_id": "line-deleted-by-admin",
                    "material_record_id": "mat-new",
                    "quantity": 4,
                    "remark": "队列值",
                }],
            })

        self.assertEqual(result["version"], 8)
        update_lines.assert_not_called()
        created_line = next(
            call.args[1][0]
            for call in create_records.call_args_list
            if call.args[0] == app.REQUEST_LINE_TABLE_NAME
        )
        self.assertEqual(created_line["申请数量"], 4)
        self.assertEqual(update_request.call_args.args[2]["申请变更次数"], "8")

    def test_allocation_replacement_updates_the_same_detail_record(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "status": app.REQUEST_STATUS_PENDING,
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 0,
            },
            "lines": [{
                "record_id": "line-1",
                "line_no": "REQ-1-03",
                "material_record_id": "mat-old",
                "product": "产品单页",
                "model": "D7",
                "language": "英语",
                "quantity": 2,
                "remark": "",
            }],
            "material_rows": [
                {"record_id": "mat-old", "fields": {"物料品类": "产品单页", "产品型号": "D7", "语种": "英语", "当前库存": 5}},
                {"record_id": "mat-new", "fields": {"物料品类": "产品单页", "产品型号": "T300", "语种": "西语", "当前库存": 8}},
            ],
        }
        with (
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields") as update_lines,
            patch.object(app, "feishu_batch_create_records") as create_lines,
            patch.object(app, "feishu_batch_delete_record_ids") as delete_lines,
            patch.object(app, "feishu_update_record_fields"),
            patch.object(app, "ensure_request_change_record_fields"),
            patch.object(app, "notify_requester_of_inventory_edit"),
            patch.object(app, "notify_enabled_admins_of_material_request"),
        ):
            app.execute_request_inventory_edit({
                "request_id": "request-1",
                "expected_version": 0,
                "operator_open_id": "ou_admin",
                "change_note": "调整配货",
                "lines": [{
                    "line_record_id": "line-1",
                    "material_record_id": "mat-new",
                    "quantity": 4,
                    "remark": "替换",
                }],
            })

        updated = update_lines.call_args.args[1][0]
        self.assertEqual(updated["record_id"], "line-1")
        self.assertEqual(updated["fields"]["申请数量"], 4)
        self.assertEqual(updated["fields"]["物料编码"], ["mat-new"])
        create_lines.assert_called_once()  # Only the immutable change-audit record is created.
        delete_lines.assert_not_called()


if __name__ == "__main__":
    unittest.main()
