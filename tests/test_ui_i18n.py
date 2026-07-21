from __future__ import annotations

import unittest

import pandas as pd

from ui_i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH,
    localize_column_config,
    normalize_ui_language,
    translate_ui_text,
)


class UiInternationalizationTests(unittest.TestCase):
    def test_language_normalization_defaults_to_chinese(self) -> None:
        self.assertEqual(normalize_ui_language("en"), LANGUAGE_EN)
        self.assertEqual(normalize_ui_language("EN"), LANGUAGE_EN)
        self.assertEqual(normalize_ui_language("zh"), LANGUAGE_ZH)
        self.assertEqual(normalize_ui_language("unexpected"), LANGUAGE_ZH)

    def test_ui_copy_translates_without_changing_business_values(self) -> None:
        self.assertEqual(translate_ui_text("审批与发放", LANGUAGE_EN), "Approval & Issuance")
        self.assertEqual(
            translate_ui_text("客户：Impact；国家：USA；申请人：高鸿源；部门：市场营销部", LANGUAGE_EN),
            "Customer: Impact; Country: USA; Applicant: 高鸿源; Department: 市场营销部",
        )
        self.assertEqual(
            translate_ui_text("产品折页(Single Product Brochure)", LANGUAGE_EN),
            "产品折页(Single Product Brochure)",
        )

    def test_chinese_mode_normalizes_bilingual_ui_headers_only(self) -> None:
        self.assertEqual(translate_ui_text("客户名称 Customer Name", LANGUAGE_ZH), "客户名称")
        self.assertEqual(translate_ui_text("库存登记", LANGUAGE_ZH), "物料申领")
        self.assertEqual(
            translate_ui_text("产品折页(Single Product Brochure)", LANGUAGE_ZH),
            "产品折页(Single Product Brochure)",
        )

    def test_dashboard_copy_translates_without_changing_filter_values(self) -> None:
        self.assertEqual(
            translate_ui_text("库存数据看板", LANGUAGE_EN),
            "Inventory Dashboard",
        )
        self.assertEqual(
            translate_ui_text("负库存", LANGUAGE_EN),
            "Negative Inventory",
        )
        self.assertEqual(
            translate_ui_text("产品折页(Single Product Brochure)", LANGUAGE_EN),
            "产品折页(Single Product Brochure)",
        )

    def test_category_inventory_reconfiguration_copy_is_translated(self) -> None:
        self.assertEqual(
            translate_ui_text("库存组合明细", LANGUAGE_EN),
            "Inventory Combination Details",
        )
        self.assertEqual(
            translate_ui_text("确认直接舍弃未分配库存", LANGUAGE_EN),
            "Confirm discarding unallocated inventory",
        )
        self.assertEqual(
            translate_ui_text(
                "将直接舍弃 75 件未分配库存，此操作保存后不可自动恢复。",
                LANGUAGE_EN,
            ),
            "75 units of unallocated inventory will be discarded and cannot be restored automatically after saving.",
        )
        self.assertEqual(
            translate_ui_text("批量设置启用状态", LANGUAGE_EN),
            "Set Status in Bulk",
        )
        self.assertEqual(
            translate_ui_text("启用库存组合 12 条；停用库存组合 3 条。", LANGUAGE_EN),
            "Active inventory combinations: 12; inactive combinations: 3.",
        )

    def test_active_inventory_alert_copy_is_translated(self) -> None:
        self.assertEqual(
            translate_ui_text(
                "发现 8 条启用库存预警：负库存 2 条，零库存 1 条，低库存 5 条。",
                LANGUAGE_EN,
            ),
            "Found 8 alerts among active inventory: 2 negative, 1 zero, and 5 low-inventory rows.",
        )

    def test_inventory_maintenance_refresh_result_is_translated(self) -> None:
        self.assertEqual(
            translate_ui_text(
                "全部页面数据已同步，共 681 条记录；自动启用 2 条，自动停用 3 条。",
                LANGUAGE_EN,
            ),
            (
                "All page data is synced. 681 records loaded; "
                "2 automatically enabled and 3 automatically disabled."
            ),
        )

    def test_column_localization_does_not_rename_or_modify_data(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "物料品类(Material Category)": "产品折页(Single Product Brochure)",
                    "申请数量": 25,
                }
            ]
        )
        original_columns = list(source.columns)
        original_values = source.to_dict("records")
        config = {
            "申请数量": {
                "label": "申请数量",
                "help": "填写实际发放数量并保存后，系统会按该数量更新物料库存。",
                "type_config": {"type": "number"},
            }
        }

        localized = localize_column_config(source, config, LANGUAGE_EN)

        self.assertEqual(list(source.columns), original_columns)
        self.assertEqual(source.to_dict("records"), original_values)
        self.assertEqual(localized["物料品类(Material Category)"]["label"], "Material Category")
        self.assertEqual(localized["申请数量"]["label"], "Requested Quantity")
        self.assertIn("update material inventory", localized["申请数量"]["help"])
        self.assertEqual(localized["申请数量"]["type_config"], {"type": "number"})
        self.assertEqual(config["申请数量"]["label"], "申请数量")


if __name__ == "__main__":
    unittest.main()
