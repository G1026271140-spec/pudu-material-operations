import unittest

import app
import submission_queue as queue


class CulturalRequestTests(unittest.TestCase):
    def test_catalog_only_includes_cultural_categories(self) -> None:
        categories = [
            {"record_id": "cat1", "fields": {"物料品类": "文化POLO衫", "品类定义": "文化周边", "中文页面名称": "文化POLO衫", "英文页面名称": "Cultural Polo Shirt"}},
            {"record_id": "cat2", "fields": {"物料品类": "产品单页", "品类定义": "印刷物料"}},
        ]
        models = [{"record_id": "mod1", "fields": {"产品型号": "M"}}]
        culture = [
            {"record_id": "cul1", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "8", "单价（人民币）": 78}},
            {"record_id": "cul2", "fields": {"物料品类": "产品单页", "产品型号": "M", "战区管理": "美洲战区", "当前库存": "99"}},
        ]
        catalog = app.cultural_request_catalog(culture, categories, models)
        self.assertEqual(catalog["products"], ["文化POLO衫"])
        self.assertEqual(catalog["combinations"][("文化POLO衫", "M", "美洲战区")]["stock"], 8)

    def test_queue_payload_keeps_cultural_dimensions(self) -> None:
        payload = app.queued_cultural_request_payload(
            {"requester": "申请人", "requester_open_id": "ou_test", "submission_token": "token"},
            [{"product": "文化夹克", "model": "L", "region": "欧洲战区", "quantity": 2, "remark": "test"}],
        )
        self.assertEqual(queue.QUEUE_TASK_TYPE_CULTURAL_REQUEST, "文化周边申领")
        self.assertEqual(payload["lines"][0]["region"], "欧洲战区")
        self.assertEqual(payload["lines"][0]["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
