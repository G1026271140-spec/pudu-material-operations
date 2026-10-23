import json
import os
from datetime import datetime
from pathlib import Path

import pytest

import live_cache


def test_request_category_images_belong_to_material_publication() -> None:
    assert "assets/request_categories" in live_cache.GROUPS["Material"]
    assert "assets/request_categories" not in live_cache.GROUPS["Warehouse"]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def roots(tmp_path):
    source, target = tmp_path / "source", tmp_path / "web"
    for root in (source, target):
        root.mkdir()
        (root / "app.py").write_text('APP_VERSION = "V2.6.7"\n')
        (root / "live_cache.py").write_text("")
        write(root / "data/contact_departments_cache.json", {
            "generated_at": "2026-09-07 10:00:00", "departments": [{"id": "old"}],
            "row_count": 1, "users": [], "user_count": 0,
        })
    return source, target


def update_contacts(root, value="new", when="2026-09-07 11:00:00"):
    write(root / "data/contact_departments_cache.json", {
        "generated_at": when, "departments": [{"id": value}],
        "row_count": 1, "users": [], "user_count": 0,
    })


def test_publication_reads_new_data_without_changing_checkout_and_is_idempotent(roots):
    source, target = roots
    update_contacts(source)
    tracked = (target / "data/contact_departments_cache.json").read_bytes()
    result = live_cache.publish_cache(source, target, ("Contacts",))
    path = live_cache.resolve_cache_path(target, "data/contact_departments_cache.json")
    assert live_cache.read_json(path)["departments"] == [{"id": "new"}]
    assert (target / "data/contact_departments_cache.json").read_bytes() == tracked
    again = live_cache.publish_cache(source, target, ("Contacts",))
    assert not again["changed"]
    assert result["revision"] == again["revision"]


def test_invalid_copy_and_failed_pointer_switch_preserve_previous_generation(roots, monkeypatch):
    source, target = roots
    update_contacts(source)
    live_cache.publish_cache(source, target, ("Contacts",))
    pointer = (target / live_cache.PUBLICATION_DIR / "current.json").read_bytes()
    update_contacts(source, "newer", "2026-09-07 12:00:00")
    data = live_cache.read_json(source / "data/contact_departments_cache.json").copy()
    data["user_count"] = 3
    write(source / "data/contact_departments_cache.json", data)
    with pytest.raises(ValueError, match="user count"):
        live_cache.publish_cache(source, target, ("Contacts",))
    assert (target / live_cache.PUBLICATION_DIR / "current.json").read_bytes() == pointer
    update_contacts(source, "newer", "2026-09-07 12:00:00")
    monkeypatch.setattr(live_cache.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        live_cache.publish_cache(source, target, ("Contacts",))
    assert (target / live_cache.PUBLICATION_DIR / "current.json").read_bytes() == pointer


def test_newer_deployment_wins_and_stale_publications_are_rejected(roots):
    source, target = roots
    update_contacts(source)
    live_cache.publish_cache(source, target, ("Contacts",))
    update_contacts(target, "deployed", "2026-09-07 12:00:00")
    assert live_cache.resolve_cache_path(target, "data/contact_departments_cache.json") == target / "data/contact_departments_cache.json"
    with pytest.raises(ValueError, match="较旧缓存"):
        live_cache.publish_cache(source, target, ("Contacts",))
    (target / "app.py").write_text('APP_VERSION = "V2.6.8"\n')
    with pytest.raises(ValueError, match="版本"):
        live_cache.publish_cache(source, target, ("Contacts",))


def test_scope_isolation_and_pinned_render_keep_images_and_data_together(roots, monkeypatch):
    source, target = roots
    monkeypatch.setattr(live_cache, "validate_generation", lambda *args: None)
    for root in (source, target):
        write(root / "data/warehouse_location_cache.json", {"generated_at": "2026-09-07 10:00:00"})
        (root / "assets/warehouse_locations").mkdir(parents=True)
        (root / "assets/request_categories").mkdir(parents=True)
    image = source / "assets/warehouse_locations/shelf.webp"
    image.write_bytes(b"first")
    live_cache.publish_cache(source, target, ("Warehouse",))
    pinned = live_cache.read_manifest(target)
    image.write_bytes(b"second")
    live_cache.publish_cache(source, target, ("Warehouse",))
    update_contacts(source)
    live_cache.publish_cache(source, target, ("Contacts",))
    assert live_cache.resolve_cache_path(target, "assets/warehouse_locations/shelf.webp").read_bytes() == b"second"
    assert live_cache.resolve_cache_path(target, "assets/warehouse_locations/shelf.webp", pinned).read_bytes() == b"first"
    image.unlink()
    live_cache.publish_cache(source, target, ("Warehouse",))
    assert not live_cache.resolve_cache_path(target, "assets/warehouse_locations/shelf.webp").exists()
    with pytest.raises(ValueError, match="inside"):
        live_cache.resolve_cache_path(target, "../outside")


pass  # Retired widget test: test_browser_notice_does_not_rerun_or_clear_drafts_until_requested


def test_app_loader_switches_on_next_render_without_process_restart(roots, monkeypatch):
    import app
    source, target = roots
    relative = "data/contact_departments_cache.json"
    monkeypatch.setattr(app, "__file__", str(target / "app.py"))
    monkeypatch.setattr(app, "CONTACT_DEPARTMENT_STATIC_CACHE_PATH", target / relative)
    monkeypatch.setattr(app.runtime, "request_state", {"_live_cache_manifest": {}, "request_cart": ["kept"]})
    assert app.load_static_contact_department_cache()["departments"] == [{"id": "old"}]
    update_contacts(source)
    live_cache.publish_cache(source, target, ("Contacts",))
    # One active render remains coherent until the user starts the next render.
    assert app.load_static_contact_department_cache()["departments"] == [{"id": "old"}]
    app.prepare_live_cache_view()
    assert app.load_static_contact_department_cache()["departments"] == [{"id": "new"}]
    assert app.runtime.request_state["request_cart"] == ["kept"]


def test_refresh_observation_time_survives_preserved_git_timestamp(roots):
    source, target = roots
    update_contacts(target, "intermediate", "2026-09-07 12:00:00")
    # A live reread reverted to the old business values; the preservation script
    # restored their old JSON timestamp but wrote them during the current run.
    stamp = datetime(2026, 9, 7, 13, 0).timestamp()
    path = source / "data/contact_departments_cache.json"
    os.utime(path, (stamp, stamp))
    result = live_cache.publish_cache(source, target, ("Contacts",), freshly_generated=True)
    applied = live_cache.read_json(live_cache.resolve_cache_path(target, "data/contact_departments_cache.json"))
    assert applied["generated_at"] == "2026-09-07 13:00:00"
    assert applied["departments"] == [{"id": "old"}]
    assert live_cache.read_json(path)["generated_at"] == "2026-09-07 10:00:00"
    assert live_cache.publish_cache(source, target, ("Contacts",), freshly_generated=True)["revision"] == result["revision"]
