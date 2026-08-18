from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class FeishuBitableBotApiTests(unittest.TestCase):
    def test_interactive_message_update_uses_patch(self) -> None:
        card = {"schema": "2.0", "body": {"elements": []}}
        self.client._request = Mock(return_value={"code": 0})

        self.client.update_interactive_message("om-card", card)

        self.client._request.assert_called_once_with(
            "PATCH",
            "/im/v1/messages/om-card",
            payload={"content": json.dumps(card, ensure_ascii=False)},
        )

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

    def test_download_bitable_attachment_resolves_authenticated_temporary_url(self) -> None:
        self.client._tenant_access_token = "token"
        self.client._tenant_access_token_expires_at = 10**12
        temporary_url = "https://internal-api-drive-stream.feishu.cn/file/image"
        api_response = MagicMock()
        api_response.__enter__.return_value.read.return_value = json.dumps(
            {
                "code": 0,
                "data": {
                    "tmp_download_urls": [
                        {
                            "file_token": "file-1",
                            "tmp_download_url": temporary_url,
                        }
                    ]
                },
            }
        ).encode("utf-8")
        image_response = MagicMock()
        image_response.__enter__.return_value.read.return_value = b"image"
        attachment_url = (
            "https://open.feishu.cn/open-apis/drive/v1/medias/"
            "batch_get_tmp_download_url?file_tokens=file-1&extra=context"
        )

        with patch(
            "feishu_bitable.request.urlopen",
            side_effect=[api_response, image_response],
        ) as urlopen:
            result = self.client.download_bitable_attachment(
                "file-1",
                attachment_url,
            )

        self.assertEqual(result, b"image")
        self.assertEqual(urlopen.call_count, 2)
        api_request = urlopen.call_args_list[0].args[0]
        image_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(api_request.get_header("Authorization"), "Bearer token")
        self.assertEqual(image_request.full_url, temporary_url)

    def test_download_bitable_attachment_rejects_untrusted_url(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "trusted Feishu URL"):
            self.client.download_bitable_attachment(
                "file-1",
                "https://example.com/file/image",
            )


if __name__ == "__main__":
    unittest.main()
