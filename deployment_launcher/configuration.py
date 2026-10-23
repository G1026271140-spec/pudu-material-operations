from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import DeploymentConfig


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def secrets_for(config: DeploymentConfig) -> dict[str, object]:
    data: dict[str, object] = dict(config.extra_secrets)
    data.update(
        {
            "INVENTORY_VIEW_PASSWORD": config.inventory_password,
            "APPROVAL_VIEW_PASSWORD": config.approval_password,
            "FEISHU_APP_ID": config.feishu_app_id,
            "FEISHU_APP_SECRET": config.feishu_app_secret,
            "FEISHU_BITABLE_APP_TOKEN": config.feishu_bitable_app_token,
            "FEISHU_BITABLE_WEB_URL": config.feishu_bitable_web_url,
            "FEISHU_APPROVAL_WRITEBACK_APP_ID": config.approval_writeback_app_id,
            "FEISHU_APPROVAL_WRITEBACK_APP_SECRET": config.approval_writeback_app_secret,
            "GITHUB_CACHE_REFRESH_TOKEN": config.github_token,
            "CLOUDFLARE_TUNNEL_TOKEN": config.cloudflare_tunnel_token,
            "STREAMLIT_APP_URL": config.public_url + "/",
        }
    )
    return {key: value for key, value in data.items() if value not in (None, "")}


def write_deployment_configuration(root: Path, config: DeploymentConfig) -> None:
    project_path = root / "config" / "project_config.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.setdefault("project", {})["github_repository"] = config.repository
    project["project"]["github_branch"] = config.branch
    project.setdefault("deployment", {})["custom_domain"] = config.public_url
    local = project["deployment"].setdefault("local_web", {})
    local["address"] = "127.0.0.1"
    local["port"] = int(config.port)
    _atomic_write(project_path, json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    secret_lines = [f"{key} = {_toml_value(value)}" for key, value in sorted(secrets_for(config).items())]
    secret_path = root / ".streamlit" / "secrets.toml"
    _atomic_write(secret_path, "\n".join(secret_lines) + "\n")
