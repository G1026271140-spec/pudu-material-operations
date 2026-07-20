import unittest

import pandas as pd

import app


def inventory_record(
    record_id: str,
    model: str,
    language: str,
    quantity: int,
    *,
    material_code: str = "",
    unit_price: float = 0,
    customs_code: str = "",
    status: str = app.STATUS_ACTIVE,
) -> dict:
    return {
        "record_id": record_id,
        "material_code": material_code or f"MAT-{record_id}",
        "category": "旧品类",
        "model": model,
        "language": language,
        "quantity": quantity,
        "unit_price": unit_price,
        "remark": "",
        "customs_code": customs_code,
        "status": status,
    }


class CategoryInventoryPlanTests(unittest.TestCase):
    def test_optional_category_unit_price_accepts_blank_and_nonnegative_values(self) -> None:
        self.assertIsNone(app.parse_optional_unit_price(""))
        self.assertEqual(app.parse_optional_unit_price("0"), 0)
        self.assertEqual(app.parse_optional_unit_price("0.06"), 0.06)

    def test_optional_category_unit_price_rejects_invalid_or_negative_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "有效数字"):
            app.parse_optional_unit_price("USD 1")
        with self.assertRaisesRegex(ValueError, "不能小于 0"):
            app.parse_optional_unit_price("-0.01")

    def test_model_rename_updates_all_language_rows_without_recreating_inventory(self) -> None:
        records = [
            inventory_record("1", "BG1", "English", 10, unit_price=12.5, customs_code="HS-1"),
            inventory_record(
                "2",
                "BG1",
                "French",
                20,
                unit_price=15,
                customs_code="HS-2",
                status=app.STATUS_INACTIVE,
            ),
        ]

        plan = app.build_category_inventory_plan(
            records,
            "Existing Category",
            ["BG1 Pro"],
            ["English", "French"],
            model_renames={"BG1": "BG1 Pro"},
        )

        targets = {target["language"]: target for target in plan["targets"]}
        self.assertEqual(plan["create_count"], 0)
        self.assertEqual(plan["delete_count"], 0)
        self.assertEqual(targets["English"]["keeper_id"], "1")
        self.assertEqual(targets["English"]["quantity"], 10)
        self.assertEqual(targets["English"]["unit_price"], 12.5)
        self.assertEqual(targets["French"]["keeper_id"], "2")
        self.assertEqual(targets["French"]["customs_code"], "HS-2")
        self.assertEqual(targets["French"]["status"], app.STATUS_INACTIVE)
        self.assertEqual(
            plan["source_to_target_key"],
            {"1": ("BG1 Pro", "English"), "2": ("BG1 Pro", "French")},
        )

    def test_model_rename_editor_rejects_duplicate_final_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能与其他已有型号重名"):
            app.category_model_rename_values(
                pd.DataFrame(
                    [
                        {"当前型号": "M1", "修改后型号": "M2"},
                        {"当前型号": "M2", "修改后型号": "M2"},
                    ]
                )
            )

    def test_model_rename_editor_returns_only_changed_models(self) -> None:
        renames = app.category_model_rename_values(
            pd.DataFrame(
                [
                    {"当前型号": "M1", "修改后型号": "M1 Pro"},
                    {"当前型号": "M2", "修改后型号": "M2"},
                ]
            )
        )

        self.assertEqual(renames, {"M1": "M1 Pro"})

    def test_model_rename_editor_rejects_reserved_no_model_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "无需产品型号"):
            app.category_model_rename_values(
                pd.DataFrame(
                    [{"当前型号": "M1", "修改后型号": app.NO_MODEL_TEXT}]
                )
            )

    def test_rename_preserves_existing_combinations(self) -> None:
        records = [
            inventory_record("1", "M1", "英语", 10),
            inventory_record("2", "M2", "英语", 20),
        ]

        plan = app.build_category_inventory_plan(records, "新品类", ["M1", "M2"], ["英语"])

        self.assertEqual(plan["target_count"], 2)
        self.assertEqual(plan["create_count"], 0)
        self.assertEqual(plan["delete_count"], 0)
        self.assertEqual([target["quantity"] for target in plan["targets"]], [10, 20])

    def test_collapsing_models_sums_stock_and_prefers_referenced_keeper(self) -> None:
        records = [
            inventory_record("1", "M1", "英语", 5, material_code="MAT-0001"),
            inventory_record("2", "M2", "英语", 7, material_code="MAT-0002"),
        ]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            [app.NO_MODEL_TEXT],
            ["英语"],
            referenced_ids={"2"},
        )

        target = plan["targets"][0]
        self.assertEqual(target["quantity"], 12)
        self.assertEqual(target["keeper_id"], "2")
        self.assertEqual(plan["delete_ids"], ["1"])

    def test_expanding_no_model_uses_carrier_and_custom_new_stock(self) -> None:
        records = [inventory_record("1", app.NO_MODEL_TEXT, "英语", 8)]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["M1", "M2"],
            ["英语"],
            carry_model="M2",
            initial_quantities={("M1", "英语"): -3},
        )

        targets = {target["key"]: target for target in plan["targets"]}
        self.assertEqual(targets[("M1", "英语")]["quantity"], -3)
        self.assertTrue(targets[("M1", "英语")]["is_new"])
        self.assertEqual(targets[("M2", "英语")]["quantity"], 8)
        self.assertFalse(targets[("M2", "英语")]["is_new"])

    def test_collapsing_languages_preserves_total_value(self) -> None:
        records = [
            inventory_record("1", "M1", "英语", 3, unit_price=10),
            inventory_record("2", "M1", "中文", 1, unit_price=30),
        ]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["M1"],
            [app.NO_LANGUAGE_TEXT],
        )

        target = plan["targets"][0]
        self.assertEqual(target["quantity"], 4)
        self.assertEqual(target["unit_price"], 15)
        self.assertEqual(plan["delete_count"], 1)

    def test_target_values_allow_custom_quantity_split_price_and_customs_code(self) -> None:
        records = [inventory_record("1", app.NO_MODEL_TEXT, "英语", 100, unit_price=8)]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["M1", "M2"],
            ["英语"],
            carry_model="M1",
            target_values={
                ("M1", "英语"): {"quantity": 40, "unit_price": 6.5, "customs_code": "HS-1"},
                ("M2", "英语"): {"quantity": 60, "unit_price": 7.5, "customs_code": ""},
            },
        )

        targets = {target["key"]: target for target in plan["targets"]}
        self.assertEqual(targets[("M1", "英语")]["quantity"], 40)
        self.assertEqual(targets[("M1", "英语")]["unit_price"], 6.5)
        self.assertEqual(targets[("M1", "英语")]["customs_code"], "HS-1")
        self.assertEqual(targets[("M2", "英语")]["quantity"], 60)
        self.assertEqual(plan["quantity_difference"], 0)
        self.assertEqual(plan["discarded_quantity"], 0)

    def test_target_values_allow_unallocated_inventory_to_be_discarded(self) -> None:
        records = [inventory_record("1", "M1", "英语", 100)]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["M1"],
            ["英语"],
            target_values={("M1", "英语"): {"quantity": 25, "unit_price": None, "customs_code": None}},
        )

        self.assertEqual(plan["current_quantity"], 100)
        self.assertEqual(plan["target_quantity"], 25)
        self.assertEqual(plan["quantity_difference"], -75)
        self.assertEqual(plan["discarded_quantity"], 75)
        self.assertEqual(plan["targets"][0]["unit_price"], 0.0)
        self.assertEqual(plan["targets"][0]["customs_code"], "")

    def test_editor_values_require_quantity_and_allow_optional_price_and_customs_code(self) -> None:
        values = app.category_inventory_target_values(
            pd.DataFrame(
                [
                    {
                        "产品型号": "M1",
                        "语种": "英语",
                        "库存数量": -10,
                        "单价": None,
                        "海关编码": None,
                    }
                ]
            )
        )

        self.assertEqual(
            values,
            {
                ("M1", "英语"): {
                    "quantity": -10,
                    "unit_price": 0.0,
                    "customs_code": "",
                    "status": app.STATUS_ACTIVE,
                }
            },
        )

    def test_inventory_status_is_preserved_and_can_be_overridden(self) -> None:
        records = [inventory_record("1", "M1", "英语", 100, status=app.STATUS_INACTIVE)]

        original_plan = app.build_category_inventory_plan(records, "旧品类", ["M1"], ["英语"])
        enabled_plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["M1"],
            ["英语"],
            target_values={
                ("M1", "英语"): {
                    "quantity": 100,
                    "unit_price": 0,
                    "customs_code": "",
                    "status": app.STATUS_ACTIVE,
                }
            },
        )

        self.assertEqual(original_plan["targets"][0]["status"], app.STATUS_INACTIVE)
        self.assertEqual(enabled_plan["targets"][0]["status"], app.STATUS_ACTIVE)

    def test_inactive_category_forces_all_inventory_targets_inactive(self) -> None:
        records = [inventory_record("1", "M1", "英语", 100, status=app.STATUS_ACTIVE)]
        plan = app.build_category_inventory_plan(records, "旧品类", ["M1", "M2"], ["英语"])

        enforced = app.enforce_category_inventory_status(plan, app.STATUS_INACTIVE)

        self.assertEqual(
            {target["status"] for target in enforced["targets"]},
            {app.STATUS_INACTIVE},
        )

    def test_relation_updates_repoint_deleted_material_ids(self) -> None:
        rows = [
            {
                "record_id": "line-1",
                "fields": {
                    "物料编码": [{"record_id": "source-1"}],
                    "其他关联": [{"record_id": "unchanged"}],
                },
            }
        ]

        updates = app.build_material_relation_updates(
            rows,
            {"source-1": "keeper-1"},
            ["物料编码", "其他关联"],
        )

        self.assertEqual(
            updates,
            [{"record_id": "line-1", "fields": {"物料编码": ["keeper-1"]}}],
        )


if __name__ == "__main__":
    unittest.main()
