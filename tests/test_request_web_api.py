from fastapi.testclient import TestClient

from request_web.api import api, build_catalog


def test_catalog_uses_local_snapshot_and_exposes_all_products():
    catalog = build_catalog()
    assert len(catalog["products"]) == 11
    assert len(catalog["users"]) > 100
    assert catalog["rolesByUser"]
    assert all(product["options"] for product in catalog["products"])


def test_health_endpoint():
    response = TestClient(api).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workspace_excludes_gift_page_and_reads_cached_surfaces():
    payload = TestClient(api).get("/api/workspace").json()
    assert payload["inventory"]
    assert payload["categories"]
    assert payload["models"]
    assert payload["languages"]
    assert "giftProjects" not in payload
