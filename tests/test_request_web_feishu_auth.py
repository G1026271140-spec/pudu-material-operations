from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlsplit

from request_web import feishu_auth
from request_web import api as web_api
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
        assert client.get("/favicon.ico").status_code == 200


def test_callback_checks_tenant_and_restores_direct_page(monkeypatch):
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    monkeypatch.setattr(feishu_auth, "exchange_code", lambda code: ("ou_user", "own-tenant", {"name": "测试用户", "avatar_url": ""}))
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as starter:
        start = starter.get("/auth/feishu/start?next=%2Fcorporate-apparel")
    assert start.status_code == 303
    assert "open.feishu.cn" in start.headers["location"]
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    # Feishu workplace may open a separate browser with no start-page cookies.
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as client:
        bad = client.get("/auth/feishu/callback?code=ok&state=wrong")
        assert bad.status_code == 400
        callback = client.get(f"/auth/feishu/callback?code=ok&state={state}")
        assert callback.status_code == 303
        assert callback.headers["location"] == "/corporate-apparel"
        assert "httponly" in callback.headers["set-cookie"].lower()
        assert "Max-Age=2592000" in callback.headers["set-cookie"]
        assert client.get("/api/admin/status").status_code == 200
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["name"] == "测试用户"
        assert me.headers["cache-control"] == "no-store"
        logout = client.get("/auth/feishu/logout")
        assert logout.status_code == 303
        assert logout.headers["location"] == "/auth/feishu/signed-out"
        assert client.get("/auth/feishu/signed-out").status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert client.get(f"/auth/feishu/callback?code=ok&state={state}").status_code == 400


def test_foreign_tenant_is_rejected(monkeypatch):
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    monkeypatch.setattr(feishu_auth, "exchange_code", lambda code: ("ou_foreign", "foreign-tenant", {"name": "访客", "avatar_url": ""}))
    with TestClient(api, base_url=PUBLIC, follow_redirects=False) as client:
        start = client.get("/auth/feishu/start")
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        response = client.get(f"/auth/feishu/callback?code=ok&state={state}")
        assert response.status_code == 403
        assert not client.cookies.get("pudu_feishu")


def test_signed_session_rejects_tampering_and_expiry(monkeypatch):
    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("app", "secret"))
    issued_at = 1_800_000_000
    monkeypatch.setattr(feishu_auth.time, "time", lambda: issued_at)
    token = feishu_auth.create_session("ou_user", "own-tenant")
    assert feishu_auth.valid_session(token, "own-tenant")
    assert not feishu_auth.valid_session(token, "another-tenant")
    assert not feishu_auth.valid_session(token + "x", "own-tenant")
    monkeypatch.setattr(feishu_auth.time, "time", lambda: issued_at + 30 * 24 * 3600 - 1)
    assert feishu_auth.valid_session(token, "own-tenant")
    monkeypatch.setattr(feishu_auth.time, "time", lambda: issued_at + 30 * 24 * 3600)
    assert not feishu_auth.valid_session(token, "own-tenant")


def test_current_user_display_roles_do_not_create_permissions(monkeypatch):
    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("app", "secret"))
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    permission_rows = []
    def cached_data(name):
        if name == "contact_departments_cache.json":
            return {"users": [{"open_id": "ou_user", "name": "目录姓名", "department_ids": ["d1"], "department_paths": ["市场部"]}]}
        return {"tables": {"用户权限表": permission_rows}}
    monkeypatch.setattr(web_api, "_json", cached_data)
    token = feishu_auth.create_session("ou_user", "own-tenant", name="登录姓名")
    with TestClient(api, base_url=PUBLIC) as client:
        client.cookies.set("pudu_feishu", token)
        new_user = client.get("/api/auth/me").json()
        assert new_user["name"] == "登录姓名"
        assert new_user["roles"] == ["销售"]
        assert new_user["permission_status"] == "missing"
        assert permission_rows == []
        permission_rows.append({"fields": {"用户账号": [{"id": "ou_user"}], "是否启用": "否", "角色": ["管理员"]}})
        disabled = client.get("/api/auth/me").json()
        assert disabled["roles"] == []
        assert disabled["permission_status"] == "disabled"
        permission_rows[0]["fields"]["是否启用"] = "是"
        enabled = client.get("/api/auth/me").json()
        assert enabled["roles"] == ["管理员"]
        assert enabled["permission_status"] == "enabled"


def test_management_requires_enabled_admin_role_not_old_password_cookie(monkeypatch):
    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("app", "secret"))
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "own-tenant")
    rows = []
    monkeypatch.setattr(
        web_api, "_json",
        lambda _name: {"tables": {"用户权限表": rows}},
    )
    monkeypatch.setattr(web_api, "_management_snapshot", lambda: {"categories": []})
    token = feishu_auth.create_session("ou_user", "own-tenant")
    with TestClient(api, base_url=PUBLIC) as client:
        client.cookies.set("pudu_feishu", token)
        client.cookies.set("pudu_admin", "old-password-session")
        assert client.get("/api/admin/status").json() == {"unlocked": False}
        assert client.get("/api/admin/management-catalog").status_code == 403
        assert client.post("/api/admin/unlock", json={"password": "anything"}).status_code == 405

        rows.append({"fields": {
            "用户账号": [{"id": "ou_user"}], "是否启用": "是",
            "角色": ["销售", "区域市场经理"],
        }})
        assert client.get("/api/admin/management-catalog").status_code == 403

        rows[0]["fields"]["角色"].append("管理员")
        assert client.get("/api/admin/status").json() == {"unlocked": True}
        assert client.get("/api/admin/management-catalog").status_code == 200

        rows[0]["fields"]["是否启用"] = "否"
        assert client.get("/api/admin/management-catalog").status_code == 403


def test_return_path_cannot_leave_site():
    assert feishu_auth.safe_return_path("https://evil.example/") == "/"
    assert feishu_auth.safe_return_path("//evil.example/") == "/"
    assert feishu_auth.safe_return_path("/corporate-apparel") == "/corporate-apparel"


def test_oauth_state_is_signed_one_use_and_expires(monkeypatch):
    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("app", "secret"))
    state = feishu_auth.new_state("/cultural")
    assert feishu_auth.consume_state(state + "x") is None
    assert feishu_auth.consume_state(state) == "/cultural"
    assert feishu_auth.consume_state(state) is None
    expired = feishu_auth.new_state("/request")
    monkeypatch.setattr(feishu_auth.time, "time", lambda: 99999999999)
    assert feishu_auth.consume_state(expired) is None
