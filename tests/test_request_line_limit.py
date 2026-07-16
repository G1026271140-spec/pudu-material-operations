import unittest
from unittest.mock import patch

import app


class RequestLineLimitTests(unittest.TestCase):
    def test_request_line_limit_is_twenty(self) -> None:
        self.assertEqual(app.MAX_REQUEST_LINE_COUNT, 20)

    def test_submission_rejects_more_than_twenty_lines(self) -> None:
        lines = [
            {
                "product": f"product-{index}",
                "model": "model",
                "language": "language",
                "quantity": 1,
            }
            for index in range(app.MAX_REQUEST_LINE_COUNT + 1)
        ]

        with patch.object(app, "refresh_feishu_schema_cache"):
            with self.assertRaisesRegex(RuntimeError, "最多可提交 20 条"):
                app.submit_feishu_material_request({}, lines)


if __name__ == "__main__":
    unittest.main()
