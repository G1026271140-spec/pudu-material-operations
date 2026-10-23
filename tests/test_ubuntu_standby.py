from fastapi.testclient import TestClient
import pytest

from deployment.ubuntu.standby import api


def test_liveness_is_not_readiness():
    with TestClient(api) as client:
        response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['business_ready'] is False
    assert response.json()['mode'] == 'commissioning'
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('method,path', [
    ('GET', '/'), ('GET', '/api/catalog'), ('GET', '/api/auth/me'),
    ('GET', '/corporate-apparel'), ('POST', '/api/requests'),
    ('POST', '/api/corporate-exchange-sync'), ('POST', '/api/pending-inventory-sync'),
    ('GET', '/auth/feishu/start'), ('GET', '/docs'),
    ('GET', '/.streamlit/secrets.toml'), ('POST', '/api/health'),
])
def test_all_business_auth_and_webhook_routes_fail_closed(method, path):
    with TestClient(api) as client:
        response = client.request(method, path, headers={'Host': 'testserver'})
    assert response.status_code == 503
    assert response.json()['business_enabled'] is False
    assert response.json()['worker_enabled'] is False
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers


def test_standby_does_not_import_business_runtime_or_clients():
    # Keeps commissioning independent from app startup side effects/secrets.
    from pathlib import Path
    source = Path('deployment/ubuntu/standby.py').read_text(encoding='utf-8')
    assert 'import app' not in source
    assert 'from request_web' not in source
    assert 'feishu_bitable' not in source
