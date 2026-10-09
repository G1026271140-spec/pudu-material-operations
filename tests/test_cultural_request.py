import unittest
import base64
from unittest.mock import MagicMock, patch

import app
import submission_queue as queue


class CulturalRequestTests(unittest.TestCase):
    def test_corporate_apparel_source_record_id_decodes_sync_source_id(self) -> None:
        encoded = base64.b64encode(
            b"7694548691520179411:recvexample123:checksum:1"
        ).decode("ascii")

        self.assertEqual(
            app.corporate_apparel_source_record_id(encoded),
            "recvexample123",
        )
        self.assertEqual(app.corporate_apparel_source_record_id("invalid"), "")

    def test_corporate_catalog_uses_fresh_source_stock_over_sync_snapshot(self) -> None:
        encoded = base64.b64encode(b"1:recsource:checksum:1").decode("ascii")
        synced = [{
            "record_id": "recsync",
            "fields": {
                "SourceID": encoded,
                "款式": "文化衫-休闲商务POLO-黑色（短袖）",
                "码数": "XL",
                "最新库存": 3,
                "系统兑换数量": 0,
            },
        }]
        source = [{
            "record_id": "recsource",
            "fields": {
                "款式": "文化衫-休闲商务POLO-黑色（短袖）",
                "码数": "XL",
                "最新库存": 3,
                "系统兑换数量": 1,
            },
        }]

        item = app.corporate_apparel_catalog(synced, source_rows=source)["items"][0]

        self.assertEqual(item["system_redeemed"], 1)
        self.assertEqual(item["available"], 2)

    def test_corporate_apparel_redeemed_updates_writable_source_table(self) -> None:
        source_client = MagicMock()
        with patch.object(app, "corporate_apparel_source_client", return_value=source_client):
            app.update_corporate_apparel_source_redeemed(
                {"source_record_id": "recvsource"},
                3,
            )

        source_client.update_record.assert_called_once_with(
            app.CORPORATE_APPAREL_SOURCE_TABLE_ID,
            "recvsource",
            {"系统兑换数量": 3},
        )

    def test_corporate_apparel_cached_quota_combines_polo_sizes(self) -> None:
        permission_rows = [{
            "record_id": "permission-1",
            "fields": {
                "用户账号": [{"id": "ou_requester"}],
                "POLO申领数量累计": 1,
            },
        }]

        with self.assertRaisesRegex(RuntimeError, "当前已领取 1 件.*本次最多还能领取 1 件"):
            app.validate_corporate_apparel_cached_quota(
                "ou_requester",
                [
                    {"product": "休闲商务POLO-黑色（短袖）", "size": "M", "quantity": 1},
                    {"product": "休闲商务POLO-黑色（短袖）", "size": "L", "quantity": 1},
                ],
                permission_rows,
            )

    def test_corporate_apparel_cached_quota_allows_two_polo_items_for_new_user(self) -> None:
        snapshots = app.validate_corporate_apparel_cached_quota(
            "ou_new",
            [
                {"product": "休闲商务POLO-黑色（短袖）", "size": "M", "quantity": 1},
                {"product": "休闲商务POLO-黑色（短袖）", "size": "L", "quantity": 1},
            ],
            [],
        )

        self.assertEqual(snapshots[0]["requested"], 2)
        self.assertEqual(snapshots[0]["target"], 2)
        self.assertEqual(snapshots[0]["limit"], 2)

    def test_cultural_shirts_and_jacket_have_independent_limits(self) -> None:
        self.assertEqual(
            app.validate_cultural_request_quantity(
                [
                    {"product": "文化POLO衫", "quantity": 2},
                    {"product": "文化夹克", "quantity": 1},
                ]
            ),
            3,
        )
        with self.assertRaisesRegex(RuntimeError, "最多申领 2 件文化衫"):
            app.validate_cultural_request_quantity(
                [{"product": "文化POLO衫", "quantity": 3}]
            )
        with self.assertRaisesRegex(RuntimeError, "最多申领 1 件文化夹克"):
            app.validate_cultural_request_quantity(
                [{"product": "文化夹克", "quantity": 2}]
            )

    def test_cultural_request_quota_uses_open_id_and_cumulative_quantity(self) -> None:
        permission_rows = [
            {
                "record_id": "rec-permission",
                "fields": {
                    "用户账号": [{"id": "ou_requester"}],
                    "POLO申领数量累计": 1,
                    "文化夹克申领数量累计": 0,
                },
            }
        ]
        with (
            patch.object(app, "ensure_requester_sales_permission", return_value="existing"),
            patch.object(app, "ensure_cultural_request_quota_fields"),
            patch.object(app, "fresh_feishu_rows", return_value=permission_rows),
        ):
            quota = app.cultural_request_quota_snapshot(
                {"requester_open_id": "ou_requester"},
                [{"product": "文化POLO衫", "quantity": 2}],
            )

        self.assertEqual(quota["current_quantity"], 1)
        self.assertEqual(quota["target_quantity"], 3)
        self.assertFalse(quota["allowed"])

    def test_jacket_quota_is_cumulative_and_independent(self) -> None:
        permission_rows = [{
            "record_id": "rec-permission",
            "fields": {
                "用户账号": [{"id": "ou_requester"}],
                "POLO申领数量累计": 0,
                "文化夹克申领数量累计": 1,
            },
        }]
        with (
            patch.object(app, "ensure_requester_sales_permission", return_value="existing"),
            patch.object(app, "ensure_cultural_request_quota_fields"),
            patch.object(app, "fresh_feishu_rows", return_value=permission_rows),
        ):
            quota = app.cultural_request_quota_snapshot(
                {"requester_open_id": "ou_requester"},
                [{"product": "文化夹克", "quantity": 1}],
            )
        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["quota_label"], "文化夹克")
        self.assertEqual(quota["quota_limit"], 1)

    def test_rejection_card_explains_limit_and_mentions_admin(self) -> None:
        card = app._cultural_request_rejection_card(
            "申请人",
            2,
            1,
            applicant=True,
            admin_open_ids=["ou_admin"],
        )
        content = "\n".join(item.get("content", "") for item in card["body"]["elements"])
        self.assertIn("已驳回", content)
        self.assertIn("历史累计已申领 2 件", content)
        self.assertIn("<at id=ou_admin></at>", content)

    def test_cultural_sizes_follow_business_order(self) -> None:
        sizes = ["2XL", "3XL", "4XL", "6XL", "L", "M", "S", "XL"]
        self.assertEqual(
            sorted(sizes, key=app.cultural_size_sort_key),
            ["S", "M", "L", "XL", "2XL", "3XL", "4XL", "6XL"],
        )

    def test_direct_route_opens_cultural_request_page(self) -> None:
        query_params = {"section": "cultural_request"}
        session_state: dict[str, object] = {}
        with (
            patch.object(app.st, "query_params", query_params),
            patch.object(app.st, "session_state", session_state),
        ):
            selected = app.apply_management_section_from_query()

        self.assertEqual(selected, "文化周边申领")
        self.assertEqual(
            session_state[app.MANAGEMENT_NAVIGATION_KEY],
            "文化周边申领",
        )

    def test_catalog_only_includes_cultural_categories(self) -> None:
        categories = [
            {"record_id": "cat1", "fields": {"物料品类": "文化POLO衫", "品类定义": "文化周边", "是否在申领页显示": "是", "中文页面名称": "文化POLO衫", "英文页面名称": "Cultural Polo Shirt"}},
            {"record_id": "cat-hidden", "fields": {"物料品类": "文化夹克", "品类定义": "文化周边", "是否在申领页显示": "否"}},
            {"record_id": "cat2", "fields": {"物料品类": "产品单页", "品类定义": "印刷物料"}},
        ]
        models = [{"record_id": "mod1", "fields": {"产品型号": "M"}}]
        culture = [
            {"record_id": "cul1", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "8", "是否可以申领": "是", "单价（人民币）": 78}},
            {"record_id": "cul-hidden", "fields": {"物料品类": "文化夹克", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "5", "是否可以申领": "是"}},
            {"record_id": "cul2", "fields": {"物料品类": "产品单页", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "99", "是否可以申领": "是"}},
        ]
        catalog = app.cultural_request_catalog(culture, categories, models)
        self.assertEqual(catalog["products"], ["文化POLO衫"])
        self.assertEqual(catalog["combinations"][("文化POLO衫", "M", "美洲战区")]["stock"], 8)
        self.assertNotIn(("文化夹克", "M", "美洲战区"), catalog["combinations"])

        admin_catalog = app.cultural_request_catalog(
            culture,
            categories,
            models,
            include_all_categories_for_admin=True,
        )
        self.assertIn(("文化夹克", "M", "美洲战区"), admin_catalog["combinations"])

    def test_catalog_hides_combination_marked_not_claimable(self) -> None:
        categories = [{"record_id": "cat1", "fields": {"物料品类": "文化POLO衫", "品类定义": "文化周边", "是否在申领页显示": "是"}}]
        culture = [
            {"record_id": "yes", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": 2, "是否可以申领": "是"}},
            {"record_id": "no", "fields": {"物料品类": "文化POLO衫", "产品型号": "L", "战区管理": "美洲战区", "当前库存": 2, "是否可以申领": "否"}},
        ]
        catalog = app.cultural_request_catalog(culture, categories, [])
        self.assertIn(("文化POLO衫", "M", "美洲战区"), catalog["combinations"])
        self.assertNotIn(("文化POLO衫", "L", "美洲战区"), catalog["combinations"])

        persistence_catalog = app.cultural_request_catalog(
            culture,
            categories,
            [],
            include_all_categories_for_admin=True,
            include_unclaimable_combinations=True,
        )
        self.assertIn(
            ("文化POLO衫", "L", "美洲战区"),
            persistence_catalog["combinations"],
        )

    def test_claimability_sync_initializes_blank_positive_stock_and_forces_nonpositive_to_no(self) -> None:
        rows = [
            {"record_id": "zero", "fields": {"当前库存": 0, "是否可以申领": "是"}},
            {"record_id": "blank-positive", "fields": {"当前库存": 5}},
            {"record_id": "manual-no", "fields": {"当前库存": 5, "是否可以申领": "否"}},
        ]
        with patch.object(app, "feishu_batch_update_record_fields", return_value=2) as update:
            result = app.sync_cultural_material_claimability(rows)
        self.assertEqual(result, {"checked_count": 3, "updated_count": 2})
        self.assertEqual(update.call_args.args[1], [
            {"record_id": "zero", "fields": {"是否可以申领": "否"}},
            {"record_id": "blank-positive", "fields": {"是否可以申领": "是"}},
        ])

    def test_queue_payload_keeps_cultural_dimensions(self) -> None:
        payload = app.queued_cultural_request_payload(
            {
                "requester": "申请人",
                "requester_open_id": "ou_test",
                "material_usage": "深圳展会",
                "submission_token": "token",
            },
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 1, "remark": "test"}],
        )
        self.assertEqual(queue.QUEUE_TASK_TYPE_CULTURAL_REQUEST, "文化周边申领")
        self.assertEqual(payload["lines"][0]["region"], "欧洲战区")
        self.assertEqual(payload["lines"][0]["quantity"], 1)
        self.assertEqual(payload["request_payload"]["material_usage"], "深圳展会")

        override_payload = app.queued_cultural_request_payload(
            {"requester": "管理员", "requester_open_id": "ou_admin", "submission_token": "token", "administrator_override": True},
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 1}],
        )
        self.assertTrue(override_payload["request_payload"]["administrator_override"])

    def test_applicant_card_mentions_enabled_admins(self) -> None:
        card = app._cultural_request_card(
            "REQ-1",
            "申请人",
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 1}],
            applicant=True,
            admin_open_ids=["ou_admin_1", "ou_admin_2"],
        )
        content = card["body"]["elements"][0]["content"]
        self.assertIn("<at id=ou_admin_1></at>", content)
        self.assertIn("<at id=ou_admin_2></at>", content)
        self.assertNotIn("@管理员", content)
        details = card["body"]["elements"][3]
        self.assertNotIn("remaining_stock", details["rows"][0])
        self.assertNotIn(
            "remaining_stock", [column["name"] for column in details["columns"]]
        )

    def test_cultural_request_card_shows_material_usage(self) -> None:
        card = app._cultural_request_card(
            "REQ-1",
            "申请人",
            [{"product": "文化POLO衫", "model": "M", "region": "中国", "quantity": 1}],
            applicant=True,
            material_usage="上海国际展会",
        )

        self.assertIn("**文化衫用途**：上海国际展会", card["body"]["elements"][2]["content"])

    def test_admin_card_shows_stock_after_claim(self) -> None:
        card = app._cultural_request_card(
            "REQ-1",
            "申请人",
            [{
                "product": "文化POLO衫", "model": "2XL", "region": "美洲战区",
                "quantity": 1, "remaining_stock": -1,
            }],
            applicant=False,
        )
        details = card["body"]["elements"][3]
        self.assertEqual(details["tag"], "table")
        self.assertEqual(details["columns"][0]["width"], "80px")
        self.assertEqual(details["rows"][0]["remaining_stock"], -1)
        self.assertIn("领取后库存", [item["display_name"] for item in details["columns"]])

    def test_only_admin_cultural_card_has_manual_reject_button(self) -> None:
        lines = [{
            "product": "文化POLO衫",
            "model": "M",
            "region": "美洲战区",
            "quantity": 1,
        }]
        admin_card = app._cultural_request_card(
            "REQ-1", "申请人", lines, applicant=False
        )
        applicant_card = app._cultural_request_card(
            "REQ-1", "申请人", lines, applicant=True
        )

        reject_button = admin_card["body"]["elements"][-1]
        self.assertEqual(reject_button["tag"], "button")
        self.assertEqual(reject_button["type"], "danger_filled")
        self.assertEqual(
            reject_button["value"],
            {"action": "reject_cultural_request", "request_no": "REQ-1"},
        )
        self.assertNotIn("reject_cultural_request", str(applicant_card))

    def test_cultural_request_rejection_restores_inventory_and_marks_lines(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "requester": "申请人",
                "requester_open_id": "ou-user",
                "status": app.CULTURAL_REQUEST_STATUS_ISSUED,
            },
            "lines": [{
                "record_id": "line-1",
                "product": "文化POLO衫",
                "model": "M",
                "region": "美洲战区",
                "quantity": 2,
                "culture_record_ids": ["culture-1"],
            }],
        }
        culture_rows = [{"record_id": "culture-1", "fields": {"当前库存": 0}}]

        def fresh_rows(table_name: str) -> list[dict]:
            if table_name == app.CULTURAL_MATERIAL_TABLE_NAME:
                return culture_rows
            if table_name == app.LEDGER_TABLE_NAME:
                return []
            return []

        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou-admin"]),
            patch.object(app, "ensure_cultural_request_workflow_fields"),
            patch.object(app, "cultural_request_context", return_value=context),
            patch.object(app, "fresh_feishu_rows", side_effect=fresh_rows),
            patch.object(app, "feishu_create_record", return_value={"record_id": "ledger-1"}) as create,
            patch.object(app, "feishu_update_record_fields") as update,
            patch.object(app, "feishu_datetime_value", return_value=123),
            patch.object(
                app,
                "recalculate_cultural_request_quota",
                return_value={"shirt_quantity": 0, "jacket_quantity": 0},
            ) as quota,
        ):
            result = app.execute_cultural_request_rejection({
                "request_no": "REQ-1",
                "operator_open_id": "ou-admin",
            })

        self.assertTrue(result["rejected"])
        self.assertEqual(result["restored_quantity"], 2)
        self.assertEqual(create.call_args.args[0], app.LEDGER_TABLE_NAME)
        self.assertEqual(create.call_args.args[1]["库存变化"], 2)
        self.assertIn(
            (
                app.CULTURAL_MATERIAL_TABLE_NAME,
                "culture-1",
                {"当前库存": 2, app.CULTURAL_CLAIMABLE_FIELD: app.CULTURAL_CLAIMABLE_YES},
            ),
            [call.args for call in update.call_args_list],
        )
        self.assertIn(
            (
                app.REQUEST_LINE_TABLE_NAME,
                "line-1",
                {"审批通过数量": 0, "实际发放数量": 0, "明细状态": "已驳回"},
            ),
            [call.args for call in update.call_args_list],
        )
        quota.assert_called_once_with("ou-user")

    def test_request_page_does_not_show_stock_caption(self) -> None:
        source = open(app.__file__, encoding="utf-8").read()
        self.assertNotIn("当前库存：{int(selected_item['stock'])}（允许负库存）", source)

    def test_cultural_request_writes_request_summary_and_single_select_region(self) -> None:
        source = open(app.__file__, encoding="utf-8").read()
        self.assertIn('"物料明细文字信息": detail_text', source)
        self.assertIn('"所属战区": request_regions', source)
        self.assertNotIn('"战区关联": [region_id]', source)


if __name__ == "__main__":
    unittest.main()
