import unittest

import app


class AdminAccessTests(unittest.TestCase):
    def test_protected_management_sections_share_admin_gate(self) -> None:
        self.assertTrue(app.management_section_requires_admin("物料数据库"))
        self.assertTrue(app.management_section_requires_admin("品类管理"))

    def test_request_pages_remain_unprotected(self) -> None:
        self.assertFalse(app.management_section_requires_admin("库存登记"))
        self.assertFalse(app.management_section_requires_admin("修改与撤回"))
        self.assertFalse(app.management_section_requires_admin(""))


if __name__ == "__main__":
    unittest.main()
