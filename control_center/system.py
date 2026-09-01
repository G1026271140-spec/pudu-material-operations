from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_config import expand_setting_path, get_setting

from .configuration import ROOT


@dataclass(frozen=True)
class TaskSpec:
    key: str
    label: str
    task_name_path: str
    log_path: str
    installer: str
    description: str

    @property
    def task_name(self) -> str:
        return str(get_setting(self.task_name_path, ""))

    @property
    def resolved_log_path(self) -> Path:
        return expand_setting_path(self.log_path)


TASKS = (
    TaskSpec("web", "本地 Web 应用", "deployment.local_web.web_task_name", "%USERPROFILE%\\PuduMaterialWebRunner\\logs\\web.log", "scripts/install_local_web_app_task.ps1", "本地 Streamlit 服务"),
    TaskSpec("tunnel", "Cloudflare Tunnel", "deployment.local_web.tunnel_task_name", "%USERPROFILE%\\PuduMaterialWebRunner\\logs\\tunnel.log", "scripts/install_local_web_app_task.ps1", "material.gaohongyuan.me 的 Named Tunnel"),
    TaskSpec("submission", "提交 Worker", "submission_worker.task_name", "%LOCALAPPDATA%\\PuduSubmissionWorker\\logs\\worker.log", "scripts/install_submission_worker_task.ps1", "处理飞书后台任务队列"),
    TaskSpec("card", "飞书卡片 Worker", "card_worker.task_name", "%LOCALAPPDATA%\\PuduFeishuCardWorker\\logs\\worker.log", "scripts/install_feishu_card_worker_task.ps1", "接收飞书消息卡片事件"),
    TaskSpec("cache", "物料缓存", "cache_runner.task_name", "%LOCALAPPDATA%\\PuduMaterialCacheRunner\\logs\\latest.log", "scripts/install_local_cache_task.ps1", "生成并发布页面静态缓存"),
    TaskSpec("contacts", "联系人缓存", "cache_runner.contact_task_name", "%LOCALAPPDATA%\\PuduMaterialCacheRunner\\logs\\latest.log", "scripts/install_local_cache_task.ps1", "更新联系人和部门缓存"),
    TaskSpec("wake", "Streamlit 唤醒", "streamlit_wake.task_name", "work\\streamlit-wake.log", "scripts/install_streamlit_wake_shortcut.ps1", "夜间检查 Streamlit Cloud 是否休眠"),
)
TASK_BY_KEY = {task.key: task for task in TASKS}


def _ps_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("任务名称不能包含换行。")
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def task_status(task: TaskSpec) -> dict[str, Any]:
    name = _ps_quote(task.task_name)
    script = (
        f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
        "if($null -eq $t){'{\"installed\":false}' }else{"
        f"$i=Get-ScheduledTaskInfo -TaskName {name};"
        "[pscustomobject]@{installed=$true;state=[string]$t.State;last_run=[string]$i.LastRunTime;"
        "last_result=[int64]$i.LastTaskResult;next_run=[string]$i.NextRunTime}|ConvertTo-Json -Compress}"
    )
    result = _powershell(script)
    if result.returncode != 0:
        return {"installed": False, "error": (result.stderr or result.stdout).strip()}
    try:
        return json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"installed": False, "error": "无法解析任务状态。"}


def all_task_statuses() -> dict[str, dict[str, Any]]:
    return {task.key: task_status(task) for task in TASKS}


def control_task(task: TaskSpec, action: str) -> None:
    command_map = {
        "start": "Start-ScheduledTask",
        "stop": "Stop-ScheduledTask",
        "run": "Start-ScheduledTask",
    }
    if action == "restart":
        name = _ps_quote(task.task_name)
        script = f"Stop-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName {name}"
    elif action in command_map:
        script = f"{command_map[action]} -TaskName {_ps_quote(task.task_name)} -ErrorAction Stop"
    else:
        raise ValueError(f"不支持的任务操作：{action}")
    result = _powershell(script)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "任务操作失败。")


def synchronize_task_group(task: TaskSpec) -> str:
    """Reinstall the selected runtime group using the versioned configuration."""
    repository = str(get_setting("project.github_repository", ""))
    repository_url = f"https://github.com/{repository}.git"
    branch = str(get_setting("project.github_branch", "master"))
    powershell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
    if task.key in {"web", "tunnel"}:
        script = ROOT / "scripts" / "install_local_web_app_task.ps1"
        args = [
            "-SourceRepoPath", str(ROOT),
            "-RunnerRoot", str(expand_setting_path(str(get_setting("deployment.local_web.runner_root", "%USERPROFILE%\\PuduMaterialWebRunner")))),
            "-RepositoryUrl", repository_url,
            "-Branch", branch,
            "-WebTaskName", str(get_setting("deployment.local_web.web_task_name", "PUDU Material Web App")),
            "-TunnelTaskName", str(get_setting("deployment.local_web.tunnel_task_name", "PUDU Material Cloudflare Tunnel")),
            "-Port", str(get_setting("deployment.local_web.port", 8501)),
        ]
    elif task.key == "submission":
        script = ROOT / "scripts" / "install_submission_worker_task.ps1"
        args = [
            "-SourceRepoPath", str(ROOT),
            "-RunnerRoot", str(expand_setting_path(str(get_setting("submission_worker.runner_root", "%LOCALAPPDATA%\\PuduSubmissionWorker")))),
            "-RepositoryUrl", repository_url,
            "-Branch", branch,
            "-TaskName", str(get_setting("submission_worker.task_name", "PUDU Submission Worker")),
            "-WorkerPriority", str(get_setting("submission_worker.priority", 100)),
        ]
    elif task.key in {"cache", "contacts"}:
        times = list(get_setting("cache_runner.daily_times", ["10:30", "16:30"]))
        if len(times) != 2:
            raise ValueError("物料缓存执行时间必须正好配置两个时间。")
        script = ROOT / "scripts" / "install_local_cache_task.ps1"
        args = [
            "-SourceRepoPath", str(ROOT),
            "-RunnerRoot", str(expand_setting_path(str(get_setting("cache_runner.runner_root", "%LOCALAPPDATA%\\PuduMaterialCacheRunner")))),
            "-RepositoryUrl", repository_url,
            "-Branch", branch,
            "-TaskName", str(get_setting("cache_runner.task_name", "PUDU Material Cache Refresh")),
            "-ContactTaskName", str(get_setting("cache_runner.contact_task_name", "PUDU Contact Cache Refresh")),
            "-MorningTime", str(times[0]),
            "-AfternoonTime", str(times[1]),
            "-ContactTime", str(get_setting("cache_runner.contact_time", "11:00")),
            "-ContactDays", ",".join(str(day) for day in get_setting("cache_runner.contact_days", ["Monday", "Wednesday", "Friday"])),
            "-SkipInitialRun",
        ]
    elif task.key == "card":
        script = ROOT / "scripts" / "install_feishu_card_worker_task.ps1"
        args = ["-TaskName", str(get_setting("card_worker.task_name", "PUDU Feishu Card Worker"))]
    else:
        raise ValueError("该任务没有可自动同步的安装器，请按配置项中的入口说明处理。")

    result = subprocess.run(
        [*powershell, str(script), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=900,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise RuntimeError(output or f"安装器退出码：{result.returncode}")
    return output or "任务配置已同步。"


def tail_log(task: TaskSpec, line_count: int = 120) -> str:
    path = task.resolved_log_path
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return f"日志尚不存在：{path}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-line_count:])


def current_app_version() -> str:
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)', (ROOT / "app.py").read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else "未知"


def git_snapshot() -> dict[str, str]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    return {
        "branch": run("branch", "--show-current"),
        "revision": run("rev-parse", "--short", "HEAD"),
        "remote": run("remote", "get-url", "origin"),
        "dirty": "是" if run("status", "--porcelain") else "否",
    }


def port_is_listening(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def system_snapshot() -> dict[str, Any]:
    address = str(get_setting("deployment.local_web.address", "127.0.0.1"))
    port = int(get_setting("deployment.local_web.port", 8501))
    return {
        "version": current_app_version(),
        "git": git_snapshot(),
        "local_web": {"address": address, "port": port, "listening": port_is_listening(address, port)},
        "tasks": all_task_statuses(),
    }
