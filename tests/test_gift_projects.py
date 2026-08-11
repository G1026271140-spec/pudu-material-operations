from __future__ import annotations

import unittest
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
            remark="",
            attachment_token="file-new",
        )
        self.assertEqual(result["project_record"]["record_id"], "project-new")


if __name__ == "__main__":
    unittest.main()
