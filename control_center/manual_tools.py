from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .configuration import ROOT, SECRETS_PATH


@dataclass(frozen=True)
class ManualTool:
    key: str
    label: str
    description: str
    result: str
    requires_secrets: bool = True
    interrupts_services: bool = False


MANUAL_TOOLS = (
    ManualTool(
        "MaterialCache",
        "刷新页面与申请缓存",
        "从飞书重新生成页面主缓存、申请/补库表单缓存和礼品图片缓存，并执行完整缓存校验。",
        "只更新本地缓存文件，不提交 GitHub、不重启应用。",
    ),
    ManualTool(
        "ContactCache",
        "刷新联系人缓存",
        "重新读取飞书联系人与部门数据，生成联系人部门静态缓存。",
        "只更新本地联系人缓存，不提交 GitHub。",
    ),
    ManualTool(
        "WarehouseCache",
        "刷新仓库与分类图片缓存",
        "重新生成仓库位置、货架图片和申请分类图片缓存，并验证图片完整性。",
        "只更新本地仓库和图片缓存，不提交 GitHub。",
    ),
    ManualTool(
        "AllCaches",
        "刷新全部页面缓存",
        "按页面缓存、联系人缓存、仓库/分类图片缓存的顺序全部执行。",
        "可能需要数分钟；只保留本地修改，不提交或重启。",
    ),
    ManualTool(
        "ValidateCaches",
        "校验现有缓存",
        "检查应用模块版本、页面缓存、申请表单缓存和仓库位置缓存。",
        "只读校验，不修改业务数据。",
        requires_secrets=False,
    ),
    ManualTool(
        "FeishuSmokeTest",
        "飞书全链路只读检查",
        "运行项目的飞书连通性和关键数据结构检查，帮助发布前发现配置或字段问题。",
        "会调用飞书接口，但不会提交 GitHub或重启服务。",
    ),
    ManualTool(
        "WakeStreamlit",
        "检查并唤醒 Streamlit Cloud",
        "检查 Streamlit Cloud 页面；仅在页面休眠时执行唤醒。",
        "不会重启本地 Web、Tunnel 或 Worker。",
        requires_secrets=False,
    ),
    ManualTool(
        "SyncAllRuntimes",
        "同步并重启全部运行组件",
        "按当前 master 配置同步本地 Web/Tunnel、提交 Worker、飞书卡片 Worker 和缓存 Runner。",
        "会短暂中断对应服务，仅用于发布后恢复或人工维护。",
        interrupts_services=True,
    ),
    ManualTool(
        "RefreshCommitRestartApp",
        "刷新缓存并提交重启应用",
        "关闭当前控制程序，刷新全部页面与业务缓存，执行完整测试后提交推送代码，再同步并重启 Web、Tunnel、Worker 和缓存任务。",
        "会短暂停止应用并自动递增版本；仅在确认当前改动应正式发布时执行。",
        interrupts_services=True,
    ),
)
MANUAL_TOOL_BY_KEY = {tool.key: tool for tool in MANUAL_TOOLS}


def run_manual_tool(tool: ManualTool, on_line: Callable[[str], None] | None = None) -> tuple[int, str]:
    if tool.requires_secrets and not SECRETS_PATH.exists():
        raise RuntimeError("请先在设置中配置 .streamlit/secrets.toml。")
    log_directory = ROOT / "work" / "control_center" / "manual-tools"
    script_path = ROOT / "scripts" / ("run_control_center_release.ps1" if tool.key == "RefreshCommitRestartApp" else "run_control_center_manual_tool.ps1")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Tool",
        tool.key,
        "-RepoPath",
        str(ROOT),
        "-LogDirectory",
        str(log_directory),
    ]
    if tool.key != "RefreshCommitRestartApp":
        command.extend(["-SecretsPath", str(SECRETS_PATH)])
    if tool.key == "RefreshCommitRestartApp":
        command.extend(["-ControlCenterPid", str(os.getpid())])
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        lines.append(line)
        if on_line:
            on_line(line)
    return process.wait(), "\n".join(lines)


def latest_manual_tool_log() -> Path | None:
    log_directory = ROOT / "work" / "control_center" / "manual-tools"
    logs = sorted(log_directory.glob("manual-*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    return logs[0] if logs else None
