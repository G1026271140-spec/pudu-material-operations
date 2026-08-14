from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import app


class GiftProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gift_category = {
            "record_id": "category-gift",
            "fields": {
                "物料品类": "活动徽章",
                "品类定义": app.CATEGORY_DEFINITION_GIFT,
                "启用状态": app.STATUS_ACTIVE,
                "是否无需型号": "是",
                "是否无需语种": "是",
                "单价（美元）": 1.5,
                "单价（人民币）": 10.155,
            },
        }

    def test_gallery_includes_all_gift_definitions_and_joins_project_images(self) -> None:
        categories = [
            self.gift_category,
            {
                "record_id": "category-print",
                "fields": {
                    "物料品类": "宣传单",
                    "品类定义": app.CATEGORY_DEFINITION_PRINT,
                    "启用状态": app.STATUS_ACTIVE,
                },
            },
            {
                "record_id": "category-disabled",
                "fields": {
                    "物料品类": "停用礼品",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                    "启用状态": app.STATUS_INACTIVE,
                },
            },
        ]
        projects = [
            {
                "record_id": "project-line-1",
                "fields": {
                    "项目名称": "深圳展会",
                    "物料名称": "活动徽章",
                    "物料状态": "寻源中",
                    "物料品类关联": ["category-gift"],
                    "物料图片": [
                        {
                            "file_token": "file-1",
                            "name": "badge.webp",
                            "tmp_url": "https://example.com/badge.webp",
                        }
                    ],
                },
            },
            {
                "record_id": "project-line-disabled",
                "fields": {
                    "项目名称": "客户礼赠",
                    "物料名称": "停用礼品",
                    "物料状态": app.GIFT_PROJECT_STATUS_REQUESTED,
                    "物料图片": [
                        {
                            "file_token": "file-disabled",
                            "name": "disabled-gift.webp",
                        }
                    ],
                },
            },
        ]

        gallery = app.gift_gallery_records_from_rows(categories, projects)

        self.assertEqual(
            [item["category"] for item in gallery],
            ["停用礼品", "活动徽章"],
        )
        self.assertEqual(gallery[0]["projects"][0]["project_name"], "客户礼赠")
        self.assertEqual(gallery[1]["projects"][0]["project_name"], "深圳展会")
        self.assertEqual(gallery[0]["attachments"][0]["file_token"], "file-disabled")
        self.assertEqual(gallery[1]["attachments"][0]["file_token"], "file-1")
        self.assertEqual(
            app.filter_gift_gallery_records(gallery, "深圳 寻源"),
            [gallery[1]],
        )
        self.assertEqual(app.filter_gift_gallery_records(gallery, "不存在"), [])

    def test_gallery_and_project_price_use_material_category_relation(self) -> None:
        categories = [
            {
                "record_id": "category-fan",
                "fields": {
                    "物料品类": "手持充电电风扇（充电）",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                    "启用状态": app.STATUS_INACTIVE,
                    "单价（美元）": 3.84,
                    "单价（人民币）": 25.9968,
                },
            }
        ]
        material_rows = [
            {
                "record_id": "material-fan",
                "fields": {
                    "物料编码": "MAT-1143",
                    "物料品类": "电风扇（充电）手持贵的",
                    "品类关联": ["category-fan"],
                },
            }
        ]
        projects = [
            {
                "record_id": "project-fan",
                "fields": {
                    "项目名称": "巴拿马活动",
                    "物料名称": "电风扇（充电）手持贵的",
                    "物料状态": "设计制作中",
                    "物料品类关联": [
                        {
                            "record_ids": None,
                            "table_id": "tbl45q6s50SzEnFI",
                            "text": None,
                            "text_arr": [],
                        }
                    ],
                    "物料图片": [
                        {
                            "file_token": "file-fan",
                            "name": "fan.png",
                            "type": "image/png",
                            "cached_path": "assets/gift_projects/fan.webp",
                        }
                    ],
                },
            }
        ]

        gallery = app.gift_gallery_records_from_rows(categories, projects, material_rows)
        records = app.gift_project_management_records(categories, projects, material_rows)

        self.assertEqual(gallery[0]["projects"][0]["record_id"], "project-fan")
        self.assertEqual(gallery[0]["attachments"][0]["file_token"], "file-fan")
        self.assertEqual(records[0]["matched_category_id"], "category-fan")
        self.assertEqual(records[0]["category"], "手持充电电风扇（充电）")
        self.assertEqual(records[0]["unit_price"], 3.84)
        self.assertEqual(records[0]["unit_price_rmb"], 25.9968)

    def test_project_price_uses_unique_fuzzy_category_match(self) -> None:
        categories = [
            {
                "record_id": "category-fan",
                "fields": {
                    "物料品类": "手持充电电风扇（充电）",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                    "单价（美元）": 3.84,
                    "单价（人民币）": 25.9968,
                },
            },
            {
                "record_id": "category-hat",
                "fields": {
                    "物料品类": "定制帽子",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                    "单价（美元）": 1.77,
                },
            },
        ]
        projects = [
            {
                "record_id": "project-fan",
                "fields": {
                    "项目名称": "巴拿马活动",
                    "物料名称": "电风扇（充电）手持贵的",
                },
            }
        ]

        records = app.gift_project_management_records(categories, projects)

        self.assertEqual(records[0]["matched_category_id"], "category-fan")
        self.assertEqual(records[0]["unit_price"], 3.84)

    def test_project_link_update_uses_best_keyword_fuzzy_match(self) -> None:
        categories = [
            {
                "record_id": "category-paper-bag",
                "fields": {
                    "物料品类": "伴手礼礼包盒（纸袋）",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                },
            },
            {
                "record_id": "category-notebook",
                "fields": {
                    "物料品类": "笔记本礼盒(Notebook Gift Box)",
                    "品类定义": app.CATEGORY_DEFINITION_GIFT,
                },
            },
        ]
        projects = [
            {
                "record_id": "project-bundle",
                "fields": {
                    "项目名称": "巴拿马活动",
                    "物料名称": "伴手礼礼包-笔记本盒套装",
                },
            }
        ]

        updates, stats = app.build_gift_project_category_link_updates(
            categories,
            [],
            projects,
        )

        self.assertEqual(
            updates,
            [
                {
                    "record_id": "project-bundle",
                    "fields": {
                        app.GIFT_PROJECT_CATEGORY_LINK_FIELD: ["category-notebook"],
                    },
                }
            ],
        )
        self.assertEqual(stats["update_count"], 1)

    def test_link_texts_can_match_related_gift_category(self) -> None:
        categories = [self.gift_category]
        projects = [
            {
                "record_id": "project-line-1",
                "fields": {
                    "项目名称": "深圳展会",
                    "物料名称": "展会定制物",
                    "物料状态": "寻源中",
                    "物料品类关联": [
                        {
                            "record_ids": None,
                            "text": "活动徽章",
                            "text_arr": ["活动徽章"],
                        }
                    ],
                },
            }
        ]

        records = app.gift_project_management_records(categories, projects)

        self.assertEqual(records[0]["matched_category_id"], "category-gift")
        self.assertEqual(records[0]["unit_price"], 1.5)

    def test_build_gift_project_category_link_updates_uses_unique_match(self) -> None:
        material_rows = [
            {
                "record_id": "material-gift",
                "fields": {
                    "物料编码": "MAT-0001",
                    "物料品类": "活动徽章别名",
                    "品类关联": ["category-gift"],
                },
            }
        ]
        projects = [
            {
                "record_id": "project-needs-link",
                "fields": {
                    "项目名称": "深圳展会",
                    "物料名称": "活动徽章别名",
                },
            },
            {
                "record_id": "project-already-linked",
                "fields": {
                    "项目名称": "深圳展会",
                    "物料名称": "活动徽章",
                    "物料品类关联": ["category-gift"],
                },
            },
            {
                "record_id": "project-unmatched",
                "fields": {
                    "项目名称": "深圳展会",
                    "物料名称": "不存在的周边",
                },
            },
        ]

        updates, stats = app.build_gift_project_category_link_updates(
            [self.gift_category],
            material_rows,
            projects,
        )

        self.assertEqual(
            updates,
            [
                {
                    "record_id": "project-needs-link",
                    "fields": {
                        app.GIFT_PROJECT_CATEGORY_LINK_FIELD: ["category-gift"],
                    },
                }
            ],
        )
        self.assertEqual(stats["already_linked_count"], 1)
        self.assertEqual(stats["update_count"], 1)
        self.assertEqual(stats["unmatched_count"], 1)

    def test_project_payload_has_fixed_status_relation_and_optional_image(self) -> None:
        fields = app.build_gift_project_fields(
            "新品发布会",
            "活动徽章",
            "category-gift",
            remark="首批需求",
            attachment_token="file-1",
        )

        self.assertEqual(fields["项目名称"], "新品发布会")
        self.assertEqual(fields["物料状态"], app.GIFT_PROJECT_STATUS_REQUESTED)
        self.assertEqual(fields["物料品类关联"], ["category-gift"])
        self.assertEqual(fields["物料图片"], [{"file_token": "file-1"}])

    def test_project_payload_uses_owner_open_id_for_person_field(self) -> None:
        fields = app.build_gift_project_fields(
            "新品发布会",
            "活动徽章",
            "category-gift",
            owner="高鸿源",
            owner_open_id="ou_owner",
        )

        self.assertEqual(fields["负责人"], [{"id": "ou_owner"}])

    def test_project_payload_rejects_free_text_for_person_field(self) -> None:
        with patch.object(app, "feishu_field_type", return_value=11):
            with self.assertRaisesRegex(ValueError, "必须从飞书通讯录中选择"):
                app.build_gift_project_fields(
                    "新品发布会",
                    "活动徽章",
                    "category-gift",
                    owner="高鸿源",
                )

    def test_project_statuses_map_to_progress_stages(self) -> None:
        cases = {
            "已提需": "已提需",
            "寻源中": "寻源中",
            "待确认下单": "待确认下单",
            "设计中": "设计制作中",
            "制作中": "设计制作中",
            "已到货": "到货",
            "在库有库存": "到货",
            "已发货": "已发货",
        }

        self.assertEqual(
            {status: app.gift_project_progress_stage(status) for status in cases},
            cases,
        )

    def test_existing_gift_request_rejects_non_gift_category(self) -> None:
        print_category = {
            **self.gift_category,
            "fields": {
                **self.gift_category["fields"],
                "品类定义": app.CATEGORY_DEFINITION_PRINT,
            },
        }
        with patch.object(app, "fresh_feishu_rows", return_value=[print_category]):
            with self.assertRaisesRegex(ValueError, "不是周边礼品"):
                app.create_gift_project_request("项目A", "category-gift")

    def test_existing_gift_request_writes_only_new_project_table(self) -> None:
        with (
            patch.object(app, "fresh_feishu_rows", return_value=[self.gift_category]),
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "project-line-1"}],
            ) as create_records,
        ):
            result = app.create_gift_project_request(
                "项目A",
                "category-gift",
                remark="需要100个",
            )

        self.assertEqual(result["record_id"], "project-line-1")
        create_records.assert_called_once()
        self.assertEqual(create_records.call_args.args[0], app.GIFT_PROJECT_TABLE_NAME)

    def test_existing_gift_requests_use_one_batch_write(self) -> None:
        second_category = {
            **self.gift_category,
            "record_id": "category-gift-2",
            "fields": {
                **self.gift_category["fields"],
                "物料品类": "定制奖牌",
            },
        }

        with (
            patch.object(
                app,
                "fresh_feishu_rows",
                return_value=[self.gift_category, second_category],
            ),
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[
                    {"record_id": "project-line-1"},
                    {"record_id": "project-line-2"},
                ],
            ) as create_records,
        ):
            created = app.create_gift_project_requests_batch(
                "项目A",
                ["category-gift", "category-gift-2"],
                owner="高鸿源",
                owner_open_id="ou_owner",
            )

        self.assertEqual(len(created), 2)
        create_records.assert_called_once()
        payload = create_records.call_args.args[1]
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["负责人"], [{"id": "ou_owner"}])
        self.assertEqual(payload[1]["负责人"], [{"id": "ou_owner"}])

    def test_collapsed_project_stage_does_not_keep_expanded_grid_height(self) -> None:
        app_source = Path(app.__file__).read_text(encoding="utf-8")

        self.assertIn(
            'details:not([open]) > div {\n            display: none !important;',
            app_source,
        )
        self.assertIn(
            'details[open] {\n            display: grid;',
            app_source,
        )

    def test_remove_gift_batch_selected_item_preserves_other_items(self) -> None:
        session_state: dict[str, object] = {
            "gift_batch_selected_ids": ["gift-3", "gift-1", "gift-2"],
            "gift_batch_new_line": {"name": "待新建礼品", "quantity": 8},
            "gift_batch_project_name": "项目 A",
        }

        remaining = app.remove_gift_batch_selected_item(session_state, "gift-2")

        self.assertEqual(remaining, ["gift-1", "gift-3"])
        self.assertEqual(session_state["gift_batch_selected_ids"], remaining)
        self.assertIn("gift_batch_new_line", session_state)
        self.assertEqual(session_state["gift_batch_project_name"], "项目 A")

    def test_remove_gift_batch_new_item_preserves_existing_selection(self) -> None:
        session_state: dict[str, object] = {
            "gift_batch_selected_ids": ["gift-1", "gift-2"],
            "gift_batch_new_line": {"name": "待新建礼品", "quantity": 8},
        }

        app.remove_gift_batch_new_item(session_state)

        self.assertNotIn("gift_batch_new_line", session_state)
        self.assertEqual(
            session_state["gift_batch_selected_ids"],
            ["gift-1", "gift-2"],
        )

    def test_existing_gift_request_allows_inactive_gift_definition(self) -> None:
        inactive_gift = {
            **self.gift_category,
            "fields": {
                **self.gift_category["fields"],
                "启用状态": app.STATUS_INACTIVE,
            },
        }
        with (
            patch.object(app, "fresh_feishu_rows", return_value=[inactive_gift]),
            patch.object(
                app,
                "feishu_batch_create_records",
                return_value=[{"record_id": "project-inactive-gift"}],
            ) as create_records,
        ):
            result = app.create_gift_project_request("项目C", "category-gift")

        self.assertEqual(result["record_id"], "project-inactive-gift")
        create_records.assert_called_once()

    def test_new_gift_uses_fixed_category_rules_and_requested_status(self) -> None:
        with (
            patch.object(app, "fresh_feishu_rows", return_value=[]),
            patch.object(
                app,
                "sync_feishu_category_inventory",
                return_value={"category_record_id": "category-new"},
            ) as sync_category,
            patch.object(
                app,
                "create_gift_project_request",
                return_value={"record_id": "project-new"},
            ) as create_project,
        ):
            result = app.create_new_gift_project_request(
                "项目B",
                "定制钥匙扣",
                unit_price=2.5,
                attachment_token="file-new",
            )

        sync_kwargs = sync_category.call_args.kwargs
        self.assertEqual(sync_kwargs["category_definition"], app.CATEGORY_DEFINITION_GIFT)
        self.assertTrue(sync_kwargs["no_model"])
        self.assertTrue(sync_kwargs["no_language"])
        self.assertEqual(sync_kwargs["target_models"], [app.NO_MODEL_TEXT])
        self.assertEqual(sync_kwargs["target_languages"], [app.NO_LANGUAGE_TEXT])
        self.assertEqual(
            sync_kwargs["target_values"][(app.NO_MODEL_TEXT, app.NO_LANGUAGE_TEXT)]["quantity"],
            0,
        )
        create_project.assert_called_once_with(
            "项目B",
            "category-new",
            owner="",
            owner_open_id="",
            remark="",
            attachment_token="file-new",
        )
        self.assertEqual(result["project_record"]["record_id"], "project-new")


if __name__ == "__main__":
    unittest.main()
