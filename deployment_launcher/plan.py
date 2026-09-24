from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .cloudflare import configure_cloudflare
from .configuration import write_deployment_configuration
from .models import CloudflareMode, DeploymentConfig, DeploymentMode
from .prerequisites import ensure_prerequisites, environment_with_prerequisites


Progress = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class PlanStep:
    key: str
    label: str
    destructive: bool = False


def build_plan(config: DeploymentConfig) -> list[PlanStep]:
    steps = [
        PlanStep("preflight", "检查管理员权限、安装包与端口"),
        PlanStep("prerequisites", "自动安装并验证 Git、Python 和 cloudflared"),
        PlanStep("files", "部署项目文件并创建 Python 环境"),
        PlanStep("configuration", "写入本机配置与受保护密钥"),
        PlanStep("verify", "执行导入检查和本地健康检查"),
    ]
    if config.mode == DeploymentMode.TAKEOVER:
        steps[4:4] = [
            PlanStep("cloudflare", "配置并验证 Cloudflare Tunnel 与 DNS"),
            PlanStep("tasks", "安装 Web、后台队列、卡片和缓存计划任务"),
        ]
    else:
        steps.insert(4, PlanStep("standby", "保持备用状态，不注册会争抢任务的后台节点"))
    return steps


def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 1800) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise RuntimeError(output or f"命令执行失败，退出码 {result.returncode}")
    return output


def _package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def _copy_source(source: Path, target: Path) -> None:
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache", "work", "logs", "outputs", "tmp", "node_modules", "dist", "build"}
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in ignored or item.name.endswith((".pyc", ".exe")):
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"))
        else:
            shutil.copy2(item, destination)


def _deploy_files(
    config: DeploymentConfig,
    package_root: Path,
    progress: Progress,
    prerequisite_paths: dict[str, Path],
) -> tuple[Path, dict[str, str]]:
    install_root = Path(config.install_root).expanduser().resolve()
    install_root.mkdir(parents=True, exist_ok=True)
    payload = package_root / "payload" / "project.zip"
    if payload.exists():
        progress("正在解压项目快照...")
        with zipfile.ZipFile(payload) as archive:
            archive.extractall(install_root)
    else:
        progress("未找到外置项目快照，正在从当前源码部署...")
        _copy_source(Path(__file__).resolve().parents[1], install_root)

    python = prerequisite_paths["python"]
    venv_python = install_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        progress("正在创建项目 Python 环境...")
        _run([str(python), "-m", "venv", str(install_root / ".venv")], cwd=install_root, env=os.environ.copy())
    progress("正在安装项目 Python 依赖...")
    _run([str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(install_root / "requirements.txt")], cwd=install_root, env=os.environ.copy())
    env = environment_with_prerequisites(prerequisite_paths)
    return install_root, env


def _install_tasks(root: Path, config: DeploymentConfig, env: dict[str, str], progress: Progress) -> None:
    repo_url = f"https://github.com/{config.repository}.git"
    common = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
    commands = [
        ("本地 Web 与 Tunnel", root / "scripts" / "install_local_web_app_task.ps1", ["-SourceRepoPath", str(root), "-RepositoryUrl", repo_url, "-Branch", config.branch, "-Port", str(config.port), "-TunnelToken", config.cloudflare_tunnel_token]),
        ("提交 Worker", root / "scripts" / "install_submission_worker_task.ps1", ["-SourceRepoPath", str(root), "-RepositoryUrl", repo_url, "-Branch", config.branch]),
        ("飞书卡片 Worker", root / "scripts" / "install_feishu_card_worker_task.ps1", []),
        ("缓存任务", root / "scripts" / "install_local_cache_task.ps1", ["-SourceRepoPath", str(root), "-RepositoryUrl", repo_url, "-Branch", config.branch, "-SkipInitialRun"]),
    ]
    for label, script, args in commands:
        progress(f"正在安装：{label}")
        _run([*common, str(script), *args], cwd=root, env=env)


def _verify(root: Path, config: DeploymentConfig, env: dict[str, str], progress: Progress) -> None:
    python = root / ".venv" / "Scripts" / "python.exe"
    progress("正在检查应用模块...")
    _run([str(python), "-c", "import app; import request_web.api; import submission_queue"], cwd=root, env=env, timeout=300)
    if config.mode == DeploymentMode.TAKEOVER:
        for label, url in (("本地", f"http://127.0.0.1:{config.port}/api/health"), ("公网", config.public_url + "/api/health")):
            progress(f"正在验证{label}健康接口：{url}")
            last_error = ""
            for _attempt in range(30):
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        if response.status == 200:
                            break
                        last_error = f"HTTP {response.status}"
                except Exception as exc:
                    last_error = str(exc)
                time.sleep(2)
            else:
                raise RuntimeError(f"{label}健康检查失败：{last_error}")


def execute_plan(config: DeploymentConfig, progress: Progress = print, *, package_root: Path | None = None) -> Path:
    config.validate()
    if os.name == "nt" and not is_admin():
        raise PermissionError("部署需要管理员权限。请右键以管理员身份运行启动器。")
    package_root = package_root or _package_root()
    progress("预检通过。旧电脑不会被自动停止或修改。")
    prerequisite_paths = ensure_prerequisites(progress)
    root, env = _deploy_files(config, package_root, progress, prerequisite_paths)
    progress("正在写入配置...")
    write_deployment_configuration(root, config)
    if config.mode == DeploymentMode.TAKEOVER:
        if config.cloudflare_mode == CloudflareMode.AUTOMATIC:
            progress("正在配置 Cloudflare Tunnel 与 DNS...")
            result = configure_cloudflare(config)
            config.cloudflare_tunnel_token = result.tunnel_token
            write_deployment_configuration(root, config)
        _install_tasks(root, config, env, progress)
    else:
        progress("备用节点已就绪。未注册 Tunnel、Worker 或缓存计划任务。")
    _verify(root, config, env, progress)
    report = {
        "status": "success",
        "mode": config.mode,
        "install_root": str(root),
        "public_url": config.public_url,
        "old_node_changed": False,
    }
    report_path = root / "deployment-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path
