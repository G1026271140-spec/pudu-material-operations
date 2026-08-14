from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


FEISHU_OPEN_API = "https://open.feishu.cn/open-apis"


class FeishuBitableError(RuntimeError):
    pass


@dataclass
class FeishuBitableConfig:
    app_id: str
    app_secret: str
    app_token: str


class FeishuBitableClient:
    def __init__(self, config: FeishuBitableConfig) -> None:
        self.config = config
        self._tenant_access_token = ""
        self._tenant_access_token_expires_at = 0.0

    def tenant_access_token(self) -> str:
        if self._tenant_access_token and time.time() < self._tenant_access_token_expires_at:
            return self._tenant_access_token

        response = self._request(
            "POST",
            "/auth/v3/tenant_access_token/internal",
            auth=False,
            payload={
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            },
        )
        token = str(response.get("tenant_access_token", "")).strip()
        if not token:
            raise FeishuBitableError("Feishu did not return tenant_access_token.")
        self._tenant_access_token = token
        self._tenant_access_token_expires_at = time.time() + int(response.get("expire", 7200)) - 120
        return token

    def list_tables(self) -> list[dict[str, Any]]:
        return self._paged_get(f"/bitable/v1/apps/{self._quoted_app_token()}/tables", "items")

    def list_fields(self, table_id: str) -> list[dict[str, Any]]:
        return self._paged_get(
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/fields",
            "items",
        )

    def create_table(
        self,
        table_name: str,
        fields: list[dict[str, Any]],
        *,
        default_view_name: str = "表格",
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables",
            payload={
                "table": {
                    "name": table_name,
                    "default_view_name": default_view_name,
                    "fields": fields,
                }
            },
        )
        return dict(response.get("data", {}))

    def create_field(
        self,
        table_id: str,
        field_name: str,
        field_type: int,
        property: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"field_name": field_name, "type": field_type}
        if property is not None:
            payload["property"] = property
        response = self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/fields",
            payload=payload,
        )
        return dict(response.get("data", {}).get("field", {}))

    def upload_media(
        self,
        file_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        normalized_name = file_name.strip()
        if not normalized_name:
            raise FeishuBitableError("Attachment file name cannot be empty.")
        if len(normalized_name) > 250:
            raise FeishuBitableError(f"Attachment file name is too long: {normalized_name}")
        if not content:
            raise FeishuBitableError(f"Attachment file is empty: {normalized_name}")
        if len(content) > 20 * 1024 * 1024:
            raise FeishuBitableError(f"Attachment exceeds Feishu's 20 MB limit: {normalized_name}")

        boundary = f"----PuduMaterialInventory{uuid.uuid4().hex}"
        body = bytearray()

        def add_text_field(name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        add_text_field("file_name", normalized_name)
        add_text_field("parent_type", "bitable_file")
        add_text_field("parent_node", self.config.app_token)
        add_text_field("size", str(len(content)))
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(b'Content-Disposition: form-data; name="file"; filename="upload"\r\n')
        body.extend(f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode("ascii"))
        body.extend(content)
        body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))

        req = request.Request(
            FEISHU_OPEN_API + "/drive/v1/medias/upload_all",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {self.tenant_access_token()}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc

        if data.get("code") != 0:
            raise FeishuBitableError(f"Feishu API {data.get('code')}: {data.get('msg')}")
        file_token = str(data.get("data", {}).get("file_token", "")).strip()
        if not file_token:
            raise FeishuBitableError("Feishu did not return an attachment file_token.")
        return file_token

    def download_media(self, file_token: str, *, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        normalized_token = file_token.strip()
        if not normalized_token:
            raise FeishuBitableError("Attachment file_token cannot be empty.")
        if max_bytes <= 0:
            raise FeishuBitableError("Attachment size limit must be positive.")

        req = request.Request(
            FEISHU_OPEN_API
            + f"/drive/v1/medias/{parse.quote(normalized_token, safe='')}/download",
            headers={"Authorization": f"Bearer {self.tenant_access_token()}"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                content = response.read(max_bytes + 1)
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc
        if len(content) > max_bytes:
            raise FeishuBitableError(
                f"Attachment exceeds the {max_bytes} byte download limit."
            )
        if not content:
            raise FeishuBitableError("Feishu returned an empty attachment.")
        return content

    def download_bitable_attachment(
        self,
        file_token: str,
        attachment_url: str = "",
        *,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> bytes:
        normalized_token = file_token.strip()
        normalized_url = attachment_url.strip()
        if not normalized_token:
            raise FeishuBitableError("Attachment file_token cannot be empty.")
        if not normalized_url:
            return self.download_media(normalized_token, max_bytes=max_bytes)
        if max_bytes <= 0:
            raise FeishuBitableError("Attachment size limit must be positive.")

        parsed_url = parse.urlsplit(normalized_url)
        hostname = str(parsed_url.hostname or "").lower()
        if parsed_url.scheme != "https" or not (
            hostname == "feishu.cn" or hostname.endswith(".feishu.cn")
        ):
            raise FeishuBitableError("Attachment URL is not a trusted Feishu URL.")

        download_url = normalized_url
        if (
            hostname == "open.feishu.cn"
            and parsed_url.path
            == "/open-apis/drive/v1/medias/batch_get_tmp_download_url"
        ):
            params = {
                key: values[-1]
                for key, values in parse.parse_qs(
                    parsed_url.query,
                    keep_blank_values=True,
                ).items()
                if values
            }
            response = self._request(
                "GET",
                "/drive/v1/medias/batch_get_tmp_download_url",
                params=params,
            )
            candidates = list(response.get("data", {}).get("tmp_download_urls") or [])
            matched = next(
                (
                    item
                    for item in candidates
                    if str(item.get("file_token") or "").strip() == normalized_token
                ),
                None,
            )
            download_url = str((matched or {}).get("tmp_download_url") or "").strip()
            if not download_url:
                raise FeishuBitableError(
                    "Feishu did not return a temporary attachment download URL."
                )

        parsed_download_url = parse.urlsplit(download_url)
        download_hostname = str(parsed_download_url.hostname or "").lower()
        if parsed_download_url.scheme != "https" or not (
            download_hostname == "feishu.cn"
            or download_hostname.endswith(".feishu.cn")
        ):
            raise FeishuBitableError("Attachment download URL is not trusted.")

        req = request.Request(download_url, method="GET")
        try:
            with request.urlopen(req, timeout=30) as response:
                content = response.read(max_bytes + 1)
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc
        if len(content) > max_bytes:
            raise FeishuBitableError(
                f"Attachment exceeds the {max_bytes} byte download limit."
            )
        if not content:
            raise FeishuBitableError("Feishu returned an empty attachment.")
        return content

    def list_records(self, table_id: str, page_size: int = 500) -> list[dict[str, Any]]:
        return self._paged_get(
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records",
            "items",
            page_size=page_size,
        )

    def list_contact_departments(self) -> list[dict[str, Any]]:
        return self._paged_get(
            "/contact/v3/departments",
            "items",
            page_size=50,
            params={
                "parent_department_id": "0",
                "fetch_child": "true",
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
            },
        )

    def list_department_users(self, department_id: str) -> list[dict[str, Any]]:
        normalized_department_id = department_id.strip()
        if not normalized_department_id:
            return []
        return self._paged_get(
            "/contact/v3/users/find_by_department",
            "items",
            page_size=50,
            params={
                "department_id": normalized_department_id,
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
            },
        )

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: str = "open_id",
    ) -> str:
        normalized_receive_id = receive_id.strip()
        normalized_text = text.strip()
        if not normalized_receive_id:
            raise FeishuBitableError("Feishu message receive_id cannot be empty.")
        if not normalized_text:
            raise FeishuBitableError("Feishu message text cannot be empty.")
        response = self._request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            payload={
                "receive_id": normalized_receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": normalized_text}, ensure_ascii=False),
            },
        )
        message_id = str(response.get("data", {}).get("message_id", "")).strip()
        if not message_id:
            raise FeishuBitableError("Feishu did not return a message_id.")
        return message_id

    def send_interactive_message(
        self,
        receive_id: str,
        card: dict[str, Any],
        *,
        receive_id_type: str = "open_id",
    ) -> str:
        normalized_receive_id = receive_id.strip()
        if not normalized_receive_id:
            raise FeishuBitableError("Feishu message receive_id cannot be empty.")
        if not card:
            raise FeishuBitableError("Feishu interactive card cannot be empty.")
        response = self._request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            payload={
                "receive_id": normalized_receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        message_id = str(response.get("data", {}).get("message_id", "")).strip()
        if not message_id:
            raise FeishuBitableError("Feishu did not return a message_id.")
        return message_id

    def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        *,
        resource_type: str = "image",
        max_bytes: int = 5 * 1024 * 1024,
    ) -> bytes:
        normalized_message_id = message_id.strip()
        normalized_file_key = file_key.strip()
        if not normalized_message_id or not normalized_file_key:
            raise FeishuBitableError("Feishu message_id and file_key cannot be empty.")
        if max_bytes <= 0:
            raise FeishuBitableError("Message resource size limit must be positive.")

        path = (
            f"/im/v1/messages/{parse.quote(normalized_message_id, safe='')}"
            f"/resources/{parse.quote(normalized_file_key, safe='')}"
        )
        url = FEISHU_OPEN_API + path + "?" + parse.urlencode({"type": resource_type})
        req = request.Request(
            url,
            headers={"Authorization": f"Bearer {self.tenant_access_token()}"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                content = response.read(max_bytes + 1)
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc
        if len(content) > max_bytes:
            raise FeishuBitableError(
                f"Feishu message resource exceeds the {max_bytes} byte limit."
            )
        if not content:
            raise FeishuBitableError("Feishu returned an empty message resource.")
        return content

    def recognize_image_text(self, content: bytes) -> list[str]:
        if not content:
            raise FeishuBitableError("OCR image cannot be empty.")
        if len(content) > 5 * 1024 * 1024:
            raise FeishuBitableError("OCR image exceeds Feishu's 5 MB limit.")
        response = self._request(
            "POST",
            "/optical_char_recognition/v1/image/basic_recognize",
            payload={"image": base64.b64encode(content).decode("ascii")},
        )
        return [
            str(item).strip()
            for item in list(response.get("data", {}).get("text_list") or [])
            if str(item).strip()
        ]

    def reply_text_message(
        self,
        message_id: str,
        text: str,
        *,
        idempotency_key: str = "",
    ) -> str:
        normalized_text = text.strip()
        if not normalized_text:
            raise FeishuBitableError("Feishu reply text cannot be empty.")
        return self._reply_message(
            message_id,
            "text",
            {"text": normalized_text},
            idempotency_key=idempotency_key,
        )

    def reply_interactive_message(
        self,
        message_id: str,
        card: dict[str, Any],
        *,
        idempotency_key: str = "",
    ) -> str:
        if not card:
            raise FeishuBitableError("Feishu interactive reply card cannot be empty.")
        return self._reply_message(
            message_id,
            "interactive",
            card,
            idempotency_key=idempotency_key,
        )

    def _reply_message(
        self,
        message_id: str,
        message_type: str,
        content: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> str:
        normalized_message_id = message_id.strip()
        if not normalized_message_id:
            raise FeishuBitableError("Feishu reply message_id cannot be empty.")
        stable_key = idempotency_key.strip() or normalized_message_id
        reply_uuid = "pudu-" + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:32]
        response = self._request(
            "POST",
            f"/im/v1/messages/{parse.quote(normalized_message_id, safe='')}/reply",
            payload={
                "msg_type": message_type,
                "content": json.dumps(content, ensure_ascii=False),
                "uuid": reply_uuid,
            },
        )
        reply_message_id = str(response.get("data", {}).get("message_id", "")).strip()
        if not reply_message_id:
            raise FeishuBitableError("Feishu did not return a reply message_id.")
        return reply_message_id

    def batch_create_records(self, table_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records/batch_create",
            payload={"records": [{"fields": fields} for fields in records]},
        )
        return list(response.get("data", {}).get("records", []))

    def batch_update_records(
        self,
        table_id: str,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records/batch_update",
            payload={
                "records": [
                    {
                        "record_id": str(record["record_id"]),
                        "fields": dict(record.get("fields") or {}),
                    }
                    for record in records
                ]
            },
        )
        return list(response.get("data", {}).get("records", []))

    def batch_delete_records(self, table_id: str, record_ids: list[str]) -> None:
        if not record_ids:
            return
        self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records/batch_delete",
            params={"ignore_consistency_check": "false"},
            payload={"records": [str(record_id) for record_id in record_ids]},
        )

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            "PUT",
            (
                f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}"
                f"/records/{parse.quote(record_id)}"
            ),
            payload={"fields": fields},
        )
        return dict(response.get("data", {}).get("record", {}))

    def delete_record(self, table_id: str, record_id: str) -> None:
        self._request(
            "DELETE",
            (
                f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}"
                f"/records/{parse.quote(record_id)}"
            ),
        )

    def discover_schema(self) -> dict[str, Any]:
        tables = self.list_tables()
        result: dict[str, Any] = {"tables": {}}
        for table in tables:
            table_id = str(table.get("table_id", ""))
            table_name = str(table.get("name", ""))
            fields = self.list_fields(table_id) if table_id else []
            result["tables"][table_name] = {
                "table_id": table_id,
                "name": table_name,
                "fields": {
                    str(field.get("field_name", "")): {
                        "field_id": field.get("field_id", ""),
                        "type": field.get("type"),
                    }
                    for field in fields
                },
            }
        return result

    def _paged_get(
        self,
        path: str,
        data_key: str,
        page_size: int = 100,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            request_params = dict(params or {})
            request_params["page_size"] = page_size
            if page_token:
                request_params["page_token"] = page_token
            response = self._request("GET", path, params=request_params)
            data = response.get("data", {})
            items.extend(data.get(data_key) or [])
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token", ""))
            if not page_token:
                break
        return items

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = FEISHU_OPEN_API + path
        if params:
            url += "?" + parse.urlencode(params)

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers["Authorization"] = f"Bearer {self.tenant_access_token()}"

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc

        if data.get("code") != 0:
            raise FeishuBitableError(f"Feishu API {data.get('code')}: {data.get('msg')}")
        return data

    def _quoted_app_token(self) -> str:
        return parse.quote(self.config.app_token)
