import unittest
from unittest.mock import MagicMock, patch

import app
import submission_queue as queue


class CulturalRequestTests(unittest.TestCase):
    def test_cultural_request_total_quantity_is_limited_to_two(self) -> None:
        self.assertEqual(
            app.validate_cultural_request_quantity(
                [{"quantity": 1}, {"quantity": 1}]
            ),
            2,
        )
        with self.assertRaisesRegex(RuntimeError, "最多申领 2 件"):
            app.validate_cultural_request_quantity(
                [{"quantity": 2}, {"quantity": 1}]
            )

    def test_cultural_request_quota_uses_open_id_and_cumulative_quantity(self) -> None:
        permission_rows = [
            {
                "record_id": "rec-permission",
                "fields": {
                    "用户账号": [{"id": "ou_requester"}],
                    "文化衫申领数量累计": 1,
                },
            }
        ]
        with (
            patch.object(app, "ensure_requester_sales_permission", return_value="existing"),
            patch.object(app, "refresh_feishu_schema_cache"),
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "fresh_feishu_rows", return_value=permission_rows),
        ):
            quota = app.cultural_request_quota_snapshot(
                {"requester_open_id": "ou_requester"}, [{"quantity": 2}]
            )

        self.assertEqual(quota["current_quantity"], 1)
        self.assertEqual(quota["target_quantity"], 3)
        self.assertFalse(quota["allowed"])

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
            {"record_id": "cul1", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "8", "是否可申领": "是", "单价（人民币）": 78}},
            {"record_id": "cul-hidden", "fields": {"物料品类": "文化夹克", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "5", "是否可申领": "是"}},
            {"record_id": "cul2", "fields": {"物料品类": "产品单页", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "99", "是否可申领": "是"}},
        ]
        catalog = app.cultural_request_catalog(culture, categories, models)
        self.assertEqual(catalog["products"], ["文化POLO衫"])
        self.assertEqual(catalog["combinations"][("文化POLO衫", "M", "美洲战区")]["stock"], 8)
        self.assertNotIn(("文化夹克", "M", "美洲战区"), catalog["combinations"])

    def test_catalog_hides_combination_marked_not_claimable(self) -> None:
        categories = [{"record_id": "cat1", "fields": {"物料品类": "文化POLO衫", "品类定义": "文化周边", "是否在申领页显示": "是"}}]
        culture = [
            {"record_id": "yes", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": 2, "是否可申领": "是"}},
            {"record_id": "no", "fields": {"物料品类": "文化POLO衫", "产品型号": "L", "战区管理": "美洲战区", "当前库存": 2, "是否可申领": "否"}},
        ]
        catalog = app.cultural_request_catalog(culture, categories, [])
        self.assertIn(("文化POLO衫", "M", "美洲战区"), catalog["combinations"])
        self.assertNotIn(("文化POLO衫", "L", "美洲战区"), catalog["combinations"])

    def test_claimability_sync_only_forces_nonpositive_stock_to_no(self) -> None:
        rows = [
            {"record_id": "zero", "fields": {"当前库存": 0, "是否可申领": "是"}},
            {"record_id": "manual-no", "fields": {"当前库存": 5, "是否可申领": "否"}},
        ]
        with patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update:
            result = app.sync_cultural_material_claimability(rows)
        self.assertEqual(result, {"checked_count": 2, "updated_count": 1})
        self.assertEqual(update.call_args.args[1], [{"record_id": "zero", "fields": {"是否可申领": "否"}}])

    def test_queue_payload_keeps_cultural_dimensions(self) -> None:
        payload = app.queued_cultural_request_payload(
            {"requester": "申请人", "requester_open_id": "ou_test", "submission_token": "token"},
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 2, "remark": "test"}],
        )
        self.assertEqual(queue.QUEUE_TASK_TYPE_CULTURAL_REQUEST, "文化周边申领")
        self.assertEqual(payload["lines"][0]["region"], "欧洲战区")
        self.assertEqual(payload["lines"][0]["quantity"], 2)

    def test_applicant_card_mentions_enabled_admins(self) -> None:
        card = app._cultural_request_card(
            "REQ-1",
            "申请人",
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 2}],
            applicant=True,
            admin_open_ids=["ou_admin_1", "ou_admin_2"],
        )
        content = card["body"]["elements"][0]["content"]
        self.assertIn("<at id=ou_admin_1></at>", content)
        self.assertIn("<at id=ou_admin_2></at>", content)
        self.assertNotIn("@管理员", content)

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
        details = card["body"]["elements"][2]["content"]
        self.assertIn("领取后剩余库存：-1", details)

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
