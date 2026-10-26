"""Feishu sign-in for the public request site.

Only the server sees Feishu tokens. The browser receives a short-lived,
signed, HttpOnly session after its tenant matches the application's tenant.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time
import tomllib
from functools import lru_cache
from pathlib import Path
from urllib import parse, request

from fastapi import HTTPException
from backend_runtime import secret


ROOT = Path(__file__).resolve().parents[1]
OPEN_API = "https://open.feishu.cn/open-apis"
SESSION_SECONDS = 30 * 24 * 3600
STATE_SECONDS = 10 * 60
_pending_states: dict[str, tuple[str, int]] = {}
_state_lock = threading.Lock()
WORKPLACE_TICKET_SECONDS = 90
WORKPLACE_RETURN_PATH = "/auth/feishu/workplace-handoff"
_workplace_tickets: dict[str, tuple[str, str, dict[str, str], int]] = {}
_ticket_lock = threading.Lock()


@lru_cache(maxsize=1)
def credentials() -> tuple[str, str]:
    app_id = secret("FEISHU_APP_ID", root=ROOT)
    app_secret = secret("FEISHU_APP_SECRET", root=ROOT)
    if not app_id or not app_secret:
        raise RuntimeError("Feishu application credentials are not configured")
    return app_id, app_secret


@lru_cache(maxsize=1)
def public_origin() -> str:
    values = json.loads((ROOT / "config" / "project_config.json").read_text(encoding="utf-8"))
    origin = secret("PUDU_PUBLIC_ORIGIN", str(values["deployment"]["custom_domain"])).rstrip("/")
    parsed = parse.urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path:
        raise RuntimeError("Public web origin must be an HTTPS origin")
    return origin


def callback_url() -> str:
    return f"{public_origin()}/auth/feishu/callback"


def workplace_authorization_url(state: str) -> str:
    app_id, _ = credentials()
    return "https://open.feishu.cn/open-apis/authen/v1/index?" + parse.urlencode(
        {"app_id": app_id, "redirect_uri": callback_url(), "state": state}
    )


def create_workplace_ticket(open_id: str, tenant_key: str, profile: dict[str, str]) -> str:
    ticket = secrets.token_urlsafe(32)
    expires = int(time.time()) + WORKPLACE_TICKET_SECONDS
    with _ticket_lock:
        for old, data in list(_workplace_tickets.items()):
            if data[3] <= time.time():
                _workplace_tickets.pop(old, None)
        if len(_workplace_tickets) >= 10000:
            _workplace_tickets.pop(next(iter(_workplace_tickets)))
        _workplace_tickets[ticket] = (open_id, tenant_key, profile, expires)
    return ticket


def consume_workplace_ticket(ticket: str) -> tuple[str, str, dict[str, str]] | None:
    if not ticket or len(ticket) > 128:
        return None
    with _ticket_lock:
        payload = _workplace_tickets.pop(ticket, None)
    if payload is None or payload[3] <= time.time():
        return None
    return payload[:3]


def is_public_host(host: str) -> bool:
    return host.split(":", 1)[0].lower() == parse.urlsplit(public_origin()).hostname


def safe_return_path(value: str) -> str:
    # A local path only. Never allow an OAuth callback to become an open redirect.
    if not value.startswith("/") or value.startswith("//") or "\\" in value or "\r" in value or "\n" in value:
        return "/"
    return value[:2048]


def _sign(payload: bytes) -> str:
    secret = credentials()[1].encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _unsign(value: str) -> dict[str, object] | None:
    try:
        encoded, signature = value.split(".", 1)
        expected = hmac.new(credentials()[1].encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None


def create_session(open_id: str, tenant_key: str, *, name: str = "", avatar_url: str = "") -> str:
    body = {
        "open_id": open_id,
        "tenant_key": tenant_key,
        "name": name[:120],
        "avatar_url": avatar_url[:600] if avatar_url.startswith("https://") else "",
        "expires": int(time.time()) + SESSION_SECONDS,
    }
    return _sign(json.dumps(body, separators=(",", ":")).encode("utf-8"))


def session_identity(value: str, tenant_key: str) -> dict[str, str] | None:
    body = _unsign(value) if value else None
    if not (
        body
        and body.get("tenant_key") == tenant_key
        and isinstance(body.get("open_id"), str)
        and str(body["open_id"]).startswith("ou_")
        and isinstance(body.get("expires"), int)
        and int(body["expires"]) > time.time()
    ):
        return None
    return {
        "open_id": str(body["open_id"]),
        "name": str(body.get("name") or ""),
        "avatar_url": str(body.get("avatar_url") or ""),
    }


def valid_session(value: str, tenant_key: str) -> bool:
    return session_identity(value, tenant_key) is not None


def _feishu(method: str, path: str, *, token: str = "", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(f"{OPEN_API}{path}", data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=12) as result:
        body = json.load(result)
    if body.get("code") != 0:
        raise RuntimeError(f"Feishu API {path} failed with code {body.get('code')}")
    return body


@lru_cache(maxsize=1)
def _tenant_token() -> tuple[str, float]:
    app_id, app_secret = credentials()
    result = _feishu("POST", "/auth/v3/tenant_access_token/internal", payload={"app_id": app_id, "app_secret": app_secret})
    return str(result["tenant_access_token"]), time.time() + int(result.get("expire", 7200)) - 120


def _current_tenant_token() -> str:
    token, expires = _tenant_token()
    if time.time() >= expires:
        _tenant_token.cache_clear()
        token, _ = _tenant_token()
    return token


@lru_cache(maxsize=1)
def _tenant_identity() -> tuple[str, float]:
    result = _feishu("GET", "/tenant/v2/tenant/query", token=_current_tenant_token())
    tenant = str((result.get("data") or {}).get("tenant", {}).get("tenant_key") or "").strip()
    if not tenant:
        raise RuntimeError("Feishu did not provide the application tenant key")
    return tenant, time.time() + 3600


def own_tenant_key() -> str:
    tenant, expires = _tenant_identity()
    if time.time() >= expires:
        _tenant_identity.cache_clear()
        tenant, _ = _tenant_identity()
    return tenant


def authorization_url(state: str) -> str:
    app_id, _ = credentials()
    return "https://open.feishu.cn/open-apis/authen/v1/authorize?" + parse.urlencode(
        {"app_id": app_id, "redirect_uri": callback_url(), "state": state}
    )


@lru_cache(maxsize=1)
def _app_token() -> tuple[str, float]:
    app_id, app_secret = credentials()
    result = _feishu(
        "POST", "/auth/v3/app_access_token/internal",
        payload={"app_id": app_id, "app_secret": app_secret},
    )
    return str(result["app_access_token"]), time.time() + int(result.get("expire", 7200)) - 120


def _current_app_token() -> str:
    token, expires = _app_token()
    if time.time() >= expires:
        _app_token.cache_clear()
        token, _ = _app_token()
    return token


def exchange_code(code: str) -> tuple[str, str, dict[str, str]]:
    result = _feishu("POST", "/authen/v1/access_token", token=_current_app_token(), payload={"grant_type": "authorization_code", "code": code})
    user_token = str((result.get("data") or {}).get("access_token") or "")
    if not user_token:
        raise RuntimeError("Feishu did not issue a user access token")
    user = _feishu("GET", "/authen/v1/user_info", token=user_token).get("data") or {}
    open_id = str(user.get("open_id") or "")
    tenant_key = str(user.get("tenant_key") or "")
    if not open_id.startswith("ou_") or not tenant_key:
        raise HTTPException(status_code=403, detail="无法验证飞书用户的企业身份")
    return open_id, tenant_key, {
        "name": str(user.get("name") or "").strip(),
        "avatar_url": str(user.get("avatar_url") or "").strip(),
    }


def new_state(return_path: str = "/") -> str:
    """Create a short signed, one-use OAuth state independent of browser cookies.

    Feishu can hand a workplace page to another browser before returning to
    our callback, so a cookie-only state check rejects legitimate sign-ins.
    """
    expires = int(time.time()) + STATE_SECONDS
    nonce = secrets.token_urlsafe(24)
    state = _sign(f"{nonce}:{expires}".encode("ascii"))
    with _state_lock:
        for old_state, (_, old_expiry) in list(_pending_states.items()):
            if old_expiry <= time.time():
                _pending_states.pop(old_state, None)
        if len(_pending_states) >= 10000:
            _pending_states.pop(next(iter(_pending_states)))
        _pending_states[state] = (safe_return_path(return_path), expires)
    return state


def consume_state(state: str) -> str | None:
    if not state or len(state) > 256:
        return None
    try:
        encoded, _ = state.split(".", 1)
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
        _, expires_text = decoded.rsplit(":", 1)
        expires = int(expires_text)
        expected = _sign(decoded.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error):
        return None
    if not hmac.compare_digest(state, expected) or expires <= time.time():
        return None
    with _state_lock:
        pending = _pending_states.pop(state, None)
    if not pending or pending[1] != expires:
        return None
    return pending[0]
