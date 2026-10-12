from fastapi.testclient import TestClient

from request_web import feishu_auth
from request_web.api import api


PUBLIC = "https://pudu-material-operations.gaohongyuan.me"


def test_public_page_and_api_require_feishu_login(monkeypatch):
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as client:
        page = client.get("/corporate-apparel")
        assert page.status_code == 303
        assert page.headers["location"].startswith("/auth/feishu/start?")
        assert client.get("/api/admin/status").status_code == 401
        assert client.get("/api/health").status_code == 200


def test_callback_checks_tenant_and_restores_direct_page(monkeypatch):
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    monkeypatch.setattr(feishu_auth, "exchange_code", lambda code: ("ou_user", "own-tenant"))
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as client:
        start = client.get("/auth/feishu/start?next=%2Fcorporate-apparel")
        assert start.status_code == 303
        assert "open.feishu.cn" in start.headers["location"]
        state = client.cookies.get("pudu_feishu_state")
        bad = client.get("/auth/feishu/callback?code=ok&state=wrong")
        assert bad.status_code == 400
        callback = client.get(f"/auth/feishu/callback?code=ok&state={state}")
        assert callback.status_code == 303
        assert callback.headers["location"] == "/corporate-apparel"
        assert "httponly" in callback.headers["set-cookie"].lower()
        assert client.get("/api/admin/status").status_code == 200


def test_foreign_tenant_is_rejected(monkeypatch):
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    monkeypatch.setattr(feishu_auth, "exchange_code", lambda code: ("ou_foreign", "foreign-tenant"))
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as client:
        client.get("/auth/feishu/start")
        state = client.cookies.get("pudu_feishu_state")
        response = client.get(f"/auth/feishu/callback?code=ok&state={state}")
        assert response.status_code == 403
        assert not client.cookies.get("pudu_feishu")


def test_signed_session_rejects_tampering_and_expiry(monkeypatch):
    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("app", "secret"))
    token = feishu_auth.create_session("ou_user", "own-tenant")
    assert feishu_auth.valid_session(token, "own-tenant")
    assert not feishu_auth.valid_session(token, "another-tenant")
    assert not feishu_auth.valid_session(token + "x", "own-tenant")
    monkeypatch.setattr(feishu_auth.time, "time", lambda: 99999999999)
    assert not feishu_auth.valid_session(token, "own-tenant")


def test_return_path_cannot_leave_site():
    assert feishu_auth.safe_return_path("https://evil.example/") == "/"
    assert feishu_auth.safe_return_path("//evil.example/") == "/"
    assert feishu_auth.safe_return_path("/corporate-apparel") == "/corporate-apparel"
