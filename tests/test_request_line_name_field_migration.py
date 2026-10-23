from __future__ import annotations

import unittest

from scripts.migrate_request_line_name_fields import build_name_snapshots


class RequestLineNameFieldMigrationTests(unittest.TestCase):
    def test_lookup_values_are_preserved_and_custom_values_use_snapshots(self) -> None:
        rows = [
            {
                "record_id": "normal",
                "fields": {
                    "品类名称": [{"text": "产品单页"}],
                    "产品型号名称": [{"text": "D7"}],
                    "语种名称": [{"text": "英语"}],
                },
            },
            {
                "record_id": "custom",
                "fields": {
                    "实际发放物料品类": "新品",
                    "实际发放产品型号": "新品",
                    "实际发放语种": "新品",
                },
            },
        ]

        snapshots = build_name_snapshots(rows)

        self.assertEqual(snapshots[0]["fields"]["品类名称"], "产品单页")
        self.assertEqual(snapshots[0]["fields"]["产品型号名称"], "D7")
        self.assertEqual(snapshots[0]["fields"]["语种名称"], "英语")
        self.assertEqual(
            snapshots[1]["fields"],
            {"品类名称": "新品", "产品型号名称": "新品", "语种名称": "新品"},
        )
