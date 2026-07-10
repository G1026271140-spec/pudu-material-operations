from __future__ import annotations

import json
import time
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

    def list_records(self, table_id: str, page_size: int = 500) -> list[dict[str, Any]]:
        return self._paged_get(
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records",
            "items",
            page_size=page_size,
        )

    def batch_create_records(self, table_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"/bitable/v1/apps/{self._quoted_app_token()}/tables/{parse.quote(table_id)}/records/batch_create",
            payload={"records": [{"fields": fields} for fields in records]},
        )
        return list(response.get("data", {}).get("records", []))

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

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/authen/v2/oauth/token",
            auth=False,
            payload={
                "grant_type": "authorization_code",
                "client_id": self.config.app_id,
                "client_secret": self.config.app_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        return dict(response.get("data") or {})

    def oauth_user_info(self, user_access_token: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            "/authen/v1/user_info",
            auth=False,
            bearer_token=user_access_token,
        )
        return dict(response.get("data") or {})

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
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            response = self._request("GET", path, params=params)
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
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        url = FEISHU_OPEN_API + path
        if params:
            url += "?" + parse.urlencode(params)

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        elif auth:
            headers["Authorization"] = f"Bearer {self.tenant_access_token()}"

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise FeishuBitableError(f"Feishu HTTP {exc.code}: {text}") from exc

        if str(data.get("code", 0)) != "0":
            raise FeishuBitableError(f"Feishu API {data.get('code')}: {data.get('msg')}")
        return data

    def _quoted_app_token(self) -> str:
        return parse.quote(self.config.app_token)
