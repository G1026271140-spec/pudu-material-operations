import unittest

import app


class AdminAccessTests(unittest.TestCase):
    def test_category_navigation_and_workbench_control_use_different_state_keys(self) -> None:
        self.assertNotEqual(
            app.MANAGEMENT_NAVIGATION_KEY,
            app.MANAGEMENT_WORKBENCH_CONTROL_KEY,
        )

    def test_protected_management_sections_share_admin_gate(self) -> None:
        self.assertTrue(app.management_section_requires_admin("物料数据库"))
        self.assertTrue(app.management_section_requires_admin("品类管理"))

    def test_request_pages_remain_unprotected(self) -> None:
        self.assertFalse(app.management_section_requires_admin("库存登记"))
        self.assertFalse(app.management_section_requires_admin("修改与撤回"))
        self.assertFalse(app.management_section_requires_admin(""))


if __name__ == "__main__":
    unittest.main()
