from __future__ import annotations

import json
from pathlib import Path

import pytest

from deployment_launcher.bundle import export_bundle, import_bundle
from deployment_launcher.cloudflare import CloudflareError, configure_cloudflare, manual_instructions
from deployment_launcher.models import CloudflareMode, DeploymentConfig, DeploymentMode, normalize_hostname
from deployment_launcher.plan import build_plan
from deployment_launcher.prerequisites import PREREQUISITES, _is_compatible
from deployment_launcher.release import bump_release_version_files, next_patch_version


def valid_config(**overrides: object) -> DeploymentConfig:
    values: dict[str, object] = {
        "install_root": r"C:\PuduMaterialOperations",
        "hostname": "materials.example.com",
        "port": 8501,
        "cloudflare_mode": CloudflareMode.MANUAL,
        "cloudflare_tunnel_token": "tunnel-token",
        "domain_ownership_confirmed": True,
        "feishu_app_id": "cli_test",
        "feishu_app_secret": "secret-value",
        "feishu_bitable_app_token": "base-token",
    }
    values.update(overrides)
    return DeploymentConfig(**values)


def test_hostname_normalization_and_rejection() -> None:
    assert normalize_hostname("HTTPS://Materials.Example.COM/") == "materials.example.com"
    with pytest.raises(ValueError):
        normalize_hostname("127.0.0.1")
    with pytest.raises(ValueError):
        normalize_hostname("not a domain")


def test_domain_ownership_confirmation_is_mandatory() -> None:
    config = valid_config(domain_ownership_confirmed=False)
    with pytest.raises(ValueError, match="域名归当前部署者"):
        config.validate()


def test_automatic_cloudflare_requires_scoped_configuration() -> None:
    config = valid_config(cloudflare_mode=CloudflareMode.AUTOMATIC, cloudflare_tunnel_token="")
    with pytest.raises(ValueError, match="Cloudflare API Token"):
        config.validate()
    config.cloudflare_api_token = "scoped-token"
    config.cloudflare_account_id = "a" * 32
    config.cloudflare_zone_id = "z" * 32
    config.validate()


def test_manual_mode_produces_concrete_instructions() -> None:
    text = "\n".join(manual_instructions(valid_config()))
    assert "materials.example.com" in text
    assert "http://127.0.0.1:8501" in text
    assert "CNAME" in text


def test_encrypted_bundle_round_trip_and_wrong_password(tmp_path: Path) -> None:
    config = valid_config(feishu_app_secret="never-plaintext")
    path = tmp_path / "migration.pudu-migration"
    export_bundle(path, config, "a-strong-password")
    raw = path.read_text(encoding="utf-8")
    assert "never-plaintext" not in raw
    assert import_bundle(path, "a-strong-password").feishu_app_secret == "never-plaintext"
    with pytest.raises(ValueError, match="密码错误"):
        import_bundle(path, "wrong-password")


def test_takeover_and_standby_have_distinct_activation_plans() -> None:
    takeover = [step.key for step in build_plan(valid_config(mode=DeploymentMode.TAKEOVER))]
    standby = [step.key for step in build_plan(valid_config(mode=DeploymentMode.STANDBY))]
    assert "tasks" in takeover and "cloudflare" in takeover
    assert "tasks" not in standby and "cloudflare" not in standby
    assert "standby" in standby


def test_required_prerequisites_are_installed_by_winget() -> None:
    mapping = {item.key: item.winget_id for item in PREREQUISITES}
    assert mapping == {
        "git": "Git.Git",
        "python": "Python.Python.3.12",
        "cloudflared": "Cloudflare.cloudflared",
    }


def test_python_prerequisite_requires_exact_312(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python_item = next(item for item in PREREQUISITES if item.key == "python")
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"placeholder")

    class Result:
        returncode = 0
        stdout = "3.14\n"

    monkeypatch.setattr("deployment_launcher.prerequisites._run", lambda *_args, **_kwargs: Result())
    assert _is_compatible(python_item, executable) is False
    Result.stdout = "3.12\n"
    assert _is_compatible(python_item, executable) is True


class FakeCloudflare:
    def __init__(self, conflicting_dns: bool = False) -> None:
        self.conflicting_dns = conflicting_dns
        self.deleted_tunnels: list[str] = []
        self.deleted_dns: list[str] = []

    def verify_zone(self, _zone: str) -> dict[str, object]:
        return {"name": "example.com"}

    def list_tunnels(self, _account: str, _name: str) -> list[dict[str, object]]:
        return []

    def create_tunnel(self, _account: str, _name: str) -> dict[str, object]:
        return {"id": "tunnel-id"}

    def configure_tunnel(self, *_args: object) -> None:
        return None

    def get_tunnel_token(self, *_args: object) -> str:
        return "generated-token"

    def list_dns(self, _zone: str, _host: str) -> list[dict[str, object]]:
        if self.conflicting_dns:
            return [{"id": "old", "content": "other.example.com"}]
        return []

    def create_dns(self, *_args: object) -> dict[str, object]:
        return {"id": "dns-id"}

    def delete_tunnel(self, _account: str, tunnel: str) -> None:
        self.deleted_tunnels.append(tunnel)

    def delete_dns(self, _zone: str, record: str) -> None:
        self.deleted_dns.append(record)


def test_cloudflare_reuses_nothing_and_returns_token() -> None:
    config = valid_config(
        cloudflare_mode=CloudflareMode.AUTOMATIC,
        cloudflare_api_token="api",
        cloudflare_account_id="account",
        cloudflare_zone_id="zone",
    )
    result = configure_cloudflare(config, client=FakeCloudflare())  # type: ignore[arg-type]
    assert result.tunnel_token == "generated-token"
    assert result.created_tunnel and result.created_dns_record


def test_cloudflare_does_not_overwrite_conflicting_dns_and_rolls_back_new_tunnel() -> None:
    config = valid_config(
        cloudflare_mode=CloudflareMode.AUTOMATIC,
        cloudflare_api_token="api",
        cloudflare_account_id="account",
        cloudflare_zone_id="zone",
    )
    client = FakeCloudflare(conflicting_dns=True)
    with pytest.raises(CloudflareError, match="不会自动覆盖"):
        configure_cloudflare(config, client=client)  # type: ignore[arg-type]
    assert client.deleted_tunnels == ["tunnel-id"]


def test_next_patch_version() -> None:
    assert next_patch_version("V2.9.4") == "V2.9.5"
    assert next_patch_version("V2.9.9") == "V3.0.0"


def test_bump_release_version_files_updates_source_and_test(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text('APP_VERSION = "V2.9.4"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_admin_access.py").write_text('self.assertEqual(app.APP_VERSION, "V2.9.4")\n', encoding="utf-8")
    assert bump_release_version_files(tmp_path) == ("V2.9.4", "V2.9.5")
    assert 'APP_VERSION = "V2.9.5"' in (tmp_path / "app.py").read_text(encoding="utf-8")


def test_old_control_center_has_been_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "control_center" / "app.py").exists()
    assert not (root / "scripts" / "run_control_center.ps1").exists()
    assert not (root / "scripts" / "build_control_center_app.ps1").exists()
    assert not (root / "docs" / "control_center.md").exists()
    assert (root / "scripts" / "run_deployment_launcher.ps1").exists()


def test_build_script_embeds_project_payload_and_new_launcher() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "build_deployment_launcher.ps1").read_text(encoding="utf-8")
    assert "project.zip" in script
    assert "PUDU Material Operations Setup" in script
    assert "--add-data" in script


def test_card_worker_installer_stops_stale_worker_processes() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "install_feishu_card_worker_task.ps1").read_text(encoding="utf-8-sig")
    assert "Get-CimInstance Win32_Process" in script
    assert "$escapedWorker" in script
    assert "Stop-Process -Id $process.ProcessId" in script
