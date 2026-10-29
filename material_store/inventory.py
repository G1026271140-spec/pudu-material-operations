"""Reviewable field contracts generated from the exported schema and current UI.

Shipping template and schedule are intentionally excluded by the user's scope.
The registry is a schema superset: operational fields are mirrored but are not
presented as arbitrary user-editable business values.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re

from .field_registry import READ_ONLY_TYPES, TYPE_NAMES, edit_mode, postgres_type, table_column_names

TABLE_PAGES = {
    "物料主数据": ["普通物料申请", "配货工作台", "采购补库", "品类/型号/语种管理"],
    "文化周边管理库存": ["文化周边申请", "配货工作台", "品类/型号/战区管理"],
    "物料申请单": ["普通物料申请", "文化周边申请", "企业文化衫申请", "配货工作台"],
    "申请明细": ["普通物料申请", "文化周边申请", "企业文化衫申请", "配货工作台"],
    "物料品类": ["申领品类卡片", "品类管理", "采购补库"],
    "产品型号": ["普通物料申请", "型号管理", "品类管理"],
    "物料语种": ["普通物料申请", "语种管理", "品类管理"],
    "战区管理": ["文化周边申请", "战区管理", "品类管理"],
    "用户权限表": ["登录权限", "管理员入口", "个人申领额度"],
    "文化周边编码及库存数量": ["企业文化衫申请"],
    "企业文化衫行政源表": ["企业文化衫申请"],
    "文化周边兑换": ["企业文化衫申请结果"],
}

# The browser keys refer to normalized API results. Source alternatives are
# recorded together when the existing code selects from a linked record/fallback.
FUNCTIONS = {
    "parse_feishu_inventory_record": ["物料主数据"],
    "feishu_category_records_from_rows": ["物料品类"],
    "load_feishu_request_records": ["物料申请单"],
    "load_feishu_request_line_records": ["申请明细", "物料主数据", "物料品类"],
    "load_cultural_dimension_inventory_records": ["文化周边管理库存"],
    "corporate_apparel_catalog": ["企业文化衫行政源表", "文化周边编码及库存数量"],
}

WIDGETS = {1: "文本", 2: "数字", 3: "单选下拉", 4: "多选", 5: "日期时间", 7: "复选框",
           11: "人员选择", 13: "电话", 15: "链接及显示文字", 17: "附件新增/替换/移除",
           18: "关联记录选择", 21: "关联记录选择", 22: "地理位置", 23: "群组选择"}

SOURCE_OVERRIDES = {
    ("load_feishu_request_records", "requester"): [("物料申请单", "申请人")],
    # The existing apparel builder displays attachments from the synced row,
    # while stock comes from the administrative source row when supplied.
    ("corporate_apparel_catalog", "images"): [("文化周边编码及库存数量", "图片")],
}


def policy(table, field):
    name, kind = field["field_name"], int(field["type"])
    if table == "物料申请单" and name in {"待核实标签", "待核实备注"}:
        return "仅管理员配货台跟进；不触发库存核实、审批或通知"
    if kind in READ_ONLY_TYPES:
        return "源字段编辑" if kind in {19, 20} else "系统生成"
    if table in {"后台任务队列", "后台任务载荷", "后台任务节点列表", "库存流水", "申请物料变更记录表"}:
        return "内部流程写入；只提供业务状态及审计展示"
    if table == "用户权限表":
        return "管理员授权管理；额度通过申领/撤销流程累计"
    if table in {"物料申请单", "申请明细", "文化周边兑换", "物料下单批次", "物料下单批次明细"}:
        return "申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验"
    if table == "文化周边编码及库存数量":
        return "行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新"
    if table == "企业文化衫行政源表":
        return "具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新"
    if name in {"当前库存", "在途库存"}:
        return "管理员库存调整/补库/配货；同时记录库存流水"
    if kind in {18, 21}:
        return "管理员选择关联记录；通过对应业务服务维护双向关联"
    return "管理员编辑"


def constants(module):
    result = {}
    for node in module.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = value
    return result


def source_names(value, const, assignments=None, seen=None):
    names = []
    assignments = assignments or {}
    seen = set() if seen is None else seen
    def strings(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [s for item in node.elts for s in strings(item)]
        if isinstance(node, ast.Name):
            v = const.get(node.id)
            return [v] if isinstance(v, str) else list(v) if isinstance(v, (list, tuple)) else []
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "list" and node.args:
            return strings(node.args[0])
        return []
    for child in ast.walk(value):
        if isinstance(child, ast.Name) and child.id in assignments and child.id not in seen:
            names.extend(source_names(assignments[child.id], const, assignments, seen | {child.id}))
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id.startswith("feishu_") and len(child.args) > 1:
                names.extend(strings(child.args[1]))
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "get":
            if isinstance(child.func.value, ast.Name) and child.func.value.id in {"fields", "material_fields", "synced_fields"} and child.args:
                names.extend(strings(child.args[0]))
    return list(dict.fromkeys(names))


def build(snapshot, source_root):
    module = ast.parse((source_root / "app.py").read_text(encoding="utf-8-sig"))
    const = constants(module)
    by_name = {(t.get("display_name") or t["table_name"]): t for t in snapshot["tables"]}
    contracts = []
    for table in snapshot["tables"]:
        for field in table["fields"]:
            display_name = table.get("display_name") or table["table_name"]
            sql_table, sql_column = table_column_names(table["table_id"], field["field_id"])
            prop = field.get("property") or {}
            expression = prop.get("formula_expression") or prop.get("formula", "")
            refs = [{"table_id": t, "field_id": f} for t, f in
                    re.findall(r"\$table\[(tbl\w+)\]\.\$field\[(fld\w+)\]", expression)]
            if int(field["type"]) == 19 and prop.get("target_field"):
                target = (prop.get("filter_info") or {}).get("target_table")
                if target:
                    refs.append({"table_id": target, "field_id": prop["target_field"]})
            contracts.append({"source": table.get("source", "primary"), "table_name": table["table_name"],
                "table_id": table["table_id"], "field_name": field["field_name"], "field_id": field["field_id"],
                "display_table_name": display_name,
                "feishu_type": int(field["type"]), "ui_type": field.get("ui_type"),
                "sql_table": "material_data." + sql_table, "sql_column": sql_column,
                "sql_type": postgres_type(int(field["type"])), "pages": ["配货工作台"] if display_name == "物料申请单" and field["field_name"] in {"待核实标签", "待核实备注"} else TABLE_PAGES.get(display_name, []),
                "edit_mode": edit_mode(field), "widget": WIDGETS.get(int(field["type"]), "显示及源字段入口"),
                "permission_and_write_path": policy(display_name, field),
                "options": [x["name"] for x in prop.get("options", [])],
                "linked_table_id": prop.get("table_id"), "multiple": prop.get("multiple"),
                "source_fields": refs, "daily_authority": "feishu", "normal_authority": "postgresql"})
    bindings = []
    for node in module.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in FUNCTIONS:
            continue
        seen = set()
        assignments = {}
        for assignment in ast.walk(node):
            if isinstance(assignment, ast.Assign):
                for target in assignment.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = assignment.value
            elif isinstance(assignment, ast.AnnAssign) and isinstance(assignment.target, ast.Name) and assignment.value is not None:
                assignments[assignment.target.id] = assignment.value
        for d in ast.walk(node):
            if not isinstance(d, ast.Dict):
                continue
            for key, value in zip(d.keys, d.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or key.value in seen:
                    continue
                seen.add(key.value)
                names = source_names(value, const, assignments)
                sources = [{"table_id": by_name[t]["table_id"], "field_id": f["field_id"],
                            "table_name": by_name[t]["table_name"], "source": by_name[t].get("source", "primary"), "field_name": f["field_name"]}
                           for t in FUNCTIONS[node.name] for f in by_name[t]["fields"] if f["field_name"] in names]
                if (node.name, key.value) in SOURCE_OVERRIDES:
                    sources = [{"table_id": by_name[t]["table_id"], "table_name": by_name[t]["table_name"],
                                "field_id": f["field_id"], "field_name": name, "source": by_name[t].get("source", "primary")}
                               for t, name in SOURCE_OVERRIDES[(node.name, key.value)]
                               for f in by_name[t]["fields"] if f["field_name"] == name]
                mode = "字段或关联来源" if sources else "系统标识/派生值"
                if key.value == "record_id":mode = "记录 ID，系统生成"
                elif key.value in {"products", "items"}:mode = "列表容器，字段见每个记录的对应关系"
                elif node.name == "load_cultural_dimension_inventory_records" and key.value in {"status", "request_visible"}:
                    mode = "共享编辑器固定默认值；实际启用/可见性在品类表维护"
                elif node.name == "load_feishu_request_records" and key.value == "position":
                    mode = "兼容占位值；当前表无岗位/职位字段，现有页面未提供此输入"
                elif node.name == "load_feishu_request_line_records" and key.value == "usage" and not sources:
                    mode = "兼容占位值；申请用途实际保存在所属申请单的物料用途字段"
                elif isinstance(value, ast.BinOp):mode = "派生值，编辑所列来源字段"
                bindings.append({"builder": node.name, "api_key": key.value, "sources": sources,
                    "mode": mode,
                    "code_line": d.lineno})
    for kind, table_name, names in [
        ("model", "产品型号", {"name": "产品型号", "code": "产品型号编码", "zh_page_name": "中文页面名称", "en_page_name": "英文页面名称", "product_line": "产品线", "model_type": "型号类型", "status": "启用状态"}),
        ("language", "物料语种", {"name": "语言种类", "zh_page_name": "语言种类", "en_page_name": "语言种类", "status": "启用状态"}),
        ("region", "战区管理", {"name": "战区名称", "zh_page_name": "战区名称", "en_page_name": "战区名称", "status": "启用状态"}),
        ("category", "物料品类", {"images": "申领页图片"}),
    ]:
        for api_key, name in names.items():
            table = by_name[table_name]
            field = next(f for f in table["fields"] if f["field_name"] == name)
            bindings.append({"builder": "dimension_management_records" if kind != "category" else "request_web.api._management_snapshot",
                "api_key": kind + "." + api_key, "sources": [{"table_id": table["table_id"], "table_name": table_name,
                "field_id": field["field_id"], "field_name": name, "source": "primary"}], "mode": "字段或关联来源"})
    for api_key, name in [("reviewLabel", "待核实标签"), ("reviewNote", "待核实备注")]:
        table = by_name["物料申请单"]
        field = next(f for f in table["fields"] if f["field_name"] == name)
        bindings.append({"builder": "material_store.pending_followup.summary", "api_key": api_key,
            "sources": [{"table_id": table["table_id"], "field_id": field["field_id"], "field_name": name,
                "table_name": table["table_name"], "source": "primary"}], "mode": "字段或关联来源"})
    return {"schema_exported_at": snapshot["exported_at"], "excluded_pages": ["发货模板", "发货排期"],
            "fields": contracts, "api_bindings": bindings}


def write_inventory(root: Path):
    snapshot = json.loads((root / "config/feishu_field_registry.json").read_text(encoding="utf-8-sig"))
    data = build(snapshot, root)
    (root / "config/frontend_field_contracts.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 业务字段、编辑选项与飞书映射", "", "生成依据：当前 React/FastAPI 代码及应用身份导出的实际飞书字段元数据。",
             "", "发货模板、发货排期按用户要求保持现状，不创建字段定义。以下为主业务表的完整数据库映射，含关联/流程字段，不能将所有流程字段作为普通输入框直接覆盖。",
             "", f"共 {len(snapshot['tables'])} 张来源表、{len(data['fields'])} 个字段（分别注册主业务库及企业文化衫行政源表）。每个字段均保留稳定字段 ID、类型化 SQL 列和原始 JSON 值。",
             "", "具体页面的业务输入、派生值和权限规则见 [页面字段说明](frontend-edit-contract.md)。机器可读定义为 config/frontend_field_contracts.json。", ""]
    for table in snapshot["tables"]:
        lines.extend(["## " + (table.get("display_name") or table["table_name"]), "", "来源：`" + table.get("source", "primary") + "`；实际表名：" + table["table_name"] + "；表 ID：`" + table["table_id"] + "`。",
                      "", "| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |", "|---|---|---|---|"])
        for field in [f for f in data["fields"] if f["table_id"] == table["table_id"]]:
            choices = "；选项：" + "、".join(field["options"]) if field["options"] else ""
            label = field["field_name"].replace("|", "\\|")
            lines.append(f"| {label} | `{field['field_id']}` / `{field['sql_column']}` | {TYPE_NAMES.get(field['feishu_type'],field['feishu_type'])} / {field['sql_type']} | {field['widget']}；{field['permission_and_write_path']}{choices} |")
        lines.append("")
    (root / "docs/frontend-field-map.md").write_text("\n".join(lines), encoding="utf-8")
    return {"tables": len(snapshot["tables"]), "fields": len(data["fields"]), "api_bindings": len(data["api_bindings"])}


if __name__ == "__main__":
    print(json.dumps(write_inventory(Path(__file__).resolve().parents[1])))
