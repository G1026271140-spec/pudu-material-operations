from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tomllib
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .bundle import export_bundle, import_bundle
from .cloudflare import manual_instructions
from .models import CloudflareMode, DOMAIN_NOTICE, DeploymentConfig, DeploymentMode
from .plan import build_plan, execute_plan, is_admin


ROOT = Path(__file__).resolve().parents[1]
ACCENT = "#007C83"
ACCENT_DARK = "#005D63"
NAVY = "#0B3152"
SURFACE = "#F4F8FA"
TEXT = "#102A43"
MUTED = "#526D82"
ERROR = "#C9362B"


def config_from_current_install(root: Path = ROOT) -> DeploymentConfig:
    project = json.loads((root / "config" / "project_config.json").read_text(encoding="utf-8"))
    secret_path = root / ".streamlit" / "secrets.toml"
    secrets = tomllib.loads(secret_path.read_text(encoding="utf-8")) if secret_path.exists() else {}
    deployment = project.get("deployment", {})
    local = deployment.get("local_web", {})
    url = str(deployment.get("custom_domain", ""))
    known = {
        "INVENTORY_VIEW_PASSWORD",
        "APPROVAL_VIEW_PASSWORD",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_BITABLE_APP_TOKEN",
        "FEISHU_BITABLE_WEB_URL",
        "FEISHU_APPROVAL_WRITEBACK_APP_ID",
        "FEISHU_APPROVAL_WRITEBACK_APP_SECRET",
        "GITHUB_CACHE_REFRESH_TOKEN",
        "CLOUDFLARE_TUNNEL_TOKEN",
        "STREAMLIT_APP_URL",
    }
    return DeploymentConfig(
        install_root=str(root),
        repository=str(project.get("project", {}).get("github_repository", "")),
        branch=str(project.get("project", {}).get("github_branch", "master")),
        hostname=url.replace("https://", "").replace("http://", "").strip("/"),
        port=int(local.get("port", 8501)),
        cloudflare_mode=CloudflareMode.MANUAL,
        cloudflare_tunnel_token=str(secrets.get("CLOUDFLARE_TUNNEL_TOKEN", "")),
        feishu_app_id=str(secrets.get("FEISHU_APP_ID", "")),
        feishu_app_secret=str(secrets.get("FEISHU_APP_SECRET", "")),
        feishu_bitable_app_token=str(secrets.get("FEISHU_BITABLE_APP_TOKEN", "")),
        feishu_bitable_web_url=str(secrets.get("FEISHU_BITABLE_WEB_URL", "")),
        approval_writeback_app_id=str(secrets.get("FEISHU_APPROVAL_WRITEBACK_APP_ID", "")),
        approval_writeback_app_secret=str(secrets.get("FEISHU_APPROVAL_WRITEBACK_APP_SECRET", "")),
        github_token=str(secrets.get("GITHUB_CACHE_REFRESH_TOKEN", "")),
        inventory_password=str(secrets.get("INVENTORY_VIEW_PASSWORD", "")),
        approval_password=str(secrets.get("APPROVAL_VIEW_PASSWORD", "")),
        extra_secrets={key: value for key, value in secrets.items() if key not in known},
    )


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PUDU Material Operations 部署启动器")
        self.geometry("1060x760")
        self.minsize(960, 680)
        self.configure(bg=SURFACE)
        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._pages: list[ttk.Frame] = []
        self._page_index = 0
        self._build_style()
        self._build_vars()
        self._build_shell()
        self.after(150, self._drain_messages)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=SURFACE)
        style.configure("Surface.TFrame", background="#FFFFFF")
        style.configure("TLabel", background=SURFACE, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Surface.TLabel", background="#FFFFFF", foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=SURFACE, foreground=NAVY, font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Heading.TLabel", background="#FFFFFF", foreground=NAVY, font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Muted.TLabel", background="#FFFFFF", foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Notice.TLabel", background="#FFF1EF", foreground=ERROR, font=("Microsoft YaHei UI", 9), padding=12)
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(16, 9))
        style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF", bordercolor=ACCENT, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#9CB7BA")])
        style.configure("TEntry", padding=7, fieldbackground="#FFFFFF", foreground=TEXT)
        style.configure("TCombobox", padding=7, fieldbackground="#FFFFFF", foreground=TEXT)
        style.configure("TRadiobutton", background="#FFFFFF", foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("TCheckbutton", background="#FFFFFF", foreground=TEXT, font=("Microsoft YaHei UI", 9))
        style.configure("Step.TLabel", background=NAVY, foreground="#C8D8E5", font=("Microsoft YaHei UI", 10), padding=(22, 14))
        style.configure("StepActive.TLabel", background="#134C6B", foreground="#FFFFFF", font=("Microsoft YaHei UI", 10, "bold"), padding=(22, 14))

    def _build_vars(self) -> None:
        current = config_from_current_install()
        self.extra_secrets = dict(current.extra_secrets)
        self.vars: dict[str, tk.Variable] = {
            "mode": tk.StringVar(value=current.mode),
            "install_root": tk.StringVar(value=str(Path.home() / "PuduMaterialOperations")),
            "repository": tk.StringVar(value=current.repository),
            "branch": tk.StringVar(value=current.branch),
            "hostname": tk.StringVar(value=current.hostname),
            "port": tk.StringVar(value=str(current.port)),
            "cloudflare_mode": tk.StringVar(value=current.cloudflare_mode),
            "ownership": tk.BooleanVar(value=False),
            "cloudflare_api_token": tk.StringVar(),
            "cloudflare_account_id": tk.StringVar(),
            "cloudflare_zone_id": tk.StringVar(),
            "cloudflare_tunnel_name": tk.StringVar(value="pudu-material-operations"),
            "cloudflare_tunnel_token": tk.StringVar(value=current.cloudflare_tunnel_token),
            "feishu_app_id": tk.StringVar(value=current.feishu_app_id),
            "feishu_app_secret": tk.StringVar(value=current.feishu_app_secret),
            "feishu_bitable_app_token": tk.StringVar(value=current.feishu_bitable_app_token),
            "feishu_bitable_web_url": tk.StringVar(value=current.feishu_bitable_web_url),
            "approval_writeback_app_id": tk.StringVar(value=current.approval_writeback_app_id),
            "approval_writeback_app_secret": tk.StringVar(value=current.approval_writeback_app_secret),
            "github_token": tk.StringVar(value=current.github_token),
            "inventory_password": tk.StringVar(value=current.inventory_password),
            "approval_password": tk.StringVar(value=current.approval_password),
        }

    def _build_shell(self) -> None:
        header = tk.Frame(self, bg="#FFFFFF", height=82, highlightbackground="#D6E2EA", highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="PUDU", bg="#FFFFFF", fg=ACCENT, font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=(28, 14))
        tk.Label(header, text="Material Operations 部署启动器", bg="#FFFFFF", fg=NAVY, font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        state = "管理员权限已就绪" if is_admin() else "运行部署时将申请管理员权限"
        tk.Label(header, text=state, bg="#FFFFFF", fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="right", padx=28)

        body = tk.Frame(self, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.nav = tk.Frame(body, bg=NAVY, width=230)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True, padx=28, pady=24)
        self.step_labels: list[ttk.Label] = []
        for name in ("部署方式", "业务配置", "公网域名", "执行确认", "安装结果"):
            label = ttk.Label(self.nav, text=name, style="Step.TLabel")
            label.pack(fill="x")
            self.step_labels.append(label)

        self._pages = [self._page_mode(), self._page_business(), self._page_domain(), self._page_review(), self._page_progress()]
        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=(258, 28), pady=(0, 20))
        self.back_button = ttk.Button(footer, text="上一步", command=self._back)
        self.back_button.pack(side="left")
        self.next_button = ttk.Button(footer, text="下一步", style="Accent.TButton", command=self._next)
        self.next_button.pack(side="right")
        self._show_page(0)

    def _base_page(self, title: str, subtitle: str) -> ttk.Frame:
        page = ttk.Frame(self.content, style="Surface.TFrame", padding=26)
        ttk.Label(page, text=title, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(page, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(6, 20))
        return page

    def _page_mode(self) -> ttk.Frame:
        page = self._base_page("选择部署方式", "启动器会自动安装 Git、Python 和 cloudflared，并继续完成系统部署。")
        for value, title, description in (
            (DeploymentMode.TAKEOVER, "迁移接管", "安装并启动 Web、Tunnel、后台 Worker 和缓存任务。旧电脑不会被自动停止。"),
            (DeploymentMode.STANDBY, "备用节点", "准备代码、Python 环境与配置，不启动会与主节点争抢的后台任务。"),
        ):
            box = ttk.Frame(page, style="Surface.TFrame", padding=(0, 7))
            box.pack(fill="x")
            ttk.Radiobutton(box, text=title, value=value, variable=self.vars["mode"]).pack(anchor="w")
            ttk.Label(box, text=description, style="Muted.TLabel", wraplength=680).pack(anchor="w", padx=24, pady=(3, 0))
        ttk.Separator(page).pack(fill="x", pady=18)
        ttk.Label(page, text="安装目录", style="Surface.TLabel").pack(anchor="w")
        row = ttk.Frame(page, style="Surface.TFrame")
        row.pack(fill="x", pady=(6, 12))
        ttk.Entry(row, textvariable=self.vars["install_root"]).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择", command=self._choose_root).pack(side="left", padx=(8, 0))
        actions = ttk.Frame(page, style="Surface.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="导入旧电脑迁移包", command=self._import_bundle).pack(side="left")
        ttk.Button(actions, text="导出本机迁移包", command=self._export_bundle).pack(side="left", padx=8)
        return page

    def _field(self, parent: ttk.Frame, label: str, key: str, *, secret: bool = False, helper: str = "") -> None:
        ttk.Label(parent, text=label, style="Surface.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Entry(parent, textvariable=self.vars[key], show="•" if secret else "").pack(fill="x")
        if helper:
            ttk.Label(parent, text=helper, style="Muted.TLabel", wraplength=680).pack(anchor="w", pady=(3, 0))

    def _page_business(self) -> ttk.Frame:
        page = self._base_page("填写业务配置", "这些信息只写入目标电脑的本机密钥文件，不会写入 Git 或打包进启动器。")
        columns = ttk.Frame(page, style="Surface.TFrame")
        columns.pack(fill="both", expand=True)
        left = ttk.Frame(columns, style="Surface.TFrame")
        right = ttk.Frame(columns, style="Surface.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self._field(left, "飞书 App ID", "feishu_app_id")
        self._field(left, "飞书 App Secret", "feishu_app_secret", secret=True)
        self._field(left, "飞书多维表格 App Token", "feishu_bitable_app_token", secret=True)
        self._field(left, "飞书多维表格链接", "feishu_bitable_web_url")
        self._field(right, "审批回写 App ID", "approval_writeback_app_id")
        self._field(right, "审批回写 App Secret", "approval_writeback_app_secret", secret=True)
        self._field(right, "GitHub Token", "github_token", secret=True, helper="用于缓存任务推送。权限应限制到当前仓库。")
        self._field(right, "库存管理密码", "inventory_password", secret=True)
        self._field(right, "审批管理密码", "approval_password", secret=True)
        return page

    def _page_domain(self) -> ttk.Frame:
        page = self._base_page("配置公网域名", "支持自动创建 Tunnel 与 DNS，也支持手动配置后由启动器负责验证。")
        ttk.Label(page, text=DOMAIN_NOTICE, style="Notice.TLabel", wraplength=720).pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(page, text="我确认该域名归当前部署者所有，并已接入对应的 Cloudflare 账号", variable=self.vars["ownership"]).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(page, style="Surface.TFrame")
        row.pack(fill="x")
        for label, value in (("自动配置", CloudflareMode.AUTOMATIC), ("手动配置", CloudflareMode.MANUAL)):
            ttk.Radiobutton(row, text=label, value=value, variable=self.vars["cloudflare_mode"], command=self._refresh_domain_mode).pack(side="left", padx=(0, 18))
        self._field(page, "公网域名", "hostname", helper="例如 pudu-material-operations.example.com")
        self._field(page, "本地端口", "port")
        self.domain_dynamic = ttk.Frame(page, style="Surface.TFrame")
        self.domain_dynamic.pack(fill="both", expand=True)
        self._refresh_domain_mode()
        return page

    def _refresh_domain_mode(self) -> None:
        if not hasattr(self, "domain_dynamic"):
            return
        for child in self.domain_dynamic.winfo_children():
            child.destroy()
        automatic = self.vars["cloudflare_mode"].get() == CloudflareMode.AUTOMATIC
        if automatic:
            self._field(self.domain_dynamic, "Cloudflare API Token", "cloudflare_api_token", secret=True, helper="仅授予 Tunnel 与 DNS 编辑权限。")
            self._field(self.domain_dynamic, "Cloudflare Account ID", "cloudflare_account_id")
            self._field(self.domain_dynamic, "Cloudflare Zone ID", "cloudflare_zone_id")
            self._field(self.domain_dynamic, "Tunnel 名称", "cloudflare_tunnel_name")
        else:
            self._field(self.domain_dynamic, "Tunnel 运行 Token", "cloudflare_tunnel_token", secret=True)
            config = self._collect(validate=False)
            text = "\n".join(manual_instructions(config))
            ttk.Label(self.domain_dynamic, text=text, style="Muted.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(10, 0))

    def _page_review(self) -> ttk.Frame:
        page = self._base_page("确认部署计划", "执行前会再次校验必填项。已有运行节点和旧电脑不会被自动停止。")
        self.review_text = tk.Text(page, height=20, bg="#F8FBFC", fg=TEXT, bd=1, relief="solid", font=("Microsoft YaHei UI", 10), wrap="word", padx=14, pady=12)
        self.review_text.pack(fill="both", expand=True)
        self.review_text.configure(state="disabled")
        return page

    def _page_progress(self) -> ttk.Frame:
        page = self._base_page("部署进度", "关闭窗口不会自动回滚已成功安装的基础软件。业务任务只有在全部配置校验通过后才会注册。")
        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))
        self.log = tk.Text(page, bg="#0C2435", fg="#E7F3F6", insertbackground="#FFFFFF", bd=0, font=("Consolas", 9), wrap="word", padx=14, pady=12)
        self.log.pack(fill="both", expand=True)
        return page

    def _choose_root(self) -> None:
        chosen = filedialog.askdirectory(title="选择安装目录")
        if chosen:
            self.vars["install_root"].set(chosen)

    def _collect(self, *, validate: bool = True) -> DeploymentConfig:
        try:
            port = int(str(self.vars["port"].get()) or "0")
        except ValueError:
            if validate:
                raise ValueError("本地端口必须是数字。") from None
            port = 8501
        config = DeploymentConfig(
            mode=DeploymentMode(self.vars["mode"].get()),
            install_root=str(self.vars["install_root"].get()),
            repository=str(self.vars["repository"].get()),
            branch=str(self.vars["branch"].get()),
            hostname=str(self.vars["hostname"].get()),
            port=port,
            cloudflare_mode=CloudflareMode(self.vars["cloudflare_mode"].get()),
            domain_ownership_confirmed=bool(self.vars["ownership"].get()),
            cloudflare_api_token=str(self.vars["cloudflare_api_token"].get()),
            cloudflare_account_id=str(self.vars["cloudflare_account_id"].get()),
            cloudflare_zone_id=str(self.vars["cloudflare_zone_id"].get()),
            cloudflare_tunnel_name=str(self.vars["cloudflare_tunnel_name"].get()),
            cloudflare_tunnel_token=str(self.vars["cloudflare_tunnel_token"].get()),
            feishu_app_id=str(self.vars["feishu_app_id"].get()),
            feishu_app_secret=str(self.vars["feishu_app_secret"].get()),
            feishu_bitable_app_token=str(self.vars["feishu_bitable_app_token"].get()),
            feishu_bitable_web_url=str(self.vars["feishu_bitable_web_url"].get()),
            approval_writeback_app_id=str(self.vars["approval_writeback_app_id"].get()),
            approval_writeback_app_secret=str(self.vars["approval_writeback_app_secret"].get()),
            github_token=str(self.vars["github_token"].get()),
            inventory_password=str(self.vars["inventory_password"].get()),
            approval_password=str(self.vars["approval_password"].get()),
            extra_secrets=dict(self.extra_secrets),
        )
        if validate:
            config.validate()
        return config

    def _load_config(self, config: DeploymentConfig) -> None:
        self.extra_secrets = dict(config.extra_secrets)
        mapping = {
            "mode": config.mode,
            "install_root": config.install_root,
            "repository": config.repository,
            "branch": config.branch,
            "hostname": config.hostname,
            "port": str(config.port),
            "cloudflare_mode": config.cloudflare_mode,
            "ownership": config.domain_ownership_confirmed,
        }
        for key in self.vars:
            if key in mapping:
                self.vars[key].set(mapping[key])
            elif hasattr(config, key):
                self.vars[key].set(getattr(config, key))
        self._refresh_domain_mode()

    def _export_bundle(self) -> None:
        destination = filedialog.asksaveasfilename(title="导出加密迁移包", defaultextension=".pudu-migration", filetypes=[("PUDU 迁移包", "*.pudu-migration")])
        if not destination:
            return
        password = self._ask_password("设置迁移包密码")
        if not password:
            return
        try:
            export_bundle(Path(destination), config_from_current_install(), password)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
        else:
            messagebox.showinfo("导出完成", "迁移包已加密保存。请通过独立渠道传递迁移包和密码。", parent=self)

    def _import_bundle(self) -> None:
        source = filedialog.askopenfilename(title="选择迁移包", filetypes=[("PUDU 迁移包", "*.pudu-migration"), ("所有文件", "*.*")])
        if not source:
            return
        password = self._ask_password("输入迁移包密码")
        if not password:
            return
        try:
            config = import_bundle(Path(source), password)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
        else:
            config.install_root = str(Path.home() / "PuduMaterialOperations")
            config.domain_ownership_confirmed = False
            self._load_config(config)
            messagebox.showinfo("导入完成", "配置已载入。请重新确认域名所有权并检查部署方式。", parent=self)

    def _ask_password(self, title: str) -> str:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("420x180")
        dialog.configure(bg="#FFFFFF")
        value = tk.StringVar()
        tk.Label(dialog, text="密码至少 10 个字符", bg="#FFFFFF", fg=TEXT, font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=24, pady=(22, 8))
        entry = ttk.Entry(dialog, textvariable=value, show="•")
        entry.pack(fill="x", padx=24)
        entry.focus_set()
        result: list[str] = []
        def submit() -> None:
            result.append(value.get())
            dialog.destroy()
        ttk.Button(dialog, text="确认", style="Accent.TButton", command=submit).pack(side="right", padx=24, pady=20)
        dialog.bind("<Return>", lambda _event: submit())
        self.wait_window(dialog)
        return result[0] if result else ""

    def _show_page(self, index: int) -> None:
        for page in self._pages:
            page.pack_forget()
        self._page_index = index
        self._pages[index].pack(fill="both", expand=True)
        for i, label in enumerate(self.step_labels):
            label.configure(style="StepActive.TLabel" if i == index else "Step.TLabel")
        self.back_button.configure(state="disabled" if index in (0, 4) else "normal")
        self.next_button.configure(text="开始部署" if index == 3 else "下一步", state="disabled" if index == 4 else "normal")

    def _back(self) -> None:
        if self._page_index > 0:
            self._show_page(self._page_index - 1)

    def _next(self) -> None:
        try:
            if self._page_index == 2:
                self._collect(validate=True)
            if self._page_index == 3:
                self._start_install()
                return
            if self._page_index == 2:
                self._render_review()
            self._show_page(self._page_index + 1)
        except Exception as exc:
            messagebox.showerror("请检查配置", str(exc), parent=self)

    def _render_review(self) -> None:
        config = self._collect(validate=True)
        lines = [
            f"部署方式：{'迁移接管' if config.mode == DeploymentMode.TAKEOVER else '备用节点'}",
            f"安装目录：{config.install_root}",
            f"公网地址：{config.public_url}",
            f"Cloudflare：{'自动配置' if config.cloudflare_mode == CloudflareMode.AUTOMATIC else '手动配置并验证'}",
            "",
            "执行步骤：",
        ]
        lines.extend(f"  {index}. {step.label}" for index, step in enumerate(build_plan(config), start=1))
        lines.extend(["", "安全边界：", "  - 旧电脑不会被自动停止或修改。", "  - API Token 和 App Secret 只写入目标电脑本机。", "  - 备用节点不会注册会争抢队列的后台任务。"])
        self.review_text.configure(state="normal")
        self.review_text.delete("1.0", "end")
        self.review_text.insert("1.0", "\n".join(lines))
        self.review_text.configure(state="disabled")

    def _start_install(self) -> None:
        config = self._collect(validate=True)
        self._show_page(4)
        self.progress.start(10)
        self.log.delete("1.0", "end")
        def worker() -> None:
            try:
                report = execute_plan(config, lambda text: self._messages.put(("log", text)))
            except Exception as exc:
                self._messages.put(("error", exc))
            else:
                self._messages.put(("done", report))
        threading.Thread(target=worker, daemon=True).start()

    def _drain_messages(self) -> None:
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.insert("end", str(payload) + "\n")
                self.log.see("end")
            elif kind == "error":
                self.progress.stop()
                self.log.insert("end", f"\n部署失败：{payload}\n")
                messagebox.showerror("部署失败", str(payload), parent=self)
            elif kind == "done":
                self.progress.stop()
                self.log.insert("end", f"\n部署完成。报告：{payload}\n")
                messagebox.showinfo("部署完成", f"部署已完成。\n报告：{payload}", parent=self)
        self.after(150, self._drain_messages)


def _relaunch_as_admin() -> bool:
    if os.name != "nt" or is_admin():
        return False
    if getattr(sys, "frozen", False):
        executable = sys.executable
        arguments = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    else:
        executable = sys.executable
        arguments = f'-m deployment_launcher {' '.join(f'"{arg}"' for arg in sys.argv[1:])}'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, arguments, str(ROOT), 1)
    return result > 32


def main() -> int:
    if "--no-elevate" not in sys.argv and _relaunch_as_admin():
        return 0
    LauncherApp().mainloop()
    return 0
