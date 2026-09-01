from __future__ import annotations

import re
from urllib.parse import urlparse

from .configuration import SettingSpec


CATEGORIES = (
    "项目与版本",
    "飞书连接",
    "飞书数据表",
    "审批与通知",
    "GitHub 与部署",
    "本地端口与界面",
    "后台队列与 Worker",
    "缓存与计划任务",
    "安全与默认值",
)


def _nonempty_text(value: object) -> None:
    if not str(value).strip():
        raise ValueError("该配置不能为空。")


def _positive(value: object) -> None:
    if float(value) <= 0:
        raise ValueError("该配置必须大于 0。")


def _port(value: object) -> None:
    number = int(value)
    if not 1 <= number <= 65535:
        raise ValueError("端口必须在 1 到 65535 之间。")


def _url(value: object) -> None:
    if not value:
        return
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("请输入完整的 http:// 或 https:// 地址。")


def _repository(value: object) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(value)):
        raise ValueError("GitHub 仓库格式应为 账号/仓库。")


def _time_list(value: object) -> None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(item)):
            raise ValueError(f"时间格式不正确：{item}，应为 HH:MM。")


def _spec(
    key: str,
    label: str,
    category: str,
    source_key: str,
    description: str,
    *,
    source: str = "project",
    value_type: str = "str",
    sensitive: bool = False,
    required: bool = False,
    restart_scope: str = "主应用与相关 Worker",
    validator=None,
) -> SettingSpec:
    return SettingSpec(
        key=key,
        label=label,
        category=category,
        source=source,
        source_key=source_key,
        description=description,
        value_type=value_type,
        sensitive=sensitive,
        required=required,
        restart_scope=restart_scope,
        validator=validator,
    )


SETTINGS: tuple[SettingSpec, ...] = (
    _spec("project.name", "项目显示名称", "项目与版本", "project.display_name", "控制台和文档中展示的项目名称。", required=True, restart_scope="控制台"),
    _spec("project.github_account", "GitHub 账号", "项目与版本", "project.github_account", "项目维护账号；仓库地址仍以“账号/仓库”配置为准。", required=True, restart_scope="发布工具"),
    _spec("project.github_branch", "发布分支", "项目与版本", "project.github_branch", "正式发布使用的唯一分支。", required=True, restart_scope="本地 Runner 与发布任务"),
    _spec("feishu.app_id", "飞书应用 App ID", "飞书连接", "FEISHU_APP_ID", "主飞书应用的 App ID。", source="secret", sensitive=True, required=True),
    _spec("feishu.app_secret", "飞书应用 App Secret", "飞书连接", "FEISHU_APP_SECRET", "主飞书应用密钥，仅保存在本机 Secrets，不进入 Git。", source="secret", sensitive=True, required=True),
    _spec("feishu.base_token", "多维表格 App Token", "飞书连接", "FEISHU_BITABLE_APP_TOKEN", "当前数据库所在多维表格的 App Token。", source="secret", sensitive=True, required=True),
    _spec("feishu.base_url", "多维表格网页链接", "飞书连接", "FEISHU_BITABLE_WEB_URL", "用于控制台和业务页跳转的 Base 链接；留空时按 App Token 生成。", source="secret", validator=_url),
    _spec("feishu.approval_id", "审批回写应用 App ID", "审批与通知", "FEISHU_APPROVAL_WRITEBACK_APP_ID", "审批回调与回写专用飞书应用。", source="secret", sensitive=True),
    _spec("feishu.approval_secret", "审批回写应用 Secret", "审批与通知", "FEISHU_APPROVAL_WRITEBACK_APP_SECRET", "审批回写应用密钥，仅保存在本机 Secrets。", source="secret", sensitive=True),
    _spec("feishu.approval_code", "审批定义 Code", "审批与通知", "feishu.approval_definition_code", "固定审批定义标识；审批实例 Code 是每次审批产生的运行数据，不在此处固定配置。", required=True),
    _spec("github.repository", "GitHub 仓库", "GitHub 与部署", "project.github_repository", "Git 克隆、缓存发布与 Actions 使用的账号/仓库。", required=True, validator=_repository),
    _spec("github.cache_workflow", "缓存工作流文件", "GitHub 与部署", "project.cache_workflow_file", "GitHub Actions 中刷新静态缓存的工作流文件名。", required=True),
    _spec("github.token", "GitHub 发布 Token", "GitHub 与部署", "GITHUB_CACHE_REFRESH_TOKEN", "触发 repository_dispatch 的 Token，仅保存在本机或云端 Secrets。", source="secret", sensitive=True),
    _spec("cloudflare.token", "Cloudflare Tunnel Token", "GitHub 与部署", "CLOUDFLARE_TUNNEL_TOKEN", "Named Tunnel 的运行令牌；控制台同步本地 Web Runner 时使用。", source="secret", sensitive=True),
    _spec("deployment.streamlit_url", "Streamlit Cloud 地址", "GitHub 与部署", "deployment.streamlit_app_url", "正式 Streamlit Cloud 入口。", required=True, validator=_url),
    _spec("deployment.custom_domain", "自定义域名", "GitHub 与部署", "deployment.custom_domain", "Cloudflare Tunnel 对外入口。", required=True, validator=_url),
    _spec("deployment.local_address", "本地监听地址", "本地端口与界面", "deployment.local_web.address", "本地 Runner 的监听地址，通常固定为 127.0.0.1。", required=True),
    _spec("deployment.local_port", "本地云端端口", "本地端口与界面", "deployment.local_web.port", "本地 Streamlit 与 Cloudflare Tunnel 必须使用同一端口。", value_type="int", required=True, validator=_port),
    _spec("deployment.web_root", "本地 Web Runner 目录", "本地端口与界面", "deployment.local_web.runner_root", "本地 Web 独立 Git 副本、Secrets、Tunnel Token 与日志目录。", required=True, restart_scope="重新安装本地 Web 与 Tunnel"),
    _spec("deployment.web_task", "本地 Web 任务名", "本地端口与界面", "deployment.local_web.web_task_name", "本地 Streamlit 的 Windows 计划任务名称。", required=True, restart_scope="重新安装本地 Web 与 Tunnel"),
    _spec("deployment.tunnel_task", "Cloudflare Tunnel 任务名", "本地端口与界面", "deployment.local_web.tunnel_task_name", "Named Tunnel 的 Windows 计划任务名称。", required=True, restart_scope="重新安装本地 Web 与 Tunnel"),
    _spec("streamlit.address", "开发运行监听地址", "本地端口与界面", "server.address", "直接运行 Streamlit 时的监听地址。", source="streamlit", required=True, restart_scope="本地 Streamlit"),
    _spec("streamlit.headless", "Streamlit 无界面模式", "本地端口与界面", "server.headless", "后台 Runner 是否以 headless 模式运行。", source="streamlit", value_type="bool", restart_scope="本地 Streamlit"),
    _spec("streamlit.upload", "最大上传大小（MB）", "本地端口与界面", "server.maxUploadSize", "Streamlit 单文件上传上限。", source="streamlit", value_type="int", validator=_positive, restart_scope="本地 Streamlit"),
    _spec("streamlit.telemetry", "发送 Streamlit 使用统计", "本地端口与界面", "browser.gatherUsageStats", "是否向 Streamlit 发送匿名使用统计。", source="streamlit", value_type="bool", restart_scope="本地 Streamlit"),
    _spec("streamlit.toolbar", "Streamlit 工具栏模式", "本地端口与界面", "client.toolbarMode", "生产页面工具栏显示模式。", source="streamlit", restart_scope="本地 Streamlit"),
    _spec("theme.primary", "主题主色", "本地端口与界面", "theme.primaryColor", "Streamlit 全局主题主色。", source="streamlit", restart_scope="本地 Streamlit"),
    _spec("theme.background", "主题背景色", "本地端口与界面", "theme.backgroundColor", "Streamlit 页面背景色。", source="streamlit", restart_scope="本地 Streamlit"),
    _spec("theme.secondary", "主题次级背景色", "本地端口与界面", "theme.secondaryBackgroundColor", "Streamlit 侧栏与容器背景色。", source="streamlit", restart_scope="本地 Streamlit"),
    _spec("theme.text", "主题文字色", "本地端口与界面", "theme.textColor", "Streamlit 全局文字颜色。", source="streamlit", restart_scope="本地 Streamlit"),
    _spec("queue.name", "后台任务队列表", "后台队列与 Worker", "feishu.tables.queue", "所有页面业务写入进入的飞书队列表。", required=True),
    _spec("queue.payload", "后台任务载荷表", "后台队列与 Worker", "feishu.tables.queue_payload", "超长队列载荷的分片存储表。", required=True),
    _spec("queue.worker_registry", "后台任务节点列表", "后台队列与 Worker", "feishu.tables.worker_registry", "记录电脑名称、优先级、心跳、版本和启用状态。", required=True),
    _spec("worker.task", "提交 Worker 任务名", "后台队列与 Worker", "submission_worker.task_name", "Windows 计划任务名称。", required=True, restart_scope="重新安装提交 Worker"),
    _spec("worker.root", "提交 Worker 运行目录", "后台队列与 Worker", "submission_worker.runner_root", "独立 Git 副本、虚拟环境、Secrets 和日志目录。", required=True, restart_scope="重新安装提交 Worker"),
    _spec("worker.poll", "队列轮询秒数", "后台队列与 Worker", "submission_worker.poll_seconds", "Worker 空闲时检查新任务的间隔。", value_type="float", validator=_positive),
    _spec("worker.lease", "任务租约秒数", "后台队列与 Worker", "submission_worker.lease_seconds", "处理中任务在 Worker 退出后可重新接管的等待时间。", value_type="int", validator=_positive),
    _spec("worker.retries", "最大重试次数", "后台队列与 Worker", "submission_worker.max_retries", "任务失败后的最大自动重试次数。", value_type="int", validator=_positive),
    _spec("queue.inline", "队列内联载荷上限", "后台队列与 Worker", "queue.payload_inline_limit", "小于该字符数的 JSON 直接保存在队列表。", value_type="int", validator=_positive),
    _spec("queue.chunk", "载荷分片大小", "后台队列与 Worker", "queue.payload_chunk_size", "超长载荷写入载荷表时的单片字符数。", value_type="int", validator=_positive),
    _spec("worker.priority", "本机 Worker 优先级", "后台队列与 Worker", "submission_worker.priority", "数值越小越优先；用于多电脑主备节点。", value_type="int", validator=_positive, restart_scope="重新安装提交 Worker"),
    _spec("worker.leader_check", "主节点检查秒数", "后台队列与 Worker", "submission_worker.leadership_check_interval_seconds", "多电脑节点重新判断主节点的间隔。", value_type="int", validator=_positive),
    _spec("worker.heartbeat", "节点心跳秒数", "后台队列与 Worker", "submission_worker.heartbeat_interval_seconds", "Worker 向飞书节点表回写版本与状态的间隔。", value_type="int", validator=_positive),
    _spec("worker.heartbeat_timeout", "节点失联判定秒数", "后台队列与 Worker", "submission_worker.heartbeat_timeout_seconds", "超过该时间未心跳的节点不再参与主节点选举。", value_type="int", validator=_positive),
    _spec("worker.inventory_schedule", "库存提醒扫描秒数", "后台队列与 Worker", "submission_worker.inventory_review_schedule_check_interval_seconds", "主 Worker 检查定时库存提醒的间隔。", value_type="int", validator=_positive),
    _spec("card.task", "飞书卡片 Worker 任务名", "后台队列与 Worker", "card_worker.task_name", "接收飞书卡片事件的常驻 Windows 任务。", required=True, restart_scope="重新安装卡片 Worker"),
    _spec("cache.task", "物料缓存任务名", "缓存与计划任务", "cache_runner.task_name", "生成并发布页面缓存的 Windows 任务。", required=True, restart_scope="重新安装缓存任务"),
    _spec("cache.contact_task", "联系人缓存任务名", "缓存与计划任务", "cache_runner.contact_task_name", "更新联系人部门缓存的 Windows 任务。", required=True, restart_scope="重新安装缓存任务"),
    _spec("cache.root", "缓存 Runner 目录", "缓存与计划任务", "cache_runner.runner_root", "缓存任务的独立 Git 副本、Secrets 和日志目录。", required=True, restart_scope="重新安装缓存任务"),
    _spec("cache.times", "物料缓存执行时间", "缓存与计划任务", "cache_runner.daily_times", "每天运行时间，多个时间以英文逗号分隔。", value_type="csv", validator=_time_list, restart_scope="重新安装缓存任务"),
    _spec("cache.contact_time", "联系人缓存时间", "缓存与计划任务", "cache_runner.contact_time", "联系人缓存任务的执行时间。", validator=_time_list, restart_scope="重新安装缓存任务"),
    _spec("cache.contact_days", "联系人缓存星期", "缓存与计划任务", "cache_runner.contact_days", "多个英文星期名以英文逗号分隔。", value_type="csv", restart_scope="重新安装缓存任务"),
    _spec("wake.task", "Streamlit 唤醒任务名", "缓存与计划任务", "streamlit_wake.task_name", "夜间唤醒检查的 Windows 计划任务名称。", required=True, restart_scope="重新配置唤醒任务"),
    _spec("wake.time", "Streamlit 唤醒时间", "缓存与计划任务", "streamlit_wake.daily_time", "每天检查线上应用的时间。", validator=_time_list, restart_scope="重新配置唤醒任务"),
    _spec("runtime.cache_ttl", "页面数据缓存秒数", "缓存与计划任务", "runtime.data_cache_ttl_seconds", "应用内短期数据缓存时间。", value_type="int", validator=_positive),
    _spec("runtime.zero_days", "零库存自动停用天数", "缓存与计划任务", "runtime.inventory_auto_disable_days", "零库存持续达到此天数后自动停用。", value_type="int", validator=_positive),
    _spec("security.inventory_password", "库存管理密码", "安全与默认值", "INVENTORY_VIEW_PASSWORD", "库存管理入口密码。", source="secret", sensitive=True, required=True),
    _spec("security.approval_password", "审批页面密码", "安全与默认值", "APPROVAL_VIEW_PASSWORD", "审批专用页面密码。", source="secret", sensitive=True),
    _spec("security.control_center_password", "配置控制台主密码", "安全与默认值", "CONTROL_CENTER_MASTER_PASSWORD", "查看或修改敏感项时的本机二次验证密码；未配置时回退为库存管理密码。", source="secret", sensitive=True),
    _spec("defaults.requester", "默认申请人", "安全与默认值", "DEFAULT_REQUESTER", "本地调试时的默认申请人。", source="secret"),
    _spec("defaults.department", "默认申请部门", "安全与默认值", "DEFAULT_REQUEST_DEPARTMENT", "本地调试时的默认部门。", source="secret"),
    _spec("defaults.position", "默认申请岗位", "安全与默认值", "DEFAULT_REQUEST_POSITION", "本地调试时的默认岗位。", source="secret"),
)


TABLE_SETTINGS = (
    ("request", "物料申请单"),
    ("request_line", "申请明细"),
    ("request_change", "申请变更记录"),
    ("material", "物料主数据"),
    ("category", "物料品类"),
    ("model", "产品型号"),
    ("language", "物料语种"),
    ("ledger", "库存流水"),
    ("user_permission", "用户权限"),
    ("gift_project", "周边礼品项目"),
    ("cultural_material", "文化周边库存"),
    ("region", "战区管理"),
)

SETTINGS += tuple(
    _spec(
        f"table.{key}",
        label,
        "飞书数据表",
        f"feishu.tables.{key}",
        f"应用按此精确表名发现并访问“{label}”；修改后必须先验证飞书实际表名。",
        required=True,
    )
    for key, label in TABLE_SETTINGS
)


SETTINGS_BY_KEY = {setting.key: setting for setting in SETTINGS}


def configuration_location(spec: SettingSpec) -> tuple[str, str]:
    """Return local storage and external modification guidance for every setting."""
    if spec.source == "secret":
        local = ".streamlit/secrets.toml（本机，Git 已忽略）"
        if spec.source_key == "CLOUDFLARE_TUNNEL_TOKEN":
            local += "；旧部署值也会从 Web Runner/cloudflare-token.txt 读取"
        elif spec.source_key == "CONTROL_CENTER_MASTER_PASSWORD":
            local += "；未单独设置时使用 INVENTORY_VIEW_PASSWORD"
        elif spec.source_key == "APPROVAL_VIEW_PASSWORD":
            local += "；未单独设置时当前代码仍使用兼容默认值"
    elif spec.source == "streamlit":
        local = ".streamlit/config.toml（随仓库版本管理）"
    else:
        local = "config/project_config.json（随仓库版本管理）"

    if spec.key.startswith("feishu.app") or spec.key.startswith("feishu.approval_"):
        external = "飞书开放平台 → 开发者后台 → 对应企业自建应用 → 凭证与基础信息"
    elif spec.key in {"feishu.base_token", "feishu.base_url"} or spec.key.startswith("table.") or spec.key.startswith("queue."):
        external = "飞书多维表格 → 打开目标 Base；App Token 在链接中，表名在左侧数据表列表中核对"
    elif spec.key == "feishu.approval_code":
        external = "飞书审批管理后台 → 审批定义；同步检查 anycross.feishu 下两份流程蓝图"
    elif spec.key.startswith("github."):
        external = "GitHub → 目标仓库；Token/Actions Secret 在 Settings → Secrets and variables → Actions"
    elif spec.key == "cloudflare.token" or spec.key == "deployment.custom_domain":
        external = "Cloudflare Dashboard → Zero Trust → Networks → Tunnels → 对应 Named Tunnel"
    elif spec.key == "deployment.streamlit_url":
        external = "Streamlit Community Cloud → Workspace → 目标应用 → Settings / Secrets"
    elif spec.category in {"后台队列与 Worker", "缓存与计划任务"}:
        external = "Windows 任务计划程序 → 任务计划程序库；安装/同步入口在 scripts 下对应 install_*_task.ps1"
    elif spec.category == "安全与默认值":
        external = "本机 Secrets 在控制台修改；云端同名值需在 Streamlit Cloud → App Settings → Secrets 同步"
    else:
        external = "本项目配置控制台；修改后按“生效范围”执行验证、重启或发布"
    return local, external
