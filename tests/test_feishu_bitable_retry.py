from __future__ import annotations

import io
import unittest
from urllib import error
from unittest.mock import MagicMock, patch

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig, FeishuBitableError


class FeishuBitableRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        self.client._tenant_access_token = "cached-token"
        self.client._tenant_access_token_expires_at = float("inf")

    @staticmethod
    def response(payload: bytes) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        return response

    def test_get_retries_transient_http_500_then_succeeds(self) -> None:
        temporary_error = error.HTTPError(
            "https://open.feishu.cn/test",
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"code":2200,"msg":"Internal Error","data":{}}'),
        )
        with (
            patch("feishu_bitable.request.urlopen", side_effect=[temporary_error, self.response(b'{"code":0,"data":{}}')]) as urlopen,
            patch("feishu_bitable.time.sleep") as sleep,
        ):
            result = self.client._request("GET", "/test")

        self.assertEqual(result["code"], 0)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_post_does_not_retry_transient_http_500(self) -> None:
        temporary_error = error.HTTPError(
            "https://open.feishu.cn/test",
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"code":2200,"msg":"Internal Error","data":{}}'),
        )
        with (
            patch("feishu_bitable.request.urlopen", side_effect=temporary_error) as urlopen,
            patch("feishu_bitable.time.sleep") as sleep,
        ):
            with self.assertRaises(FeishuBitableError):
                self.client._request("POST", "/test", payload={"value": 1})

        urlopen.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
