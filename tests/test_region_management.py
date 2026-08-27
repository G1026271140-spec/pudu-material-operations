import unittest
from unittest.mock import patch

import app


class RegionManagementTests(unittest.TestCase):
    def test_region_config_and_category_scope(self) -> None:
        self.assertEqual(app.dimension_management_config("region")["table"], app.REGION_TABLE_NAME)
        categories = [
            {"category": "文化POLO衫", "category_definition": app.CATEGORY_DEFINITION_CULTURAL},
            {"category": "产品单页", "category_definition": app.CATEGORY_DEFINITION_PRINT},
        ]
        self.assertEqual(
            app.dimension_association_category_names("region", categories, "欧洲战区"),
            ["文化POLO衫"],
        )

    def test_region_association_plan_uses_model_as_counterpart(self) -> None:
        rows = [{
            "record_id": "cul-1", "material_code": "CUL-1", "category": "文化POLO衫",
            "model": "M", "language": "欧洲战区", "region": "欧洲战区",
            "quantity": 5, "status": app.STATUS_ACTIVE,
            "request_visible": app.REQUEST_PAGE_VISIBLE_VALUE,
        }]
        changes = app.dimension_association_plan(
            "region", "edit", "欧洲战区", "欧盟战区",
            [["文化POLO衫", "M"]], rows,
            [{"category": "文化POLO衫", "record_id": "cat-1"}],
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["action"], "update")
        self.assertEqual(changes[0]["region"], "欧盟战区")
        self.assertEqual(changes[0]["model"], "M")

    def test_execute_region_edit_updates_region_and_culture_rows(self) -> None:
        draft = {
            "kind": "region", "operation": "edit", "record_id": "reg-1",
            "name": "欧盟战区", "status": app.STATUS_ACTIVE,
            "changes": [{"action": "update", "record_id": "cul-1", "region": "欧盟战区"}],
        }
        region_rows = [{"record_id": "reg-1", "fields": {"战区名称": "欧洲战区", "启用状态": "启用"}}]
        culture_rows = [{"record_id": "cul-1", "fields": {"文化周边编码": "CUL-1", "物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "欧洲战区", "当前库存": 5}}]

        def fresh(table_name):
            return region_rows if table_name == app.REGION_TABLE_NAME else culture_rows

        with (
            patch.object(app, "refresh_feishu_schema_cache"),
            patch.object(app, "fresh_feishu_rows", side_effect=fresh),
            patch.object(app, "feishu_update_record_fields") as update_one,
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_many,
            patch.object(app, "feishu_batch_delete_record_ids", return_value=0),
        ):
            result = app.execute_region_dimension_management(draft)

        update_one.assert_called_once_with(app.REGION_TABLE_NAME, "reg-1", {"战区名称": "欧盟战区", "启用状态": "启用"})
        self.assertEqual(update_many.call_args.args[0], app.CULTURAL_MATERIAL_TABLE_NAME)
        self.assertEqual(update_many.call_args.args[1][0]["fields"], {"战区管理": "欧盟战区"})
        self.assertEqual(result["updated_material_count"], 1)


if __name__ == "__main__":
    unittest.main()
