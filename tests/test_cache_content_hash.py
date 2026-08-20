import unittest

from scripts.preserve_unchanged_cache_files import stable_value


class CacheContentHashTests(unittest.TestCase):
    def test_volatile_refresh_metadata_does_not_change_content(self) -> None:
        old = {
            "generated_at": "2026-08-20 10:30:00",
            "source": "live_feishu",
            "tables": {"物料品类": [{"fields": {"名称": "单页"}}]},
        }
        new = {
            "generated_at": "2026-08-20 16:30:00",
            "source": "static_snapshot",
            "tables": {"物料品类": [{"fields": {"名称": "单页"}}]},
        }

        self.assertEqual(stable_value(old), stable_value(new))

    def test_business_field_change_is_detected(self) -> None:
        old = {"tables": {"物料主数据": [{"fields": {"当前库存": 10}}]}}
        new = {"tables": {"物料主数据": [{"fields": {"当前库存": 9}}]}}

        self.assertNotEqual(stable_value(old), stable_value(new))

    def test_temporary_attachment_urls_do_not_create_commits(self) -> None:
        old = {"attachment": {"file_token": "token", "tmp_url": "old"}}
        new = {"attachment": {"file_token": "token", "tmp_url": "new"}}

        self.assertEqual(stable_value(old), stable_value(new))


if __name__ == "__main__":
    unittest.main()
