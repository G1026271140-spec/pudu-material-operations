import json
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parents[1] / "anycross.feishu" / "数据回写json.json"


class AnyCrossInventoryWritebackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.steps = {step["id"]: step for step in cls.workflow["steps"]}

    def test_workflow_step_ids_are_unique_and_structure_is_resolvable(self) -> None:
        step_ids = [step["id"] for step in self.workflow["steps"]]
        structure_ids: list[str] = []

        def collect(nodes: list[dict]) -> None:
            for node in nodes:
                structure_ids.append(node["id"])
                collect(list(node.get("subSteps") or []))

        collect(self.workflow["structure"])
        self.assertEqual(len(step_ids), len(set(step_ids)))
        self.assertEqual(set(step_ids), set(structure_ids))

    def test_prepare_uses_approval_line_number_instead_of_row_position(self) -> None:
        source = self.steps["script-prepare"]["parameters"]["js_code"]["value"]

        self.assertIn("fields['明细编号']", source)
        self.assertNotIn("row_index", source)
        self.assertNotIn("padStart", source)

    def test_duplicate_line_numbers_receive_distinct_idempotency_keys(self) -> None:
        source = self.steps["script-prepare"]["parameters"]["js_code"]["value"]

        self.assertIn("lineCounts[d.line_no] > 1", source)
        self.assertIn("material_category", source)
        self.assertIn("product_model", source)
        self.assertIn("language", source)

    def test_detail_lookup_can_disambiguate_historical_duplicate_numbers(self) -> None:
        query = self.steps["bitable-query-detail"]
        reference = self.steps["script-detail-reference"]
        source = reference["parameters"]["js_code"]["value"]

        self.assertEqual(query["parameters"]["page_size"]["value"], 20)
        self.assertIn("expected", reference["parameters"]["input"]["value"])
        self.assertIn("结合品类/型号/语种后应唯一命中 1 条", source)
        self.assertIn("first.record_ids", source)

    def test_result_audit_task_is_enqueued_before_inventory_updates(self) -> None:
        structure_ids = [item["id"] for item in self.workflow["structure"]]
        fields_source = self.steps["script-notify-task-fields"]["parameters"]["js_code"]["value"]

        self.assertLess(structure_ids.index("branch-notify-task"), structure_ids.index("loop-detail"))
        self.assertIn("审批回写管理员通知", fields_source)
        self.assertIn("下次重试时间", fields_source)
        self.assertIn("10 * 60 * 1000", fields_source)
        self.assertIn("后台任务队列", self.steps["script-prepare"]["parameters"]["js_code"]["value"])


if __name__ == "__main__":
    unittest.main()
