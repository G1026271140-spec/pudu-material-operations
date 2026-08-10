from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, Mock, patch

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class FeishuBitableBotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))

    def test_ocr_sends_base64_image_and_returns_text_list(self) -> None:
        self.client._request = Mock(
            return_value={"data": {"text_list": ["产品单页", "", " 5 "]}}
        )

        result = self.client.recognize_image_text(b"image-bytes")

        self.assertEqual(result, ["产品单页", "5"])
        call = self.client._request.call_args
        self.assertEqual(
            call.args,
            ("POST", "/optical_char_recognition/v1/image/basic_recognize"),
        )
        self.assertEqual(
            call.kwargs["payload"]["image"],
            base64.b64encode(b"image-bytes").decode("ascii"),
        )

    def test_interactive_reply_uses_stable_uuid(self) -> None:
        self.client._request = Mock(
            return_value={"data": {"message_id": "om-reply"}}
        )

        first = self.client.reply_interactive_message(
            "om-source",
            {"schema": "2.0"},
            idempotency_key="inventory:om-source",
        )
        first_payload = dict(self.client._request.call_args.kwargs["payload"])
        second = self.client.reply_interactive_message(
            "om-source",
            {"schema": "2.0"},
            idempotency_key="inventory:om-source",
        )
        second_payload = dict(self.client._request.call_args.kwargs["payload"])

        self.assertEqual(first, "om-reply")
        self.assertEqual(second, "om-reply")
        self.assertEqual(first_payload["uuid"], second_payload["uuid"])
        self.assertEqual(first_payload["msg_type"], "interactive")
        self.assertIn('"schema": "2.0"', first_payload["content"])

    def test_download_message_image_uses_message_resource_endpoint(self) -> None:
        self.client._tenant_access_token = "token"
        self.client._tenant_access_token_expires_at = 10**12
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"image"

        with patch("feishu_bitable.request.urlopen", return_value=response) as urlopen:
            result = self.client.download_message_resource("om-source", "img-key")

        self.assertEqual(result, b"image")
        request_object = urlopen.call_args.args[0]
        self.assertIn("/im/v1/messages/om-source/resources/img-key", request_object.full_url)
        self.assertIn("type=image", request_object.full_url)


if __name__ == "__main__":
    unittest.main()
