from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from control_center import configuration
from control_center.catalog import SETTINGS, configuration_location
from control_center.manual_tools import MANUAL_TOOLS
from control_center.release import bump_release_version_files, next_patch_version
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


def test_manual_tools_cover_all_cache_scopes_and_high_risk_sync() -> None:
    tools = {tool.key: tool for tool in MANUAL_TOOLS}
    assert {"MaterialCache", "ContactCache", "WarehouseCache", "AllCaches", "ValidateCaches"} <= tools.keys()
    assert tools["SyncAllRuntimes"].interrupts_services is True
    assert all(not tools[key].interrupts_services for key in ("MaterialCache", "ContactCache", "WarehouseCache", "AllCaches"))


def test_next_patch_version() -> None:
    assert next_patch_version("V1.9.4") == "V1.9.5"
    assert next_patch_version("V2.4.9") == "V2.5.0"
    assert next_patch_version("V1.9.10") == "V2.0.0"
    with pytest.raises(ValueError):
        next_patch_version("1.9")


def test_bump_release_version_files_updates_source_and_exact_test(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text('APP_VERSION = "V2.4.9"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_admin_access.py").write_text(
        'self.assertEqual(app.APP_VERSION, "V2.4.9")\n', encoding="utf-8"
    )
    assert bump_release_version_files(tmp_path) == ("V2.4.9", "V2.5.0")
    assert 'APP_VERSION = "V2.5.0"' in (tmp_path / "app.py").read_text(encoding="utf-8")
    assert 'app.APP_VERSION, "V2.5.0"' in (tmp_path / "tests" / "test_admin_access.py").read_text(encoding="utf-8")


def test_bump_release_version_cli_can_import_project_package(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text('APP_VERSION = "V3.1.7"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_admin_access.py").write_text(
        'self.assertEqual(app.APP_VERSION, "V3.1.7")\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "bump_release_version.py"), "--root", str(tmp_path)],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"current_version": "V3.1.7", "new_version": "V3.1.8"}


def test_release_pipeline_has_required_fail_closed_stages() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "run_control_center_release.ps1").read_text(encoding="utf-8")
    ordered = [
        'Set-Stage "发布预检"',
        'Set-Stage "递增应用版本"',
        'Set-Stage "刷新全部页面缓存"',
        'Set-Stage "完整测试与发布校验"',
        'Set-Stage "重新打包控制程序"',
        'Set-Stage "提交并推送 GitHub"',
        'Set-Stage "同步并重启运行组件"',
        'Set-Stage "运行状态与健康验证"',
    ]
    positions = [script.index(stage) for stage in ordered]
    assert positions == sorted(positions)
    assert "Sensitive files cannot be committed" in script
    assert 'Set-ReleaseStatus "failed"' in script


def test_launcher_rejects_stale_exe_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "run_control_center.ps1").read_text(encoding="utf-8")
    assert ".VersionInfo.ProductVersion" in launcher
    assert "$PackagedMetadataVersion -eq $SourceVersion" in launcher
