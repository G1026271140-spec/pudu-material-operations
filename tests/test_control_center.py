from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from control_center import configuration
from control_center.catalog import SETTINGS, configuration_location
from control_center.system import TASKS


def test_every_setting_has_storage_and_external_location() -> None:
    assert len(SETTINGS) >= 50
    for spec in SETTINGS:
        local, external = configuration_location(spec)
        assert local.strip(), spec.key
        assert external.strip(), spec.key
        assert spec.description.strip(), spec.key
        assert spec.restart_scope.strip(), spec.key


def test_sensitive_catalog_covers_operational_secrets() -> None:
    source_keys = {spec.source_key for spec in SETTINGS if spec.source == "secret"}
    assert {
        "INVENTORY_VIEW_PASSWORD",
        "APPROVAL_VIEW_PASSWORD",
        "CONTROL_CENTER_MASTER_PASSWORD",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_BITABLE_APP_TOKEN",
        "FEISHU_APPROVAL_WRITEBACK_APP_ID",
        "FEISHU_APPROVAL_WRITEBACK_APP_SECRET",
        "GITHUB_CACHE_REFRESH_TOKEN",
        "CLOUDFLARE_TUNNEL_TOKEN",
    } <= source_keys


def test_toml_update_preserves_other_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[server]\naddress = "0.0.0.0"\n\n[theme]\nprimaryColor = "#123456"\n', encoding="utf-8")
    configuration.write_toml_setting(path, "maxUploadSize", 64, "server")
    text = path.read_text(encoding="utf-8")
    assert 'address = "0.0.0.0"' in text
    assert "maxUploadSize = 64" in text
    assert 'primaryColor = "#123456"' in text
    assert configuration.read_toml_setting(path, "maxUploadSize", "server") == 64


def test_project_setting_update_is_nested_and_backed_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    config_path = root / "config" / "project_config.json"
    config_path.parent.mkdir()
    config_path.write_text('{"deployment":{"local_web":{"port":8501}}}\n', encoding="utf-8")
    monkeypatch.setattr(configuration, "ROOT", root)
    monkeypatch.setattr(configuration, "PROJECT_CONFIG_PATH", config_path)
    monkeypatch.setattr(configuration, "BACKUP_ROOT", root / "work" / "control_center" / "backups")
    configuration.write_project_setting("deployment.local_web.port", 8600)
    assert json.loads(config_path.read_text(encoding="utf-8"))["deployment"]["local_web"]["port"] == 8600
    backups = list((root / "work" / "control_center" / "backups").rglob("project_config.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["deployment"]["local_web"]["port"] == 8501


def test_versioned_approval_code_matches_anycross_blueprint() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config" / "project_config.json").read_text(encoding="utf-8"))
    raw = (root / "anycross.feishu" / "数据回写json.json").read_text(encoding="utf-8")
    match = re.search(r'"approval_code"\s*:\s*\{[^{}]*?"value"\s*:\s*"([^"]+)"', raw)
    assert match
    assert config["feishu"]["approval_definition_code"] == match.group(1)


def test_runtime_task_names_are_unique() -> None:
    names = [task.task_name for task in TASKS]
    assert all(names)
    assert len(names) == len(set(names))


def test_tunnel_runner_uses_configured_port() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = (root / "scripts" / "run_cloudflare_named_tunnel.ps1").read_text(encoding="utf-8")
    installer = (root / "scripts" / "install_local_web_app_task.ps1").read_text(encoding="utf-8")
    assert 'http://127.0.0.1:$Port' in runner
    assert '"-Port", $Port' in installer
