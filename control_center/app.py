from __future__ import annotations

import hmac
import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from project_config import get_setting

from .catalog import CATEGORIES, SETTINGS, SETTINGS_BY_KEY, configuration_location
from .configuration import ROOT, SECRETS_PATH, STREAMLIT_CONFIG_PATH, read_setting, read_toml_setting, write_setting
from .feishu_runtime import load_approval_instances, load_worker_nodes, update_worker_node
from .manual_tools import MANUAL_TOOLS, ManualTool, run_manual_tool
from .release import latest_release_log, latest_release_status, launch_release_worker, release_preview
from .system import TASKS, TASK_BY_KEY, control_task, current_app_version, synchronize_task_group, system_snapshot, tail_log


MASK = "••••••••••••"

BG = "#f7f7f7"
PANEL = "#ffffff"
BORDER = "#e5e5e5"
TEXT = "#202020"
MUTED = "#6b6b6b"
ACCENT = "#0078d4"
ACCENT_SOFT = "#e8f3fb"
SUCCESS = "#107c10"


def _display_value(spec, value: Any, unlocked: bool) -> str:
    if spec.sensitive and value not in (None, "") and not unlocked:
        return MASK
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value if value is not None else "")


class ScrollableFrame(tk.Frame):
    """A neutral scroll region that keeps the MAA-style content column calm."""

    def __init__(self, parent, *, background: str = BG) -> None:
        super().__init__(parent, bg=background)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=background)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<Enter>", lambda _event: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _event: self.canvas.unbind_all("<MouseWheel>"))

    def _sync_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class ControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Marketing materials Control · {current_app_version()}")
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.configure(background=BG)
        icon_path = ROOT / "assets" / "app-icon.png"
        if icon_path.exists():
            try:
                self.app_icon = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self.app_icon)
            except tk.TclError:
                self.app_icon = None
        self.unlocked = False
        self.current_spec = None
        self.current_category = CATEGORIES[0]
        self.current_page = "运行总览"
        self.operation_running = False
        self.status_var = tk.StringVar(value="就绪")
        self._configure_style()
        self._build_layout()
        requested_page = os.environ.get("PUDU_CONTROL_CENTER_PAGE", "运行总览")
        self._show_page(requested_page if requested_page in self.nav_items else "运行总览")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 9))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 14, "bold"), foreground=TEXT, background=PANEL)
        style.configure("Subheader.TLabel", font=("Microsoft YaHei UI", 9), foreground=MUTED, background=PANEL)
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 13, "bold"), foreground=TEXT, background=BG)
        style.configure("CardTitle.TLabel", font=("Microsoft YaHei UI", 10, "bold"), foreground=TEXT, background=PANEL)
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7), relief="flat", borderwidth=1)
        style.map("TButton", background=[("active", "#f0f0f0")])
        style.configure("Accent.TButton", foreground="#ffffff", background=ACCENT, bordercolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#006cbe"), ("pressed", "#005a9e")])
        style.configure("Treeview", rowheight=34, font=("Microsoft YaHei UI", 9), background=PANEL, fieldbackground=PANEL, bordercolor=BORDER, relief="flat")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9), foreground=MUTED, background="#fafafa", relief="flat", bordercolor=BORDER)
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
        style.configure("TEntry", padding=(8, 7), fieldbackground=PANEL, bordercolor="#cfcfcf", lightcolor="#cfcfcf", darkcolor="#cfcfcf")
        style.configure("TCombobox", padding=(8, 6))

    def _build_layout(self) -> None:
        header = tk.Frame(self, bg=PANEL, height=92, highlightbackground=BORDER, highlightthickness=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=PANEL)
        brand.pack(side="left", fill="y", padx=(22, 28))
        ttk.Label(brand, text="Marketing materials Control", style="Header.TLabel").pack(anchor="w", pady=(14, 0))
        ttk.Label(brand, text=f"配置与运行控制台  ·  {current_app_version()}", style="Subheader.TLabel").pack(anchor="w", pady=(2, 0))

        nav = tk.Frame(header, bg=PANEL)
        nav.pack(side="left", fill="both", expand=True)
        self.nav_items = ["运行总览", "后台任务", "手动工具", "飞书工具", "设置"]
        self.nav_buttons: dict[str, tk.Frame] = {}
        for item in self.nav_items:
            slot = tk.Frame(nav, bg=PANEL, width=128)
            slot.pack(side="left", fill="y")
            slot.pack_propagate(False)
            button = tk.Button(slot, text=item, command=lambda name=item: self._show_page(name), bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=ACCENT, relief="flat", borderwidth=0, font=("Microsoft YaHei UI", 10), cursor="hand2")
            button.pack(fill="both", expand=True, pady=(12, 4))
            underline = tk.Frame(slot, bg=PANEL, height=2)
            underline.pack(fill="x")
            self.nav_buttons[item] = (slot, button, underline)

        safe = tk.Label(header, text="● 旁路管理", bg=PANEL, fg=SUCCESS, font=("Microsoft YaHei UI", 9))
        safe.pack(side="right", padx=24)

        separator = tk.Frame(self, bg=BORDER, height=1)
        separator.pack(fill="x")
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True)

        status = tk.Label(self, textvariable=self.status_var, anchor="w", bg="#fafafa", fg=MUTED, padx=18, pady=7, font=("Microsoft YaHei UI", 9), highlightbackground=BORDER, highlightthickness=1)
        status.pack(fill="x")
        self._select_top_tab("运行总览")

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _select_top_tab(self, selected: str) -> None:
        self.current_page = selected
        for item, (_slot, button, underline) in self.nav_buttons.items():
            button.configure(fg=ACCENT if item == selected else TEXT)
            underline.configure(bg=ACCENT if item == selected else PANEL)

    def _show_page(self, item: str) -> None:
        self._select_top_tab(item)
        if item == "运行总览":
            self.show_overview()
        elif item == "后台任务":
            self.show_tasks()
        elif item == "手动工具":
            self.show_manual_tools()
        elif item == "飞书工具":
            self.show_feishu_tools()
        elif item == "设置":
            self.show_settings(self.current_category)

    def _page_heading(self, title: str, intro: str) -> None:
        ttk.Label(self.content, text=title, style="Section.TLabel").pack(anchor="w", padx=28, pady=(22, 5))
        tk.Label(self.content, text=intro, bg=BG, fg=MUTED, justify="left", wraplength=1040, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=28, pady=(0, 14))

    def show_overview(self) -> None:
        self._clear_content()
        self._page_heading("运行总览", "只读检查本机代码、端口和计划任务。打开控制台和刷新状态不会停止、重启或重新安装任何服务。")
        notice = tk.Frame(self.content, bg="#f0f8ee", highlightbackground="#c9e4c5", highlightthickness=1)
        notice.pack(fill="x", padx=28, pady=(0, 12))
        tk.Label(notice, text="旁路管理已启用", bg="#f0f8ee", fg=SUCCESS, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=15, pady=(10, 2))
        tk.Label(notice, text="配置保存后仅记录变更，不会自动重启网页、Tunnel、Worker 或缓存任务。", bg="#f0f8ee", fg="#3f5f3f", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=15, pady=(0, 10))
        self.overview_frame = tk.Frame(self.content, bg=BG)
        self.overview_frame.pack(fill="both", expand=True, padx=22)
        ttk.Button(self.content, text="刷新实际状态", command=self._refresh_overview).pack(anchor="e", padx=28, pady=14)
        self._refresh_overview()

    def _refresh_overview(self) -> None:
        self.status_var.set("正在读取 Git、端口和 Windows 任务状态……")
        for child in self.overview_frame.winfo_children():
            child.destroy()
        ttk.Label(self.overview_frame, text="正在检查，请稍候……").pack(anchor="w")

        def worker() -> None:
            try:
                snapshot = system_snapshot()
                self.after(0, lambda: self._render_overview(snapshot))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("状态检查失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _render_overview(self, snapshot: dict[str, Any]) -> None:
        for child in self.overview_frame.winfo_children():
            child.destroy()
        git = snapshot["git"]
        web = snapshot["local_web"]
        rows = [
            ("应用版本", snapshot["version"], "代码中的 APP_VERSION"),
            ("Git 分支 / 修订", f"{git['branch']} · {git['revision']}", f"工作区有修改：{git['dirty']}"),
            ("Git 远端", git["remote"] or "未配置", "git remote origin"),
            ("本地 Web", f"{web['address']}:{web['port']}", "正在监听" if web["listening"] else "未监听"),
        ]
        for index, (label, value, note) in enumerate(rows):
            card = tk.Frame(self.overview_frame, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            tk.Label(card, text=label, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=16, pady=(14, 3))
            value_size = 10 if label == "Git 远端" else 12
            tk.Label(card, text=value, bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", value_size, "bold"), wraplength=510, justify="left").pack(anchor="w", padx=16)
            tk.Label(card, text=note, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=16, pady=(5, 14))
        self.overview_frame.columnconfigure(0, weight=1)
        self.overview_frame.columnconfigure(1, weight=1)
        self.status_var.set("实际状态已刷新")

    def show_settings(self, category: str) -> None:
        self._clear_content()
        self.current_category = category
        shell = tk.Frame(self.content, bg=BG)
        shell.pack(fill="both", expand=True, padx=22, pady=(18, 16))
        main = tk.Frame(shell, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        rail = tk.Frame(shell, bg=PANEL, width=250, highlightbackground=BORDER, highlightthickness=1)
        rail.pack(side="right", fill="y", padx=(18, 0))
        rail.pack_propagate(False)

        heading = tk.Frame(main, bg=BG)
        heading.pack(fill="x", padx=6)
        ttk.Label(heading, text=category, style="Section.TLabel").pack(side="left")
        count = sum(1 for item in SETTINGS if item.category == category)
        tk.Label(heading, text=f"{count} 项", bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=9, pady=(4, 0))
        if any(item.sensitive for item in SETTINGS if item.category == category):
            ttk.Button(heading, text="立即锁定敏感项" if self.unlocked else "解锁敏感项", command=self._lock if self.unlocked else self._unlock).pack(side="right")
        tk.Label(main, text="每项均显示本机保存位置、平台修改入口和生效范围。保存配置不会自动中断正在运行的应用。", bg=BG, fg=MUTED, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=6, pady=(5, 12))

        scroller = ScrollableFrame(main)
        scroller.pack(fill="both", expand=True)
        self.setting_vars: dict[str, tk.StringVar] = {}
        for spec in SETTINGS:
            if spec.category == category:
                self._setting_card(scroller.inner, spec)

        tk.Label(rail, text="设置分类", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(18, 10))
        for index, item in enumerate(CATEGORIES, start=1):
            selected = item == category
            row = tk.Frame(rail, bg=ACCENT_SOFT if selected else PANEL, height=43, cursor="hand2")
            row.pack(fill="x", padx=8, pady=1)
            row.pack_propagate(False)
            number = tk.Label(row, text=str(index), width=3, bg=ACCENT_SOFT if selected else PANEL, fg=ACCENT if selected else "#999999", font=("Segoe UI", 9, "bold" if selected else "normal"))
            number.pack(side="left", padx=(6, 0))
            label = tk.Label(row, text=item, anchor="w", bg=ACCENT_SOFT if selected else PANEL, fg=ACCENT if selected else TEXT, font=("Microsoft YaHei UI", 9, "bold" if selected else "normal"))
            label.pack(side="left", fill="both", expand=True)
            for widget in (row, number, label):
                widget.bind("<Button-1>", lambda _event, name=item: self.show_settings(name))
        tk.Label(rail, text="配置仅在明确点击保存后写入。\n需重启的项目会单独提示。", bg=PANEL, fg=MUTED, justify="left", wraplength=200, font=("Microsoft YaHei UI", 8)).pack(side="bottom", anchor="w", padx=18, pady=18)

    def _setting_card(self, parent, spec) -> None:
        local, external = configuration_location(spec)
        value = read_setting(spec)
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", padx=6, pady=(0, 10))

        top = tk.Frame(card, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(14, 8))
        copy = tk.Frame(top, bg=PANEL)
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text=spec.label, bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        tk.Label(copy, text=spec.description, bg=PANEL, fg=MUTED, justify="left", wraplength=480, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(3, 0))

        value_var = tk.StringVar(value=_display_value(spec, value, self.unlocked))
        self.setting_vars[spec.key] = value_var
        editor = tk.Frame(top, bg=PANEL)
        editor.pack(side="right", padx=(18, 0))
        if spec.value_type == "bool":
            field = ttk.Combobox(editor, textvariable=value_var, values=("true", "false"), state="readonly", width=24)
        else:
            field = ttk.Entry(editor, textvariable=value_var, show="•" if (spec.sensitive and not self.unlocked) else "", width=26)
        field.pack(side="left")
        if spec.sensitive and not self.unlocked:
            field.configure(state="disabled")
        ttk.Button(editor, text="保存", style="Accent.TButton", command=lambda item=spec, variable=value_var: self._save_setting(item, variable)).pack(side="right", padx=(7, 0))

        meta = tk.Frame(card, bg="#fbfbfb", highlightbackground="#eeeeee", highlightthickness=1)
        meta.pack(fill="x")
        text = f"本机：{local}\n入口：{external}\n生效：{spec.restart_scope}"
        tk.Label(meta, text=text, bg="#fbfbfb", fg=MUTED, justify="left", wraplength=700, font=("Microsoft YaHei UI", 8)).pack(side="left", fill="x", expand=True, padx=16, pady=10)
        actions = tk.Frame(meta, bg="#fbfbfb")
        actions.pack(side="right", padx=12)
        ttk.Button(actions, text="打开本机位置", command=lambda item=spec: self._open_local(item)).pack(side="left")
        ttk.Button(actions, text="打开平台入口", command=lambda item=spec: self._open_external(item)).pack(side="left", padx=(6, 0))

    def _save_setting(self, spec, variable: tk.StringVar) -> None:
        self.current_spec = spec
        if spec.sensitive and not self.unlocked:
            self._unlock()
            return
        try:
            write_setting(spec, variable.get())
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.status_var.set(f"已保存：{spec.label}；未自动重启任何服务；备份位于 work/control_center/backups")
        messagebox.showinfo("保存成功", f"{spec.label} 已保存。\n\n没有停止或重启正在运行的应用。\n需要时请在后台任务页手动执行：{spec.restart_scope}", parent=self)
        self.show_settings(spec.category)

    def show_manual_tools(self) -> None:
        self._clear_content()
        self._page_heading("手动工具", "集中运行页面缓存、联系人缓存、仓库图片缓存和发布前校验。普通工具只保留本地结果，不会自动提交或重启。")
        scroller = ScrollableFrame(self.content)
        scroller.pack(fill="both", expand=True, padx=22, pady=(0, 16))

        release = tk.Frame(scroller.inner, bg="#f4f9fd", highlightbackground="#b8d8ef", highlightthickness=1)
        release.pack(fill="x", padx=6, pady=(0, 12))
        release_copy = tk.Frame(release, bg="#f4f9fd")
        release_copy.pack(side="left", fill="both", expand=True, padx=18, pady=16)
        tk.Label(release_copy, text="版本刷新", bg="#f4f9fd", fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        tk.Label(
            release_copy,
            text="自动递增版本 → 刷新全部页面缓存 → 完整测试 → 重新打包控制程序 → 提交并推送 master → 同步并重启运行组件 → 健康验证",
            bg="#f4f9fd",
            fg=MUTED,
            justify="left",
            wraplength=760,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(5, 8))
        status = latest_release_status()
        if status:
            status_color = SUCCESS if status.get("state") == "success" else "#c42b1c" if status.get("state") == "failed" else ACCENT
            status_text = f"最近状态：{status.get('stage', '—')} · {status.get('message', '')} · {status.get('updated_at', '')}"
        else:
            status_color = MUTED
            status_text = "尚未通过控制台执行版本刷新。"
        tk.Label(release_copy, text=status_text, bg="#f4f9fd", fg=status_color, justify="left", wraplength=760, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        release_actions = tk.Frame(release, bg="#f4f9fd")
        release_actions.pack(side="right", padx=18)
        ttk.Button(release_actions, text="查看发布日志", command=self._show_latest_release_log).pack(pady=(0, 7))
        ttk.Button(release_actions, text="开始版本刷新", style="Accent.TButton", command=self._start_release).pack()

        tk.Label(scroller.inner, text="缓存与维护程序", bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=8, pady=(2, 8))
        for tool in MANUAL_TOOLS:
            card = tk.Frame(scroller.inner, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", padx=6, pady=(0, 9))
            copy = tk.Frame(card, bg=PANEL)
            copy.pack(side="left", fill="both", expand=True, padx=16, pady=13)
            tk.Label(copy, text=tool.label, bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
            tk.Label(copy, text=tool.description, bg=PANEL, fg=MUTED, justify="left", wraplength=720, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(3, 2))
            result_color = "#c42b1c" if tool.interrupts_services else MUTED
            tk.Label(copy, text=tool.result, bg=PANEL, fg=result_color, justify="left", wraplength=720, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
            ttk.Button(card, text="一键启动", command=lambda item=tool: self._start_manual_tool(item)).pack(side="right", padx=18)

    def _start_manual_tool(self, tool: ManualTool) -> None:
        if tool.key == "RefreshCommitRestartApp":
            self._start_release()
            return
        if self.operation_running:
            messagebox.showwarning("已有程序运行", "请等待当前手动程序完成。", parent=self)
            return
        if tool.interrupts_services and not messagebox.askyesno(
            "高风险操作确认",
            f"“{tool.label}”会短暂中断网页或后台 Worker。\n\n仅在发布后恢复或人工维护时使用，是否继续？",
            parent=self,
        ):
            return
        self.operation_running = True
        window, text = self._create_log_window(f"运行日志 · {tool.label}")
        self.status_var.set(f"正在运行：{tool.label}……")

        def append(line: str) -> None:
            self.after(0, lambda value=line: self._append_log(text, value))

        def worker() -> None:
            try:
                code, output = run_manual_tool(tool, append)
            except Exception as exc:
                self.after(0, lambda error=exc: self._manual_tool_finished(tool, 1, str(error), window))
                return
            self.after(0, lambda: self._manual_tool_finished(tool, code, output, window))

        threading.Thread(target=worker, daemon=True).start()

    def _manual_tool_finished(self, tool: ManualTool, code: int, output: str, window: tk.Toplevel) -> None:
        self.operation_running = False
        parent = window if window.winfo_exists() else self
        if code == 0:
            self.status_var.set(f"手动程序已完成：{tool.label}")
            messagebox.showinfo("运行完成", f"{tool.label} 已完成。\n\n{tool.result}", parent=parent)
        else:
            self.status_var.set(f"手动程序失败：{tool.label}")
            messagebox.showerror("运行失败", output[-1800:] or "请查看运行日志。", parent=parent)

    def _create_log_window(self, title: str) -> tuple[tk.Toplevel, tk.Text]:
        window = tk.Toplevel(self)
        window.title(title)
        window.geometry("980x620")
        text = tk.Text(window, wrap="word", bg="#101820", fg="#d8e4ee", insertbackground="#ffffff", font=("Consolas", 9), padx=12, pady=12)
        text.pack(fill="both", expand=True)
        text.insert("end", "等待程序输出……\n")
        return window, text

    @staticmethod
    def _append_log(text: tk.Text, line: str) -> None:
        if not text.winfo_exists():
            return
        text.insert("end", line + "\n")
        text.see("end")

    def _show_latest_release_log(self) -> None:
        path = latest_release_log()
        if path is None:
            messagebox.showinfo("暂无日志", "尚未生成版本刷新日志。", parent=self)
            return
        window, text = self._create_log_window("最近版本刷新日志")
        text.delete("1.0", "end")
        text.insert("1.0", path.read_text(encoding="utf-8-sig", errors="replace"))
        text.configure(state="disabled")

    def _start_release(self) -> None:
        if self.operation_running:
            messagebox.showwarning("已有程序运行", "请等待当前手动程序完成。", parent=self)
            return
        try:
            preview = release_preview()
        except Exception as exc:
            messagebox.showerror("发布预检失败", str(exc), parent=self)
            return
        changes = "\n".join(preview.changed_files[:18]) or "（当前没有未提交文件；流程仍会递增版本并刷新缓存）"
        if len(preview.changed_files) > 18:
            changes += f"\n……另有 {len(preview.changed_files) - 18} 项"
        prompt = (
            f"当前分支：{preview.branch}\n"
            f"当前版本：{preview.current_version}\n"
            f"目标版本：{preview.next_version}\n\n"
            f"将纳入发布的本地修改：\n{changes}\n\n"
            "流程会关闭并在完成后重新打开控制程序，也会短暂重启本地网页、Tunnel 和后台 Worker。是否进入最终确认？"
        )
        if not messagebox.askyesno("版本刷新预览", prompt, parent=self):
            return
        commit_message = simpledialog.askstring(
            "GitHub 提交说明",
            "请输入本次版本刷新的提交说明：",
            initialvalue=f"Release {preview.next_version}",
            parent=self,
        )
        if commit_message is None or not commit_message.strip():
            return
        if not messagebox.askyesno(
            "最终发布确认",
            f"确定执行 {preview.next_version} 的完整刷新吗？\n\n"
            "开始后控制程序会关闭；缓存、测试或推送失败时会停止后续步骤并保留日志，不会跳过失败继续重启。",
            parent=self,
        ):
            return
        try:
            launch_release_worker(control_center_pid=os.getpid(), commit_message=commit_message.strip())
        except Exception as exc:
            messagebox.showerror("无法启动版本刷新", str(exc), parent=self)
            return
        self.status_var.set("版本刷新已交给独立发布程序；控制台即将关闭，完成后会自动重新打开。")
        self.after(500, self.destroy)

    def _on_setting_selected(self, _event=None) -> None:
        selected = self.settings_tree.selection()
        if selected:
            self._render_setting_detail(SETTINGS_BY_KEY[selected[0]])

    def _render_setting_detail(self, spec) -> None:
        self.current_spec = spec
        for child in self.detail_frame.winfo_children():
            child.destroy()
        local, external = configuration_location(spec)
        value = read_setting(spec)
        ttk.Label(self.detail_frame, text=spec.label, style="Section.TLabel").pack(anchor="w", padx=18, pady=(18, 8))
        tk.Label(self.detail_frame, text=spec.description, bg="#f8faff", fg="#55657d", justify="left", wraplength=370).pack(anchor="w", padx=18)
        tk.Label(self.detail_frame, text="当前值", bg="#f8faff", fg="#263a59", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        self.value_var = tk.StringVar(value=_display_value(spec, value, self.unlocked))
        self.value_entry = ttk.Entry(self.detail_frame, textvariable=self.value_var, show="" if (not spec.sensitive or self.unlocked) else "•")
        self.value_entry.pack(fill="x", padx=18)
        if spec.sensitive:
            ttk.Button(self.detail_frame, text="解锁敏感项" if not self.unlocked else "敏感项已解锁", command=self._unlock).pack(anchor="w", padx=18, pady=(8, 0))
        self._detail_block("本机保存位置", local)
        self._detail_block("从哪里打开和修改", external)
        self._detail_block("修改后如何生效", spec.restart_scope)
        buttons = tk.Frame(self.detail_frame, bg="#f8faff")
        buttons.pack(fill="x", padx=18, pady=18)
        ttk.Button(buttons, text="打开本机位置", command=lambda: self._open_local(spec)).pack(side="left")
        ttk.Button(buttons, text="打开平台入口", command=lambda: self._open_external(spec)).pack(side="left", padx=7)
        ttk.Button(buttons, text="保存", command=self._save_current).pack(side="right")

    def _detail_block(self, title: str, text: str) -> None:
        tk.Label(self.detail_frame, text=title, bg="#f8faff", fg="#263a59", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=18, pady=(14, 3))
        tk.Label(self.detail_frame, text=text, bg="#f8faff", fg="#5d6b82", justify="left", wraplength=370).pack(anchor="w", padx=18)

    def _unlock(self) -> None:
        if self.unlocked:
            return
        expected = str(read_toml_setting(SECRETS_PATH, "CONTROL_CENTER_MASTER_PASSWORD") or read_toml_setting(SECRETS_PATH, "INVENTORY_VIEW_PASSWORD") or "")
        if not expected:
            if not messagebox.askyesno("尚未设置主密码", "本机尚未配置控制台主密码。是否仅在本次会话解锁，并立即设置该密码？", parent=self):
                return
            self.unlocked = True
        else:
            supplied = simpledialog.askstring("解锁敏感配置", "请输入配置控制台主密码：", show="*", parent=self)
            if supplied is None:
                return
            if not hmac.compare_digest(supplied, expected):
                messagebox.showerror("解锁失败", "密码不正确。", parent=self)
                return
            self.unlocked = True
        if self.current_page == "设置":
            self.show_settings(self.current_spec.category if self.current_spec else self.current_category)

    def _lock(self) -> None:
        self.unlocked = False
        self.status_var.set("敏感配置已重新锁定")
        if self.current_page == "设置":
            self.show_settings(self.current_category)

    def _save_current(self) -> None:
        spec = self.current_spec
        if spec is None:
            return
        if spec.sensitive and not self.unlocked:
            self._unlock()
            if not self.unlocked:
                return
            return
        try:
            value = write_setting(spec, self.value_var.get())
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.status_var.set(f"已保存：{spec.label}；备份位于 work/control_center/backups")
        messagebox.showinfo("保存成功", f"{spec.label} 已保存。\n\n生效范围：{spec.restart_scope}\n云端同名配置不会由本机自动覆盖，请按右侧入口同步。", parent=self)
        self._render_setting_detail(spec)

    def _open_local(self, spec) -> None:
        path = SECRETS_PATH if spec.source == "secret" else STREAMLIT_CONFIG_PATH if spec.source == "streamlit" else ROOT / "config" / "project_config.json"
        os.startfile(str(path.parent))

    def _open_external(self, spec) -> None:
        if spec.key.startswith("feishu.app") or spec.key.startswith("feishu.approval_"):
            url = "https://open.feishu.cn/app"
        elif spec.key in {"feishu.base_token", "feishu.base_url"} or spec.key.startswith("table.") or spec.key.startswith("queue."):
            configured = str(read_toml_setting(SECRETS_PATH, "FEISHU_BITABLE_WEB_URL") or "")
            token = str(read_toml_setting(SECRETS_PATH, "FEISHU_BITABLE_APP_TOKEN") or "")
            url = configured or (f"https://pudutech.feishu.cn/base/{token}" if token else "https://www.feishu.cn/product/base")
        elif spec.key.startswith("github."):
            url = f"https://github.com/{get_setting('project.github_repository', '')}/settings/secrets/actions"
        elif spec.key.startswith("cloudflare.") or spec.key == "deployment.custom_domain":
            url = "https://one.dash.cloudflare.com/"
        elif spec.key == "deployment.streamlit_url":
            url = "https://share.streamlit.io/"
        else:
            url = "https://github.com/" + str(get_setting("project.github_repository", ""))
        webbrowser.open(url)

    def show_tasks(self) -> None:
        self._clear_content()
        self._page_heading("后台任务", "查看计划任务和日志不会干扰服务。只有你明确点击启动、停止、重启或同步后才会执行操作。")
        tree_shell = tk.Frame(self.content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tree_shell.pack(fill="both", expand=True, padx=28)
        tree = ttk.Treeview(tree_shell, columns=("name", "state", "result", "next"), show="headings", selectmode="browse")
        for key, title, width in (("name", "任务", 310), ("state", "状态", 120), ("result", "最近结果", 140), ("next", "下次运行", 220)):
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True)
        self.task_tree = tree
        controls = tk.Frame(self.content, bg=BG)
        controls.pack(fill="x", padx=28, pady=14)
        for action, label in (("start", "启动"), ("run", "立即运行"), ("restart", "重启"), ("stop", "停止")):
            ttk.Button(controls, text=label, command=lambda a=action: self._task_action(a)).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="同步所选任务配置", command=self._synchronize_task).pack(side="left", padx=10)
        ttk.Button(controls, text="查看最近日志", command=self._show_task_log).pack(side="left", padx=10)
        ttk.Button(controls, text="刷新", command=self._refresh_tasks).pack(side="right")
        self._refresh_tasks()

    def _refresh_tasks(self) -> None:
        self.status_var.set("正在读取 Windows 任务状态……")
        for row in self.task_tree.get_children():
            self.task_tree.delete(row)

        def worker() -> None:
            snapshot = system_snapshot()["tasks"]
            self.after(0, lambda: self._render_tasks(snapshot))

        threading.Thread(target=worker, daemon=True).start()

    def _render_tasks(self, statuses: dict[str, dict[str, Any]]) -> None:
        for task in TASKS:
            status = statuses.get(task.key, {})
            installed = status.get("installed", False)
            state = status.get("state", "未安装" if not installed else "未知")
            result = status.get("last_result", "—")
            next_run = status.get("next_run", "—") or "—"
            self.task_tree.insert("", "end", iid=task.key, values=(f"{task.label} · {task.task_name}", state, result, next_run))
        self.status_var.set("后台任务状态已刷新")

    def _selected_task(self):
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showwarning("请选择任务", "请先选择一项后台任务。", parent=self)
            return None
        return TASK_BY_KEY[selection[0]]

    def _task_action(self, action: str) -> None:
        task = self._selected_task()
        if task is None:
            return
        if action in {"stop", "restart"} and not messagebox.askyesno("高风险操作确认", f"该操作会短暂中断对应服务。\n\n确定要{ '停止' if action == 'stop' else '重启' }“{task.label}”吗？", parent=self):
            return
        try:
            control_task(task, action)
        except Exception as exc:
            messagebox.showerror("任务操作失败", str(exc), parent=self)
            return
        self.status_var.set(f"已提交任务操作：{task.label} / {action}")
        self.after(800, self._refresh_tasks)

    def _show_task_log(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        window = tk.Toplevel(self)
        window.title(f"最近日志 · {task.label}")
        window.geometry("1000x620")
        text = tk.Text(window, wrap="none", bg="#0d1726", fg="#d7e3f5", insertbackground="#ffffff", font=("Consolas", 9))
        text.pack(fill="both", expand=True)
        text.insert("1.0", tail_log(task))
        text.configure(state="disabled")

    def show_feishu_tools(self) -> None:
        self.show_worker_nodes()

    def _feishu_switcher(self, active: str) -> None:
        switcher = tk.Frame(self.content, bg=BG)
        switcher.pack(fill="x", padx=28, pady=(18, 0))
        for label, command in (("后台电脑节点", self.show_worker_nodes), ("审批实例", self.show_approval_instances)):
            selected = label == active
            tk.Button(switcher, text=label, command=command, bg=ACCENT if selected else PANEL, fg="#ffffff" if selected else TEXT, activebackground=ACCENT if selected else "#f0f0f0", activeforeground="#ffffff" if selected else TEXT, relief="flat", borderwidth=1, highlightbackground=BORDER, font=("Microsoft YaHei UI", 9), padx=18, pady=7, cursor="hand2").pack(side="left", padx=(0, 1))

    def show_worker_nodes(self) -> None:
        self._clear_content()
        self._feishu_switcher("后台电脑节点")
        self._page_heading("后台电脑节点", "实时读取飞书“后台任务节点列表”。刷新是只读操作；编辑时只更新优先级和启用状态。")
        tree_shell = tk.Frame(self.content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tree_shell.pack(fill="both", expand=True, padx=28)
        tree = ttk.Treeview(tree_shell, columns=("host", "node", "priority", "enabled", "status", "version", "heartbeat"), show="headings", selectmode="browse")
        columns = (("host", "电脑", 150), ("node", "节点标识", 220), ("priority", "优先级", 75), ("enabled", "启用", 65), ("status", "状态", 90), ("version", "版本", 90), ("heartbeat", "最后心跳", 180))
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True)
        self.node_tree = tree
        controls = tk.Frame(self.content, bg=BG)
        controls.pack(fill="x", padx=28, pady=14)
        ttk.Button(controls, text="编辑优先级与启用状态", command=self._edit_worker_node).pack(side="left")
        ttk.Button(controls, text="刷新飞书实时数据", command=self._refresh_worker_nodes).pack(side="right")
        self._refresh_worker_nodes()

    def _refresh_worker_nodes(self) -> None:
        self.status_var.set("正在读取飞书后台节点……")
        for row in self.node_tree.get_children():
            self.node_tree.delete(row)

        def worker() -> None:
            try:
                nodes = load_worker_nodes()
                self.after(0, lambda: self._render_worker_nodes(nodes))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("节点读取失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _render_worker_nodes(self, nodes) -> None:
        self.worker_nodes = {node.record_id: node for node in nodes}
        for node in nodes:
            self.node_tree.insert("", "end", iid=node.record_id, values=(node.hostname, node.node_id, node.priority, "是" if node.enabled else "否", node.status, node.version, node.heartbeat))
        self.status_var.set(f"已读取 {len(nodes)} 个飞书后台节点")

    def _edit_worker_node(self) -> None:
        selected = self.node_tree.selection()
        if not selected:
            messagebox.showwarning("请选择节点", "请先选择一台后台电脑节点。", parent=self)
            return
        if not self.unlocked:
            self._unlock()
            if not self.unlocked:
                return
        node = self.worker_nodes[selected[0]]
        priority = simpledialog.askinteger("节点优先级", f"设置“{node.hostname or node.node_id}”的优先级（数值越小越优先）：", initialvalue=node.priority, minvalue=1, maxvalue=10000, parent=self)
        if priority is None:
            return
        enabled = messagebox.askyesno("节点启用状态", "选择“是”启用该节点；选择“否”停用该节点。", default="yes" if node.enabled else "no", parent=self)
        if not messagebox.askyesno("确认写入飞书", f"节点：{node.hostname or node.node_id}\n优先级：{priority}\n是否启用：{'是' if enabled else '否'}\n\n只更新这两个字段，是否继续？", parent=self):
            return

        def worker() -> None:
            try:
                update_worker_node(node.record_id, priority=priority, enabled=enabled)
                self.after(0, self._refresh_worker_nodes)
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("节点更新失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def show_approval_instances(self) -> None:
        self._clear_content()
        self._feishu_switcher("审批实例")
        self._page_heading("飞书审批实例", "从“物料申请单”只读查询审批实例；固定审批定义 Code 请在设置页修改。")
        tree_shell = tk.Frame(self.content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tree_shell.pack(fill="both", expand=True, padx=28)
        tree = ttk.Treeview(tree_shell, columns=("request", "instance", "status", "requester", "time"), show="headings")
        for key, title, width in (("request", "申请单号", 150), ("instance", "审批实例 Code", 320), ("status", "审批状态", 110), ("requester", "申请人", 120), ("time", "提交时间", 180)):
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True)
        self.approval_tree = tree
        ttk.Button(self.content, text="刷新飞书审批实例", command=self._refresh_approval_instances).pack(anchor="e", padx=28, pady=14)
        self._refresh_approval_instances()

    def _refresh_approval_instances(self) -> None:
        self.status_var.set("正在读取飞书审批实例……")
        for row in self.approval_tree.get_children():
            self.approval_tree.delete(row)

        def worker() -> None:
            try:
                rows = load_approval_instances()
                self.after(0, lambda: self._render_approval_instances(rows))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("审批实例读取失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _render_approval_instances(self, rows) -> None:
        for index, row in enumerate(rows):
            self.approval_tree.insert("", "end", iid=f"approval-{index}", values=(row["request_no"], row["instance_code"], row["status"], row["requester"], row["submitted_at"]))
        self.status_var.set(f"已读取 {len(rows)} 条审批实例")

    def _synchronize_task(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        if not messagebox.askyesno(
            "确认同步任务配置",
            f"将使用当前控制台配置重新安装并重启“{task.label}”所属运行组。\n\n安装器会复制 Secrets 到独立 Runner，并可能短暂中断对应服务。是否继续？",
            parent=self,
        ):
            return
        self.status_var.set(f"正在同步任务配置：{task.label}……")

        def worker() -> None:
            try:
                output = synchronize_task_group(task)
                self.after(0, lambda: self._synchronize_finished(task.label, output))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("同步失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _synchronize_finished(self, label: str, output: str) -> None:
        self.status_var.set(f"任务配置已同步：{label}；请继续检查日志和最终业务结果")
        messagebox.showinfo("同步完成", output[-1600:], parent=self)
        self._refresh_tasks()


def main() -> None:
    app = ControlCenter()
    app.mainloop()


if __name__ == "__main__":
    main()
