from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .configuration import ROOT


RELEASE_LOG_DIRECTORY = ROOT / "work" / "control_center" / "release"
RELEASE_STATUS_PATH = RELEASE_LOG_DIRECTORY / "latest-status.json"


@dataclass(frozen=True)
class ReleasePreview:
    branch: str
    revision: str
    current_version: str
    next_version: str
    changed_files: tuple[str, ...]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def next_patch_version(version: str) -> str:
    match = re.fullmatch(r"V(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"无法识别版本号：{version}")
    major, minor, patch = (int(part) for part in match.groups())
    if patch >= 9:
        patch = 0
        minor += 1
    else:
        patch += 1
    if minor >= 10:
        minor = 0
        major += 1
    return f"V{major}.{minor}.{patch}"


def bump_release_version_files(root: Path = ROOT) -> tuple[str, str]:
    app_path = root / "app.py"
    admin_test_path = root / "tests" / "test_admin_access.py"
    app_text = app_path.read_text(encoding="utf-8-sig")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', app_text, re.MULTILINE)
    if not match:
        raise RuntimeError("app.py 中未找到 APP_VERSION。")
    current_version = match.group(1)
    new_version = next_patch_version(current_version)
    replacement = f'APP_VERSION = "{new_version}"'
    app_text = app_text[: match.start()] + replacement + app_text[match.end() :]
    admin_test = admin_test_path.read_text(encoding="utf-8-sig")
    old_assertion = f'self.assertEqual(app.APP_VERSION, "{current_version}")'
    new_assertion = f'self.assertEqual(app.APP_VERSION, "{new_version}")'
    if old_assertion not in admin_test:
        raise RuntimeError("版本测试未包含当前 APP_VERSION，已停止自动递增。")
    app_path.write_text(app_text, encoding="utf-8", newline="")
    admin_test_path.write_text(admin_test.replace(old_assertion, new_assertion, 1), encoding="utf-8", newline="")
    return current_version, new_version


def release_preview() -> ReleasePreview:
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)', app_text, re.MULTILINE)
    if not match:
        raise RuntimeError("app.py 中未找到 APP_VERSION。")
    current_version = match.group(1)
    changes = tuple(line for line in _git("status", "--short").splitlines() if line.strip())
    return ReleasePreview(
        branch=_git("branch", "--show-current"),
        revision=_git("rev-parse", "--short", "HEAD"),
        current_version=current_version,
        next_version=next_patch_version(current_version),
        changed_files=changes,
    )


def launch_release_worker(*, control_center_pid: int, commit_message: str) -> None:
    RELEASE_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "run_control_center_release.ps1"),
        "-RepoPath",
        str(ROOT),
        "-ControlCenterPid",
        str(control_center_pid),
        "-CommitMessage",
        commit_message,
        "-LogDirectory",
        str(RELEASE_LOG_DIRECTORY),
    ]
    subprocess.Popen(
        command,
        cwd=ROOT,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
        close_fds=True,
    )


def latest_release_status() -> dict[str, str]:
    if not RELEASE_STATUS_PATH.exists():
        return {}
    try:
        data = json.loads(RELEASE_STATUS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def latest_release_log() -> Path | None:
    path = RELEASE_LOG_DIRECTORY / "latest.log"
    return path if path.exists() else None
