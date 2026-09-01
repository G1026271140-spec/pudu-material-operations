from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_CONFIG_PATH = PROJECT_ROOT / "config" / "project_config.json"
_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {}
_CACHE_MTIME_NS: int | None = None


def _load_config() -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME_NS
    try:
        mtime_ns = PROJECT_CONFIG_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    with _LOCK:
        if _CACHE_MTIME_NS == mtime_ns:
            return _CACHE
        raw = json.loads(PROJECT_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config/project_config.json 的根节点必须是对象。")
        _CACHE = raw
        _CACHE_MTIME_NS = mtime_ns
        return _CACHE


def get_setting(path: str, default: Any = None) -> Any:
    """Read a dotted project setting, with an optional PUDU_* env override."""
    env_name = "PUDU_" + path.replace(".", "_").upper()
    if env_name in os.environ:
        raw = os.environ[env_name]
        if isinstance(default, bool):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(default, int) and not isinstance(default, bool):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return raw
    value: Any = _load_config()
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def expand_setting_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()
