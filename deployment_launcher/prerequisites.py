from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Prerequisite:
    key: str
    label: str
    winget_id: str
    commands: tuple[str, ...]


PREREQUISITES = (
    Prerequisite("git", "Git", "Git.Git", ("git.exe", "git")),
    Prerequisite("python", "Python 3.12", "Python.Python.3.12", ("python.exe", "python", "py.exe", "py")),
    Prerequisite("cloudflared", "cloudflared", "Cloudflare.cloudflared", ("cloudflared.exe", "cloudflared")),
)


def _candidate_paths(item: Prerequisite) -> list[Path]:
    candidates: dict[str, list[Path]] = {
        "git": [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe"],
        "python": [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Python312" / "python.exe",
        ],
        "cloudflared": [
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "cloudflared" / "cloudflared.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "cloudflared" / "cloudflared.exe",
        ],
    }
    return candidates[item.key]


def find_prerequisite(item: Prerequisite) -> Path | None:
    for command in item.commands:
        found = shutil.which(command)
        if found:
            return Path(found)
    return next((path for path in _candidate_paths(item) if path.exists()), None)


def _run(command: list[str], timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def ensure_prerequisites(progress: Progress = print) -> dict[str, Path]:
    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        raise RuntimeError("未找到 Windows 程序包管理器 winget。请先通过 Microsoft Store 更新“应用安装程序”，然后重新运行启动器。")
    resolved: dict[str, Path] = {}
    for item in PREREQUISITES:
        path = find_prerequisite(item)
        if path is None:
            progress(f"正在自动安装 {item.label}...")
            result = _run(
                [
                    winget,
                    "install",
                    "--id",
                    item.winget_id,
                    "--exact",
                    "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--disable-interactivity",
                ]
            )
            if result.returncode not in (0, -1978335189):
                output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
                raise RuntimeError(f"{item.label} 自动安装失败。\n{output[-2000:]}")
            path = find_prerequisite(item)
        if path is None:
            raise RuntimeError(f"{item.label} 安装完成后仍无法定位可执行文件，请查看 winget 日志。")
        progress(f"已就绪：{item.label} ({path})")
        resolved[item.key] = path
    return resolved


def environment_with_prerequisites(paths: dict[str, Path]) -> dict[str, str]:
    env = os.environ.copy()
    directories = [str(path.parent) for path in paths.values()]
    env["PATH"] = os.pathsep.join(directories + [env.get("PATH", "")])
    return env
