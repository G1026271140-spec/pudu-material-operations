from __future__ import annotations

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
            items.extend(data.get(data_key, []))
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
