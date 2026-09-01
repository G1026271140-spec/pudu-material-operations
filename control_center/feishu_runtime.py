from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Any

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig
from project_config import get_setting

from .configuration import SECRETS_PATH


def _credentials() -> tuple[str, str, str]:
    if not SECRETS_PATH.exists():
        raise RuntimeError("本机尚未创建 .streamlit/secrets.toml。")
    with SECRETS_PATH.open("rb") as stream:
        secrets = tomllib.load(stream)
    values = tuple(str(secrets.get(key) or "").strip() for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_BITABLE_APP_TOKEN"))
    if not all(values):
        raise RuntimeError("请先在“飞书连接”中补齐 App ID、App Secret 和 Base Token。")
    return values  # type: ignore[return-value]


def client_and_schema() -> tuple[FeishuBitableClient, dict[str, Any]]:
    client = FeishuBitableClient(FeishuBitableConfig(*_credentials()))
    return client, client.discover_schema()


def _table_id(schema: dict[str, Any], name: str) -> str:
    table = schema.get("tables", {}).get(name)
    if not table:
        raise RuntimeError(f"飞书 Base 中未找到配置的数据表：{name}")
    return str(table.get("table_id") or "")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(filter(None, (_cell_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "name", "value", "id", "record_id"):
            if key in value:
                return _cell_text(value[key])
        return ""
    return str(value)


@dataclass(frozen=True)
class WorkerNode:
    record_id: str
    node_id: str
    hostname: str
    priority: int
    heartbeat: str
    version: str
    status: str
    enabled: bool


def load_worker_nodes() -> list[WorkerNode]:
    client, schema = client_and_schema()
    table_name = str(get_setting("feishu.tables.worker_registry", "后台任务节点列表"))
    rows = client.list_records(_table_id(schema, table_name))
    nodes: list[WorkerNode] = []
    for row in rows:
        fields = row.get("fields") or {}
        enabled_text = _cell_text(fields.get("是否启用")).strip().lower()
        try:
            priority = int(float(_cell_text(fields.get("优先级")) or 100))
        except ValueError:
            priority = 100
        nodes.append(
            WorkerNode(
                record_id=str(row.get("record_id") or ""),
                node_id=_cell_text(fields.get("节点标识")),
                hostname=_cell_text(fields.get("电脑名称")),
                priority=priority,
                heartbeat=_cell_text(fields.get("最后心跳时间")),
                version=_cell_text(fields.get("应用版本")),
                status=_cell_text(fields.get("节点状态")),
                enabled=enabled_text in {"是", "true", "1", "yes"},
            )
        )
    return sorted(nodes, key=lambda node: (node.priority, node.hostname, node.node_id))


def update_worker_node(record_id: str, *, priority: int, enabled: bool) -> None:
    if not record_id:
        raise ValueError("节点记录缺少 record_id。")
    if not 1 <= priority <= 10_000:
        raise ValueError("节点优先级必须在 1 到 10000 之间。")
    client, schema = client_and_schema()
    table_name = str(get_setting("feishu.tables.worker_registry", "后台任务节点列表"))
    client.update_record(
        _table_id(schema, table_name),
        record_id,
        {"优先级": priority, "是否启用": "是" if enabled else "否"},
    )


def load_approval_instances(limit: int = 200) -> list[dict[str, str]]:
    client, schema = client_and_schema()
    table_name = str(get_setting("feishu.tables.request", "物料申请单"))
    rows = client.list_records(_table_id(schema, table_name))
    result: list[dict[str, str]] = []
    for row in reversed(rows[-limit:]):
        fields = row.get("fields") or {}
        instance = _cell_text(fields.get("审批实例Code") or fields.get("审批实例 Code"))
        if not instance:
            continue
        result.append(
            {
                "record_id": str(row.get("record_id") or ""),
                "request_no": _cell_text(fields.get("申请单号")),
                "instance_code": instance,
                "status": _cell_text(fields.get("审批状态") or fields.get("状态")),
                "requester": _cell_text(fields.get("申请人")),
                "submitted_at": _cell_text(fields.get("申请时间") or fields.get("提交时间")),
            }
        )
    return result
