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
from .system import TASKS, TASK_BY_KEY, control_task, current_app_version, synchronize_task_group, system_snapshot, tail_log


MASK = "••••••••••••"


def _display_value(spec, value: Any, unlocked: bool) -> str:
    if spec.sensitive and value not in (None, "") and not unlocked:
        return MASK
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value if value is not None else "")


class ControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"PUDU 配置与运行控制台 · {current_app_version()}")
        self.geometry("1360x820")
        self.minsize(1120, 700)
        self.configure(background="#f3f6fb")
        self.unlocked = False
        self.current_spec = None
        self.status_var = tk.StringVar(value="就绪")
        self._configure_style()
        self._build_layout()
        self.show_overview()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 18, "bold"), foreground="#0b2351", background="#ffffff")
        style.configure("Subheader.TLabel", font=("Microsoft YaHei UI", 10), foreground="#5d6b82", background="#ffffff")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 12, "bold"), foreground="#163b73")
        style.configure("Treeview", rowheight=31, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_layout(self) -> None:
        header = tk.Frame(self, bg="#ffffff", height=78)
        header.pack(fill="x")
        header.pack_propagate(False)
        ttk.Label(header, text="PUDU 配置与运行控制台", style="Header.TLabel").pack(anchor="w", padx=24, pady=(14, 0))
        ttk.Label(header, text="配置来源、修改入口、生效范围和后台任务集中管理", style="Subheader.TLabel").pack(anchor="w", padx=25, pady=(2, 0))

        body = tk.PanedWindow(self, orient="horizontal", sashwidth=1, bg="#d9e1ef")
        body.pack(fill="both", expand=True, padx=14, pady=14)

        nav = tk.Frame(body, bg="#102a56", width=220)
        body.add(nav, minsize=205)
        tk.Label(nav, text="导航", bg="#102a56", fg="#a9bddc", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
        self.nav_list = tk.Listbox(nav, bg="#102a56", fg="#edf4ff", selectbackground="#2563eb", selectforeground="#ffffff", relief="flat", borderwidth=0, highlightthickness=0, font=("Microsoft YaHei UI", 10), activestyle="none")
        self.nav_items = ["运行总览", "后台任务与日志", "后台电脑节点", "飞书审批实例", *CATEGORIES]
        for item in self.nav_items:
            self.nav_list.insert("end", item)
        self.nav_list.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        self.nav_list.bind("<<ListboxSelect>>", self._on_navigation)

        content = tk.Frame(body, bg="#ffffff")
        body.add(content, stretch="always")
        self.content = content

        status = tk.Label(self, textvariable=self.status_var, anchor="w", bg="#e8eef8", fg="#34445f", padx=14, pady=7, font=("Microsoft YaHei UI", 9))
        status.pack(fill="x")

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _on_navigation(self, _event=None) -> None:
        selection = self.nav_list.curselection()
        if not selection:
            return
        item = self.nav_items[selection[0]]
        if item == "运行总览":
            self.show_overview()
        elif item == "后台任务与日志":
            self.show_tasks()
        elif item == "后台电脑节点":
            self.show_worker_nodes()
        elif item == "飞书审批实例":
            self.show_approval_instances()
        else:
            self.show_settings(item)

    def show_overview(self) -> None:
        self._clear_content()
        title = ttk.Label(self.content, text="运行总览", style="Section.TLabel")
        title.pack(anchor="w", padx=22, pady=(20, 6))
        intro = tk.Label(self.content, text="这里显示当前代码、Git、本地端口和计划任务的实际状态。Running 只代表进程存在，最终结果仍需结合日志与业务读回判断。", bg="#ffffff", fg="#5d6b82", justify="left", wraplength=920)
        intro.pack(anchor="w", padx=22, pady=(0, 14))
        self.overview_frame = tk.Frame(self.content, bg="#ffffff")
        self.overview_frame.pack(fill="both", expand=True, padx=22)
        ttk.Button(self.content, text="刷新实际状态", command=self._refresh_overview).pack(anchor="e", padx=22, pady=14)
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
            card = tk.Frame(self.overview_frame, bg="#f6f9fe", highlightbackground="#dce5f3", highlightthickness=1)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            tk.Label(card, text=label, bg="#f6f9fe", fg="#607089", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(card, text=value, bg="#f6f9fe", fg="#102a56", font=("Microsoft YaHei UI", 12, "bold"), wraplength=410, justify="left").pack(anchor="w", padx=16)
            tk.Label(card, text=note, bg="#f6f9fe", fg="#65758c", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=16, pady=(4, 12))
        self.overview_frame.columnconfigure(0, weight=1)
        self.overview_frame.columnconfigure(1, weight=1)
        self.status_var.set("实际状态已刷新")

    def show_settings(self, category: str) -> None:
        self._clear_content()
        ttk.Label(self.content, text=category, style="Section.TLabel").pack(anchor="w", padx=22, pady=(20, 10))
        pane = tk.PanedWindow(self.content, orient="horizontal", sashwidth=1, bg="#dce5f3")
        pane.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        left = tk.Frame(pane, bg="#ffffff")
        right = tk.Frame(pane, bg="#f8faff", width=420)
        pane.add(left, stretch="always")
        pane.add(right, minsize=380)

        tree = ttk.Treeview(left, columns=("value", "source", "impact"), show="headings", selectmode="browse")
        tree.heading("value", text="配置项 / 当前值")
        tree.heading("source", text="保存来源")
        tree.heading("impact", text="修改后生效范围")
        tree.column("value", width=310)
        tree.column("source", width=180)
        tree.column("impact", width=210)
        tree.pack(fill="both", expand=True)
        self.settings_tree = tree
        self.detail_frame = right
        for spec in SETTINGS:
            if spec.category != category:
                continue
            value = read_setting(spec)
            source_text = configuration_location(spec)[0]
            tree.insert("", "end", iid=spec.key, values=(f"{spec.label}\n{_display_value(spec, value, self.unlocked)}", source_text, spec.restart_scope))
        tree.bind("<<TreeviewSelect>>", self._on_setting_selected)
        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            self._render_setting_detail(SETTINGS_BY_KEY[children[0]])

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
        if self.current_spec:
            self._render_setting_detail(self.current_spec)

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
        ttk.Label(self.content, text="后台任务与日志", style="Section.TLabel").pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(self.content, text="任务控制只允许操作项目清单内的固定任务。停止或重启前会再次确认。", bg="#ffffff", fg="#5d6b82").pack(anchor="w", padx=22, pady=(0, 10))
        tree = ttk.Treeview(self.content, columns=("name", "state", "result", "next"), show="headings", selectmode="browse")
        for key, title, width in (("name", "任务", 310), ("state", "状态", 120), ("result", "最近结果", 140), ("next", "下次运行", 220)):
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True, padx=22)
        self.task_tree = tree
        controls = tk.Frame(self.content, bg="#ffffff")
        controls.pack(fill="x", padx=22, pady=14)
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
        if action in {"stop", "restart"} and not messagebox.askyesno("确认任务操作", f"确定要{ '停止' if action == 'stop' else '重启' }“{task.label}”吗？", parent=self):
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

    def show_worker_nodes(self) -> None:
        self._clear_content()
        ttk.Label(self.content, text="后台电脑节点", style="Section.TLabel").pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(self.content, text="实时读取飞书“后台任务节点列表”。可调整节点优先级和启用状态；电脑名称、心跳、版本和运行状态由 Worker 自动回写。", bg="#ffffff", fg="#5d6b82").pack(anchor="w", padx=22, pady=(0, 10))
        tree = ttk.Treeview(self.content, columns=("host", "node", "priority", "enabled", "status", "version", "heartbeat"), show="headings", selectmode="browse")
        columns = (("host", "电脑", 150), ("node", "节点标识", 220), ("priority", "优先级", 75), ("enabled", "启用", 65), ("status", "状态", 90), ("version", "版本", 90), ("heartbeat", "最后心跳", 180))
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True, padx=22)
        self.node_tree = tree
        controls = tk.Frame(self.content, bg="#ffffff")
        controls.pack(fill="x", padx=22, pady=14)
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
        ttk.Label(self.content, text="飞书审批实例", style="Section.TLabel").pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(self.content, text="审批实例 Code 是每次业务运行产生的记录，这里从“物料申请单”实时查询；固定审批定义 Code 请在“审批与通知”配置页修改。", bg="#ffffff", fg="#5d6b82").pack(anchor="w", padx=22, pady=(0, 10))
        tree = ttk.Treeview(self.content, columns=("request", "instance", "status", "requester", "time"), show="headings")
        for key, title, width in (("request", "申请单号", 150), ("instance", "审批实例 Code", 320), ("status", "审批状态", 110), ("requester", "申请人", 120), ("time", "提交时间", 180)):
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="both", expand=True, padx=22)
        self.approval_tree = tree
        ttk.Button(self.content, text="刷新飞书审批实例", command=self._refresh_approval_instances).pack(anchor="e", padx=22, pady=14)
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
