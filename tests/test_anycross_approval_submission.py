from __future__ import annotations

import json
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parents[1] / "anycross.feishu" / "序列化审批.json"


class AnyCrossApprovalSubmissionTests(unittest.TestCase):
    def test_custom_material_dimensions_fall_back_to_text_snapshots(self) -> None:
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        step = next(item for item in workflow["steps"] if item.get("id") == "script-8")
        code = step["parameters"]["js_code"]["value"]
        inputs = step["parameters"]["input"]["value"]

        self.assertIn("'品类名称': '实际发放物料品类'", code)
        self.assertIn("'产品型号名称': '实际发放产品型号'", code)
        self.assertIn("'语种名称': '实际发放语种'", code)
        self.assertEqual(
            inputs["valueMap"]["value"]["expression"],
            '_("$.loop-6.item.fields")',
        )


if __name__ == "__main__":
    unittest.main()
