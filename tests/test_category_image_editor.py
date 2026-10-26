from contextlib import contextmanager
from copy import deepcopy
import importlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app
from category_media import apply_category_media, validate_image_selection
from material_store import media

web = importlib.import_module("request_web.api")


def png():
    output = BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def category(monkeypatch):
    state = {"申领页图片": [
        {"file_token": "old", "name": "old.png"},
        {"file_token": "model", "name": "model.glb"},
        {"file_token": "html", "name": "viewer.html"},
    ]}
    names = {item["file_token"]: item["name"] for item in state["申领页图片"]}
    names["new"] = "new.png"
    def write(_table, _id, fields):
        state.update({key: [{**item, "name": names[item["file_token"]]} for item in value]
                      if key == "申领页图片" else value for key, value in fields.items()})
    update = Mock(side_effect=write)
    client = SimpleNamespace(get_record=lambda *_: {"fields": deepcopy(state)})
    monkeypatch.setattr(app, "feishu_client", lambda: client)
    monkeypatch.setattr(app, "feishu_table_id", lambda _: "table")
    monkeypatch.setattr(app, "feishu_update_record_fields", update)
    monkeypatch.setattr(media, "remote_token", lambda *_: "new")
    return state, update


def test_removing_all_category_images_preserves_glb_and_html(category):
    _, update = category
    apply_category_media("category", {"images": [], "expected_image_tokens": ["old"]})
    assert update.call_args.args[2] == {"申领页图片": [{"file_token": "model"}, {"file_token": "html"}]}


def test_replacing_image_keeps_other_attachments_and_retry_is_idempotent(category):
    _, update = category
    selection = {"images": [{"local_media_id": str(uuid4())}], "expected_image_tokens": ["old"]}
    apply_category_media("category", selection)
    apply_category_media("category", selection)
    assert update.call_count == 2
    assert update.call_args.args[2]["申领页图片"] == [
        {"file_token": "model"}, {"file_token": "html"}, {"file_token": "new"}]


def test_changed_remote_images_reject_stale_edit(category):
    state, update = category
    state["申领页图片"].insert(0, {"file_token": "manual", "name": "manual.png"})
    with pytest.raises(ValueError, match="已发生变化"):
        apply_category_media("category", {"images": [], "expected_image_tokens": ["old"]})
    update.assert_not_called()


@pytest.mark.parametrize("selection", [
    {"images": [], "expected_image_tokens": None},
    {"images": [{"file_token": "another-category"}], "expected_image_tokens": ["old"]},
    {"images": [{"local_media_id": "../../secret"}], "expected_image_tokens": []},
])
def test_invalid_or_unrelated_images_are_rejected(selection):
    with pytest.raises(ValueError):
        validate_image_selection(selection)


def test_png_is_verified_and_html_disguised_as_image_is_rejected():
    assert media.validate_image(png()) == ("image/png", ".png")
    with pytest.raises(ValueError):
        media.validate_image(b"<html>not an image</html>")
    with pytest.raises(ValueError):
        media.validate_image(b"x" * (media.MAX_IMAGE_BYTES + 1))


def test_local_save_persists_before_return_and_ignores_filename_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PUDU_MEDIA_ROOT", str(tmp_path))
    execute = Mock()
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(media, "connection", connection)
    result = media.save_image(png(), "../../image.png", "ou-admin")
    assert result["name"] == "image.png"
    assert (tmp_path / (result["local_media_id"] + ".png")).read_bytes() == png()
    assert execute.call_args.args[1][-1] == "ou-admin"


def test_failed_database_insert_cleans_up_uncommitted_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PUDU_MEDIA_ROOT", str(tmp_path))
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=Mock(side_effect=RuntimeError("DB unavailable")))
    monkeypatch.setattr(media, "connection", connection)
    with pytest.raises(RuntimeError):
        media.save_image(png(), "image.png", "ou-admin")
    assert list(tmp_path.iterdir()) == []


def test_upload_requires_existing_admin_authorization(monkeypatch):
    monkeypatch.setattr(web, "_signed_admin_open_id", lambda _: "")
    client = TestClient(web.api)
    assert client.post("/api/admin/category-images", content=png()).status_code == 403
    assert client.get("/api/admin/category-images/" + str(uuid4())).status_code == 403


def test_category_submit_keeps_optional_media_and_omission_means_unchanged(monkeypatch):
    monkeypatch.setattr(web, "_signed_admin_open_id", lambda _: "ou-admin")
    enqueue = Mock(return_value="task")
    monkeypatch.setattr(web, "_enqueue_fast", enqueue)
    body = {"operation": "edit", "submission_token": "test", "sync_args": {}, "draft": {}}
    client = TestClient(web.api)
    assert client.post("/api/admin/category/submit", json=body).status_code == 200
    assert "category_media" not in enqueue.call_args.args[2]
    selection = {"images": [], "expected_image_tokens": ["old"]}
    assert client.post("/api/admin/category/submit", json={**body, "category_media": selection}).status_code == 200
    assert enqueue.call_args.args[2]["category_media"] == selection
