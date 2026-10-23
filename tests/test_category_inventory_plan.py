import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_new_category_preview_lists_every_target_and_keeps_quantities(self) -> None:
        plan = app.build_category_inventory_plan(
            [],
            "新品类",
            ["M1", "M2"],
            ["英语", "韩语"],
            target_values={
                ("M1", "英语"): {"quantity": 10, "unit_price": 1.5},
                ("M1", "韩语"): {"quantity": -2, "unit_price": 2.5},
                ("M2", "英语"): {"quantity": 30, "unit_price": 3.5},
                ("M2", "韩语"): {"quantity": 40, "unit_price": 4.5},
            },
        )

        preview = app.category_inventory_preview_dataframe(plan["targets"])

        self.assertEqual(len(preview), 4)
        self.assertEqual(preview["序号"].tolist(), [1, 2, 3, 4])
        self.assertEqual(preview["库存数量"].tolist(), [10, -2, 30, 40])
        self.assertEqual(
            list(zip(preview["产品型号"], preview["语种"])),
            [("M1", "英语"), ("M1", "韩语"), ("M2", "英语"), ("M2", "韩语")],
        )

    def test_new_category_preview_values_use_each_edited_quantity(self) -> None:
        preview = pd.DataFrame(
            [
                {
                    "序号": 1,
                    "产品型号": "M1",
                    "语种": "英语",
                    "库存数量": 25,
                    "单价": 1.25,
                    "海关编码": "HS-1",
                    "启用状态": app.STATUS_ACTIVE,
                },
                {
                    "序号": 2,
                    "产品型号": "M2",
                    "语种": "韩语",
                    "库存数量": -5,
                    "单价": 0,
                    "海关编码": "",
                    "启用状态": app.STATUS_INACTIVE,
                },
            ]
        )

        values = app.category_inventory_preview_values(
            preview,
            [("M1", "英语"), ("M2", "韩语")],
            app.STATUS_ACTIVE,
        )

        self.assertEqual(values[("M1", "英语")]["quantity"], 25)
        self.assertEqual(values[("M1", "英语")]["unit_price"], 1.25)
        self.assertEqual(values[("M1", "英语")]["customs_code"], "HS-1")
        self.assertEqual(values[("M2", "韩语")]["quantity"], -5)
        self.assertEqual(values[("M2", "韩语")]["status"], app.STATUS_INACTIVE)

    def test_inactive_new_category_forces_all_preview_rows_inactive(self) -> None:
        preview = pd.DataFrame(
            [
                {
                    "产品型号": "M1",
                    "语种": "英语",
                    "库存数量": 10,
                    "单价": 0,
                    "海关编码": "",
                    "启用状态": app.STATUS_ACTIVE,
                }
            ]
        )

        values = app.category_inventory_preview_values(
            preview,
            [("M1", "英语")],
            app.STATUS_INACTIVE,
        )

        self.assertEqual(values[("M1", "英语")]["status"], app.STATUS_INACTIVE)

    def test_new_category_preview_rejects_missing_or_negative_price_rows(self) -> None:
        missing = pd.DataFrame(
            [
                {
                    "产品型号": "M1",
                    "语种": "英语",
                    "库存数量": 10,
                    "单价": 0,
                    "海关编码": "",
                    "启用状态": app.STATUS_ACTIVE,
                }
            ]
        )
        negative_price = missing.copy()
        negative_price.loc[0, "单价"] = -1

        with self.assertRaisesRegex(ValueError, "组合不一致"):
            app.category_inventory_preview_values(
                missing,
                [("M1", "英语"), ("M2", "韩语")],
                app.STATUS_ACTIVE,
            )
        with self.assertRaisesRegex(ValueError, "单价不能小于 0"):
            app.category_inventory_preview_values(
                negative_price,
                [("M1", "英语")],
                app.STATUS_ACTIVE,
            )

    def test_return_from_new_category_preview_restores_full_form_and_inventory_state(self) -> None:
        session_state: dict[str, object] = {"target_revision": 2}
        form_state = {
            "category_name_new": "新品类",
            "category_zh_page_name_new": "新品类中文",
            "category_en_page_name_new": "New Category",
            "category_status_new": app.STATUS_ACTIVE,
            "category_unit_price_new": "1.25",
            "category_customs_code_new": "HS-1",
            "category_no_model_new": True,
            "category_no_language_new": True,
            "category_models_new": [],
            "category_custom_models_new": "",
            "category_languages_new": [],
            "category_custom_languages_new": "",
            "untrusted_widget_key": "ignored",
        }
        target_values = {
            (app.NO_MODEL_TEXT, app.NO_LANGUAGE_TEXT): {
                "quantity": 37,
                "unit_price": 1.25,
                "customs_code": "HS-1",
                "status": app.STATUS_ACTIVE,
            }
        }

        with patch.object(app.st, "session_state", session_state):
            app.restore_new_category_creation_state(
                {
                    "form_state": form_state,
                    "target_state_key": "target_values",
                    "revision_key": "target_revision",
                },
                target_values,
            )

        self.assertEqual(session_state["category_name_new"], "新品类")
        self.assertEqual(session_state["category_zh_page_name_new"], "新品类中文")
        self.assertEqual(session_state["category_en_page_name_new"], "New Category")
        self.assertTrue(session_state["category_no_model_new"])
        self.assertTrue(session_state["category_no_language_new"])
        self.assertEqual(session_state["target_values"], target_values)
        self.assertEqual(session_state["target_revision"], 3)
        self.assertNotIn("untrusted_widget_key", session_state)

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

    def test_category_enabled_status_does_not_override_inventory_targets(self) -> None:
        records = [inventory_record("1", "M1", "英语", 100, status=app.STATUS_ACTIVE)]
        plan = app.build_category_inventory_plan(records, "旧品类", ["M1", "M2"], ["英语"])

        enforced = app.enforce_category_inventory_status(plan, app.STATUS_INACTIVE)

        self.assertEqual(
            {target["status"] for target in enforced["targets"]},
            {app.STATUS_ACTIVE},
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

    def test_language_rename_keeps_inventory_in_renamed_target(self) -> None:
        records = [inventory_record("1", "BG1", "英语", 12)]

        plan = app.build_category_inventory_plan(
            records,
            "旧品类",
            ["BG1"],
            ["English"],
            language_renames={"英语": "English"},
        )

        self.assertEqual(plan["targets"][0]["language"], "English")
        self.assertEqual(plan["targets"][0]["quantity"], 12)
        self.assertEqual(plan["language_renames"], {"英语": "English"})

    def test_language_rename_validation_rejects_duplicate_names(self) -> None:
        editor_df = pd.DataFrame(
            [
                {"当前语种": "英语", "修改后语种": "英文"},
                {"当前语种": "法语", "修改后语种": "英文"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "不能与其他已有语种重名"):
            app.category_language_rename_values(editor_df)

    def test_category_option_pool_summaries_follow_hierarchy(self) -> None:
        categories = [
            {
                "record_id": "category-a",
                "category": "品类A",
                "status": app.STATUS_ACTIVE,
            }
        ]
        records = [
            inventory_record("1", "M1", "英语", 5),
            inventory_record("2", "M1", "法语", 0, status=app.STATUS_INACTIVE),
        ]
        for record in records:
            record["category"] = "品类A"

        category_pool = app.category_pool_summary(categories, records)
        model_pool = app.category_model_pool_summary(records)
        language_pool = app.category_language_pool_summary(records)
        material_pool = app.category_material_pool_summary(records)

        self.assertEqual(category_pool[0]["value"], "品类A")
        self.assertIn("2 行", str(category_pool[0]["meta"]))
        self.assertEqual(model_pool[0]["value"], "M1")
        self.assertIn("2 个语种", str(model_pool[0]["meta"]))
        self.assertEqual(
            [item["value"] for item in language_pool],
            ["英语", "法语"],
        )
        self.assertIn("1 个型号", str(language_pool[0]["meta"]))
        self.assertEqual(
            [item["value"] for item in material_pool],
            ["1", "2"],
        )

    def test_category_option_pool_keeps_selected_values_across_reruns(self) -> None:
        session_state: dict[str, object] = {}
        component_result = SimpleNamespace(selected=["品类A"], edit="")
        options = [{"value": "品类A", "label": "品类A", "meta": "1 行"}]
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(
                app,
                "CATEGORY_OPTION_POOL",
                return_value=component_result,
            ) as component,
        ):
            app.render_category_option_pool(
                options,
                selected=[],
                key="delete_pool",
                multi=True,
                danger=True,
            )
            app.render_category_option_pool(
                options,
                selected=[],
                key="delete_pool",
                multi=True,
                danger=True,
            )

        self.assertEqual(session_state["delete_pool_selection"], ["品类A"])
        self.assertEqual(component.call_args_list[1].kwargs["data"]["selected"], ["品类A"])

    def test_category_option_pool_passes_single_compact_grouped_configuration(self) -> None:
        session_state: dict[str, object] = {}
        component_result = SimpleNamespace(selected="品类B", edit="")
        options = [
            {
                "value": "品类A",
                "label": "品类A",
                "meta": "1 行",
                "group": app.CATEGORY_DEFINITION_PRINT,
            },
            {
                "value": "品类B",
                "label": "品类B",
                "meta": "2 行",
                "group": app.CATEGORY_DEFINITION_GIFT,
            },
            {
                "value": "品类C",
                "label": "品类C",
                "meta": "3 行",
                "group": app.CATEGORY_DEFINITION_CULTURAL,
            },
        ]
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(
                app,
                "CATEGORY_OPTION_POOL",
                return_value=component_result,
            ) as component,
        ):
            selected, _ = app.render_category_option_pool(
                options,
                selected=None,
                key="category_delete_pool",
                multi=False,
                danger=True,
                compact=True,
                grouped=True,
            )

        data = component.call_args.kwargs["data"]
        self.assertEqual(selected, "品类B")
        self.assertFalse(data["multi"])
        self.assertTrue(data["compact"])
        self.assertTrue(data["grouped"])
        self.assertEqual(data["group_order"], list(app.CATEGORY_DEFINITION_OPTIONS))
        self.assertEqual(
            [item["group"] for item in data["options"]],
            list(app.CATEGORY_DEFINITION_OPTIONS),
        )

    def test_category_delete_scope_supports_multiple_models_and_languages(self) -> None:
        records = [
            inventory_record("1", "M1", "英语", 0),
            inventory_record("2", "M1", "韩语", 0),
            inventory_record("3", "M2", "英语", 0),
            inventory_record("4", "M2", "日语", 0),
        ]

        self.assertEqual(
            [record["record_id"] for record in app.category_delete_material_scope(records, ["M1", "M2"], ["英语"])],
            ["1", "3"],
        )
        self.assertEqual(
            [record["record_id"] for record in app.category_delete_material_scope(records, ["M1"], [])],
            ["1", "2"],
        )
        self.assertEqual(app.category_delete_material_scope(records, [], []), [])

    def test_category_pool_carries_definition_for_grouped_delete_layout(self) -> None:
        categories = [
            {
                "category": "品类A",
                "category_definition": app.CATEGORY_DEFINITION_GIFT,
                "status": app.STATUS_ACTIVE,
            }
        ]

        summary = app.category_pool_summary(categories, [])

        self.assertEqual(summary[0]["group"], app.CATEGORY_DEFINITION_GIFT)

    def test_category_pool_defaults_unknown_definition_to_print_group(self) -> None:
        categories = [
            {
                "category": "品类A",
                "category_definition": "",
                "status": app.STATUS_ACTIVE,
            },
            {
                "category": "品类B",
                "category_definition": "旧定义",
                "status": app.STATUS_ACTIVE,
            },
        ]

        summary = app.category_pool_summary(categories, [])

        self.assertEqual(
            [item["group"] for item in summary],
            [app.CATEGORY_DEFINITION_PRINT, app.CATEGORY_DEFINITION_PRINT],
        )

    def test_category_delete_preview_contains_material_details(self) -> None:
        record = inventory_record("1", "M1", "韩语", 0, status=app.STATUS_INACTIVE)
        record["category"] = "产品单页"
        record["material_code"] = "MAT-0001"

        preview = app.category_delete_preview_dataframe([record])

        self.assertEqual(preview.loc[0, "物料编码"], "MAT-0001")
        self.assertEqual(preview.loc[0, "物料品类"], "产品单页")
        self.assertEqual(preview.loc[0, "产品型号"], "M1")
        self.assertEqual(preview.loc[0, "语种"], "韩语")
        self.assertEqual(preview.loc[0, "启用状态"], app.STATUS_INACTIVE)
        self.assertEqual(preview.loc[0, "申领页显示"], app.REQUEST_PAGE_HIDDEN_VALUE)

    def test_category_delete_detects_changes_after_preview(self) -> None:
        preview = inventory_record("1", "M1", "韩语", 0)
        preview["material_code"] = "MAT-0001"
        current = dict(preview)
        current["quantity"] = 5

        changed = app.category_delete_changed_records([preview], [current])

        self.assertEqual(changed, ["MAT-0001"])

    def test_new_material_rows_default_to_active_and_visible_on_request_page(self) -> None:
        plan = app.build_category_inventory_plan([], "新品类", ["M1"], ["英语"])

        self.assertEqual(plan["targets"][0]["status"], app.STATUS_ACTIVE)
        self.assertEqual(
            plan["targets"][0]["request_visible"],
            app.REQUEST_PAGE_VISIBLE_VALUE,
        )

    def test_material_deletion_ignores_stock_and_historical_references(self) -> None:
        record = inventory_record("material-1", "M1", "英语", 99)

        self.assertEqual(app.category_delete_blockers([record]), [])

    def test_category_deletion_only_blocks_missing_categories(self) -> None:
        categories = {"品类A": {"record_id": "category-a", "category": "品类A"}}
        inventory_records = [
            {**inventory_record("material-1", "M1", "英语", 99), "category": "品类A"}
        ]

        self.assertEqual(
            app.category_delete_category_blockers(
                ["品类A"],
                categories,
                inventory_records,
            ),
            [],
        )
        self.assertEqual(
            app.category_delete_category_blockers(
                ["已删除品类"],
                categories,
                inventory_records,
            ),
            ["已删除品类（品类已不存在）"],
        )

    @patch("app.feishu_rows")
    @patch("app.feishu_material_rows")
    def test_category_reference_detects_linked_material_and_gift_project(
        self,
        mock_material_rows,
        mock_rows,
    ) -> None:
        mock_material_rows.return_value = [
            {
                "record_id": "material-1",
                "fields": {"物料品类": "品类A"},
            }
        ]

        def rows_for_table(table_name: str) -> list[dict]:
            if table_name == app.REQUEST_LINE_TABLE_NAME:
                return [
                    {
                        "record_id": "line-1",
                        "fields": {"物料编码": [{"record_id": "material-1"}]},
                    }
                ]
            if table_name == app.GIFT_PROJECT_TABLE_NAME:
                return [
                    {
                        "record_id": "project-1",
                        "fields": {
                            app.GIFT_PROJECT_CATEGORY_LINK_FIELD: [
                                {"record_id": "category-a", "text": "品类A"}
                            ]
                        },
                    }
                ]
            return []

        mock_rows.side_effect = rows_for_table

        count = app.count_feishu_category_business_references(
            "品类A",
            "category-a",
        )

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
