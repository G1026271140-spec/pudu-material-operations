from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(os.environ.get("PUDU_PROJECT_ROOT") or (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]))
PROJECT_CONFIG_PATH = ROOT / "config" / "project_config.json"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
STREAMLIT_CONFIG_PATH = ROOT / ".streamlit" / "config.toml"
BACKUP_ROOT = ROOT / "work" / "control_center" / "backups"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    category: str
    source: str
    source_key: str
    description: str
    value_type: str = "str"
    sensitive: bool = False
    required: bool = False
    restart_scope: str = "无需重启"
    validator: Callable[[Any], None] | None = None


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        relative = Path(path.name)
    target = BACKUP_ROOT / timestamp / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    handle, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _get_dotted(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return ""
        value = value[part]
    return value


def _set_dotted(data: dict[str, Any], path: str, value: Any) -> None:
    node = data
    parts = path.split(".")
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"配置路径冲突：{path}")
        node = child
    node[parts[-1]] = value


def read_project_setting(path: str) -> Any:
    data = json.loads(PROJECT_CONFIG_PATH.read_text(encoding="utf-8"))
    return _get_dotted(data, path)


def write_project_setting(path: str, value: Any) -> None:
    data = json.loads(PROJECT_CONFIG_PATH.read_text(encoding="utf-8"))
    _set_dotted(data, path, value)
    _atomic_write(PROJECT_CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


_TOML_ASSIGNMENT = re.compile(r"^(?P<prefix>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*=.*$")
_TOML_SECTION = re.compile(r"^\s*\[(?P<section>[^]]+)]\s*$")


def _parse_toml_scalar(raw: str) -> Any:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return json.loads(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def read_toml_setting(path: Path, key: str, section: str = "") -> Any:
    if not path.exists():
        return ""
    active_section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        section_match = _TOML_SECTION.match(line)
        if section_match:
            active_section = section_match.group("section").strip()
            continue
        match = _TOML_ASSIGNMENT.match(line)
        if match and active_section == section and match.group("key") == key:
            return _parse_toml_scalar(line.split("=", 1)[1])
    return ""


def write_toml_setting(path: Path, key: str, value: Any, section: str = "") -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    active_section = ""
    section_start: int | None = 0 if not section else None
    section_end = len(lines)
    replacement = f"{key} = {_format_toml_scalar(value)}"
    for index, line in enumerate(lines):
        section_match = _TOML_SECTION.match(line)
        if section_match:
            next_section = section_match.group("section").strip()
            if active_section == section and section_start is not None:
                section_end = index
                break
            active_section = next_section
            if active_section == section:
                section_start = index + 1
            continue
        match = _TOML_ASSIGNMENT.match(line)
        if match and active_section == section and match.group("key") == key:
            lines[index] = replacement
            _atomic_write(path, "\n".join(lines) + "\n")
            return
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", replacement])
    else:
        lines.insert(section_end, replacement)
    _atomic_write(path, "\n".join(lines) + "\n")


def coerce_value(raw: str, value_type: str) -> Any:
    text = raw.strip()
    if value_type == "int":
        return int(text)
    if value_type == "float":
        return float(text)
    if value_type == "bool":
        lowered = text.lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("布尔值只能填写 true/false、1/0 或 yes/no。")
        return lowered in {"true", "1", "yes"}
    if value_type == "csv":
        return [item.strip() for item in text.split(",") if item.strip()]
    return text


def read_setting(spec: SettingSpec) -> Any:
    if spec.source == "project":
        return read_project_setting(spec.source_key)
    if spec.source == "secret":
        value = read_toml_setting(SECRETS_PATH, spec.source_key)
        if value not in (None, ""):
            return value
        if spec.source_key == "APPROVAL_VIEW_PASSWORD":
            return "pd123456"
        if spec.source_key == "CONTROL_CENTER_MASTER_PASSWORD":
            return read_toml_setting(SECRETS_PATH, "INVENTORY_VIEW_PASSWORD")
        if spec.source_key == "CLOUDFLARE_TUNNEL_TOKEN":
            runner_root = Path(os.path.expandvars(str(read_project_setting("deployment.local_web.runner_root"))))
            token_path = runner_root / "cloudflare-token.txt"
            if token_path.exists():
                return token_path.read_text(encoding="utf-8", errors="replace").strip()
        return ""
    if spec.source == "streamlit":
        section, key = spec.source_key.split(".", 1)
        return read_toml_setting(STREAMLIT_CONFIG_PATH, key, section)
    raise ValueError(f"不支持的配置来源：{spec.source}")


def write_setting(spec: SettingSpec, raw_value: str) -> Any:
    value = coerce_value(raw_value, spec.value_type)
    if spec.required and value in (None, ""):
        raise ValueError(f"{spec.label}不能为空。")
    if spec.validator:
        spec.validator(value)
    if spec.source == "project":
        write_project_setting(spec.source_key, value)
    elif spec.source == "secret":
        write_toml_setting(SECRETS_PATH, spec.source_key, value)
    elif spec.source == "streamlit":
        section, key = spec.source_key.split(".", 1)
        write_toml_setting(STREAMLIT_CONFIG_PATH, key, value, section)
    else:
        raise ValueError(f"不支持的配置来源：{spec.source}")
    return value
