import unittest

from scripts.validate_release_consistency import validate_release_consistency


class ReleaseConsistencyTests(unittest.TestCase):
    def test_current_release_is_consistent(self) -> None:
        stats = validate_release_consistency()
        self.assertGreater(int(stats["queue_task_types"]), 0)


if __name__ == "__main__":
    unittest.main()
