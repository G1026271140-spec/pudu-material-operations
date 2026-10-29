"""Scheduling I/O, invoked only from the existing authenticated UI / queue Worker.

The original inventory-review handler is deliberately not reused: saving a plan
must not confirm inventory, approve an application, or populate issued quantities.
"""
from __future__ import annotations

from datetime import datetime
import json
import uuid

import order_scheduling as rules


class SchedulingService:
    def __init__(self, app):
        self.app = app

    @property
    def tables(self):
        a = self.app
        return (a.REQUEST_TABLE_NAME, a.REQUEST_LINE_TABLE_NAME, a.MATERIAL_TABLE_NAME,
                a.CATEGORY_TABLE_NAME, a.MODEL_TABLE_NAME, a.LANGUAGE_TABLE_NAME,
                a.USER_PERMISSION_TABLE_NAME, rules.BATCH_TABLE, rules.DETAIL_TABLE)

    def validate_schema(self):
        a = self.app
        if hasattr(a, "ensure_order_scheduling_fields"):
            a.ensure_order_scheduling_fields()
        schema = a.feishu_schema()
        full = {name: dict(value) for name, value in schema.get("tables", {}).items()}
        for table in rules.SCHEMA:
            if table not in full:
                continue
            fields = a.feishu_client().list_fields(full[table]["table_id"])
            full[table]["fields"] = {f["field_name"]: f for f in fields}
        errors = rules.schema_errors(full)
        if errors:
            raise ValueError("下单排期字段校验未通过：\n" + "\n".join(errors))
        return True

    def snapshot(self, *, live=False):
        read = self.app.fresh_feishu_rows if live else self.app.page_data_cache_rows
        return {table: read(table) for table in self.tables}

    def roles(self, requester_id, rows=None):
        a = self.app
        if not str(requester_id).startswith("ou_"):
            raise ValueError("请选择有效的申请人，才能核对申请时效权限。")
        roles = set()
        for row in rows if rows is not None else a.fresh_feishu_rows(a.USER_PERMISSION_TABLE_NAME):
            fields = a.feishu_fields(row)
            if requester_id in a.feishu_person_open_ids(fields, ["用户账号"]) and a.feishu_permission_enabled(fields):
                roles.update(a.feishu_choice_values(fields, "角色"))
        return sorted(roles or {"销售"})

    def request_dates(self, payload, *, submitted=None):
        return rules.calculate_dates(
            payload.get("arrival_start"), payload.get("arrival_end"), str(payload.get("request_reason") or ""),
            self.roles(payload.get("requester_open_id")),
            submitted=submitted or rules.today(),
        )

    def require_admin(self, operator):
        if operator not in self.app.enabled_admin_open_ids():
            raise PermissionError("只有已启用的管理员可以执行下单排期操作。")

    def index(self, rows):
        return {self.app.feishu_record_id(row): row for row in rows}

    def catalog(self, snapshot, *, include_ids=()):
        a = self.app
        categories = self.index(snapshot[a.CATEGORY_TABLE_NAME])
        category_by_name = {a.feishu_text(a.feishu_fields(r), "物料品类"): r for r in categories.values()}
        material_rows = a.material_rows_with_dimension_model_names(snapshot[a.MATERIAL_TABLE_NAME], snapshot[a.MODEL_TABLE_NAME])
        result = {}
        for row in material_rows:
            mid, fields = a.feishu_record_id(row), a.feishu_fields(row)
            product = a.feishu_text(fields, "物料品类")
            cids = a.feishu_link_ids_any(fields, ["品类关联"])
            category = categories.get(cids[0], {}) if cids else category_by_name.get(product, {})
            cf = a.feishu_fields(category)
            if a.feishu_text(cf, "品类定义") == a.CATEGORY_DEFINITION_CULTURAL:
                continue
            if not product or (a.feishu_text(fields, "启用状态") == "停用" and mid not in include_ids):
                continue
            result[mid] = {
                "material_id": mid, "product": product,
                "category": a.feishu_text(cf, "中文页面名称") or product,
                "model": a.feishu_text(fields, "产品型号") or a.NO_MODEL_TEXT,
                "language": a.feishu_text(fields, "语种") or a.NO_LANGUAGE_TEXT,
                "unit_price": a.feishu_float(cf, a.UNIT_PRICE_RMB_FIELD),
                "stock": a.feishu_int(fields, "当前库存"), "row": row,
            }
        return result

    def grouped_requests(self, snapshot):
        a = self.app
        raw_lines = snapshot[a.REQUEST_LINE_TABLE_NAME]
        material_ids = {mid for r in raw_lines for mid in a.feishu_link_ids_any(a.feishu_fields(r), ["物料编码", "物料"])}
        catalog = self.catalog(snapshot, include_ids=material_ids)
        groups = {}
        for row in snapshot[a.REQUEST_TABLE_NAME]:
            fields = a.feishu_fields(row)
            if not rules.ordinary_request(fields) or not a.feishu_text(fields, "申请单号"):
                continue
            rid = a.feishu_record_id(row)
            groups[rid] = {"id": rid, "fields": fields, "lines": [], "generated": False, "reserved_keys": set(),
                           "request_no": a.feishu_text(fields, "申请单号"),
                           "requester": a.request_applicant_text(fields),
                           "usage": a.feishu_text(fields, "物料用途"),
                           "status": a.feishu_text(fields, "审批状态")}
        for row in raw_lines:
            f = a.feishu_fields(row)
            for rid in a.feishu_link_ids_any(f, ["所属申请单", "申请单"]):
                if rid not in groups:
                    continue
                if a.feishu_text(f, rules.GENERATED) == "已生成":
                    groups[rid]["generated"] = True
                mids = a.feishu_link_ids_any(f, ["物料编码", "物料"])
                mid = mids[0] if len(mids) == 1 else ""
                item = catalog.get(mid, {})
                groups[rid]["lines"].append({
                    "id": a.feishu_record_id(row), "material_id": mid,
                    "category": item.get("category") or a.feishu_text(f, "品类名称"),
                    "model": item.get("model") or a.feishu_text(f, "产品型号名称"),
                    "language": item.get("language") or a.feishu_text(f, "语种名称"),
                    "quantity": a.feishu_int(f, "申请数量"), "remark": a.feishu_text(f, "备注"),
                    "status": a.feishu_text(f, "明细状态"), "fields": f,
                })
        batches = self.index(snapshot[rules.BATCH_TABLE])
        for row in snapshot[rules.DETAIL_TABLE]:
            f = a.feishu_fields(row)
            bids = a.feishu_link_ids(f, "所属下单批次")
            if any(a.feishu_text(a.feishu_fields(batches.get(bid, {})), "批次状态") in {"已生成", "已作废"} for bid in bids):
                for rid in a.feishu_link_ids(f, "来源申请单"):
                    if rid in groups:
                        groups[rid]["generated"] = True
            for bid in bids:
                bf = a.feishu_fields(batches.get(bid, {}))
                if a.feishu_text(bf, "批次状态") in {"生成中", "生成失败"}:
                    for rid in a.feishu_link_ids(f, "来源申请单"):
                        if rid in groups:
                            groups[rid]["reserved_keys"].add(a.feishu_text(bf, "生成幂等键"))
        for group in groups.values():
            group["fingerprint"] = rules.fingerprint({"fields": group["fields"], "lines": sorted(group["lines"], key=lambda r: r["id"])})
        return groups

    def check_group(
        self,
        group,
        expected=None,
        *,
        editing=False,
        generation_key="",
        check_fingerprint=True,
        authoritative=False,
    ):
        a = self.app
        if not group:
            raise ValueError("申请单不存在，或不是普通物料申请。")
        if check_fingerprint and group["fingerprint"] != expected:
            raise ValueError("申请内容已变化，请刷新后重新选择，避免覆盖他人的修改。")
        if group["generated"] and not editing:
            raise ValueError("该申请单已有明细生成过下单表，不能重复生成或直接覆盖明细。")
        if group.get("reserved_keys", set()) - {generation_key}:
            raise ValueError("此申请有未完成的下单批次，请先恢复原任务，不能另建批次或覆盖明细。")
        if not authoritative and group["status"] in {"已撤回", "已驳回", "已拒绝", "已取消", "已发放", "已完成", "审批拒绝"}:
            raise ValueError("申请已撤回、驳回或发放，不能执行此操作。")
        if not authoritative and editing and (group["status"] != a.REQUEST_STATUS_PENDING or
                                               a.feishu_text(group["fields"], "库存审查状态") != a.INVENTORY_REVIEW_PENDING):
            raise ValueError("只允许编辑待审批、尚未完成库存核实的申请；已锁定申请保留现有处理流程。")
        if any(a.feishu_int(line["fields"], "实际发放数量") > 0 or
               a.feishu_link_ids(line["fields"], "出库流水") for line in group["lines"]):
            # Existing review may reserve issued quantities before actual dispatch.
            # Never let a planning edit reset those quantities.
            if editing:
                raise ValueError("明细已有发放数量或出库关联，不能直接修改。")
        if any(a.feishu_link_ids(line["fields"], "出库流水") or line["status"] == "已发放" for line in group["lines"]):
            raise ValueError("申请已有发放记录，不能重复下单或改写。")

    def write(self, table, rid, fields):
        missing = set(fields) - set(self.app.feishu_table_fields(table))
        if missing:
            raise ValueError(f"{table}缺少写入字段：{'、'.join(sorted(missing))}；未执行写入。")
        return self.app.feishu_update_record_fields(table, rid, fields)

    def sync_request_schedule_dates(self, request_id, request_fields, line_rows, detail_rows, batch_rows):
        date_fields = {
            rules.USAGE_DATE: request_fields.get(rules.USAGE_DATE),
            rules.ORDER_DATE: request_fields.get(rules.ORDER_DATE),
            rules.ARRIVAL_DATE: request_fields.get(rules.ARRIVAL_DATE),
            rules.SHIP_DATE: request_fields.get(rules.SHIP_DATE),
        }
        date_fields = {name: value for name, value in date_fields.items() if value not in (None, "")}
        if not date_fields:
            return 0
        updated = 0
        for row in line_rows:
            fields = self.app.feishu_fields(row)
            if request_id not in self.app.feishu_link_ids_any(fields, ["所属申请单", "申请单"]):
                continue
            writable = {
                name: value for name, value in date_fields.items()
                if name in self.app.feishu_table_fields(self.app.REQUEST_LINE_TABLE_NAME)
            }
            if writable:
                self.write(self.app.REQUEST_LINE_TABLE_NAME, self.app.feishu_record_id(row), writable)
                updated += 1
        for row in detail_rows:
            fields = self.app.feishu_fields(row)
            if request_id not in self.app.feishu_link_ids(fields, "来源申请单"):
                continue
            writable = {
                name: value
                for name, value in date_fields.items()
                if name in self.app.feishu_table_fields(rules.DETAIL_TABLE)
            }
            if rules.ARRIVAL_DATE in writable:
                arrival_value = writable.pop(rules.ARRIVAL_DATE)
                if rules.ARRIVAL_DATE in self.app.feishu_table_fields(rules.DETAIL_TABLE):
                    writable[rules.ARRIVAL_DATE] = arrival_value
                if rules.DETAIL_ARRIVAL_DATE in self.app.feishu_table_fields(rules.DETAIL_TABLE):
                    writable[rules.DETAIL_ARRIVAL_DATE] = arrival_value
            if writable:
                self.write(rules.DETAIL_TABLE, self.app.feishu_record_id(row), writable)
                updated += 1
        batch_ids = {
            bid
            for row in detail_rows
            if request_id in self.app.feishu_link_ids(self.app.feishu_fields(row), "来源申请单")
            for bid in self.app.feishu_link_ids(self.app.feishu_fields(row), "所属下单批次")
        }
        for row in batch_rows:
            if self.app.feishu_record_id(row) not in batch_ids:
                continue
            writable = {
                name: value for name, value in date_fields.items()
                if name in self.app.feishu_table_fields(rules.BATCH_TABLE)
            }
            if writable:
                self.write(rules.BATCH_TABLE, self.app.feishu_record_id(row), writable)
                updated += 1
        return updated

    def create(self, table, fields):
        missing = set(fields) - set(self.app.feishu_table_fields(table))
        if missing:
            raise ValueError(f"{table}缺少写入字段：{'、'.join(sorted(missing))}；未创建记录。")
        rows = self.app.feishu_batch_create_records(table, [fields])
        if len(rows) != 1:
            raise RuntimeError(f"{table}创建结果不完整。")
        return rows[0]

    def refresh(self):
        self.app.refresh_page_cache_tables(self.tables)

    def in_transit_totals(self, snapshot):
        """Derive ordered-but-not-stocked quantities from durable order details."""
        a = self.app
        batches = self.index(snapshot[rules.BATCH_TABLE])
        totals = {}
        for row in snapshot[rules.DETAIL_TABLE]:
            fields = a.feishu_fields(row)
            if a.feishu_text(fields, "补库状态") not in {"待补库", "补库异常"}:
                continue
            batch_ids = a.feishu_link_ids(fields, "所属下单批次")
            material_ids = a.feishu_link_ids(fields, "关联物料")
            if len(batch_ids) != 1 or len(material_ids) != 1:
                continue
            batch_fields = a.feishu_fields(batches.get(batch_ids[0], {}))
            if a.feishu_text(batch_fields, "批次状态") != "已生成":
                continue
            quantity = a.feishu_int(fields, "下单数量")
            if quantity > 0:
                material_id = material_ids[0]
                totals[material_id] = totals.get(material_id, 0) + quantity
        return totals

    def sync_in_transit_stock(self, snapshot=None):
        """Overwrite the material mirror from order details; never delta-update it."""
        a = self.app
        snapshot = snapshot or self.snapshot(live=True)
        totals = self.in_transit_totals(snapshot)
        updated = 0
        for row in snapshot[a.MATERIAL_TABLE_NAME]:
            material_id = a.feishu_record_id(row)
            target = totals.get(material_id, 0)
            if a.feishu_int(a.feishu_fields(row), rules.IN_TRANSIT_STOCK) != target:
                self.write(a.MATERIAL_TABLE_NAME, material_id, {rules.IN_TRANSIT_STOCK: target})
                updated += 1
        return updated

    def edit(self, payload, progress, checkpoint):
        """Fail closed after an uncertain write; do not replay a partial multi-record edit."""
        a = self.app
        self.require_admin(payload.get("operator_open_id"))
        self.validate_schema()
        if progress.get("write_done"):
            self.refresh()
            return progress
        if progress.get("edit_started"):
            raise RuntimeError("排期编辑曾中断，请先核对申请明细和变更记录；为避免重复增删，不自动重放。")
        snapshot = self.snapshot(live=True)
        group = self.grouped_requests(snapshot).get(payload.get("request_id"))
        # Once queued, the payload is the authoritative target state. Manual
        # edits to status/version fields must not invalidate the background
        # write; irreversible issue-ledger safeguards below remain enforced.
        self.check_group(
            group,
            editing=True,
            check_fingerprint=False,
            authoritative=True,
        )
        desired = list(payload.get("lines") or [])
        if not desired:
            raise ValueError("申请须至少保留1条明细。")
        note = str(payload.get("change_note") or "").strip()
        if not note:
            raise ValueError("请填写修改说明。")
        current = {line["id"]: line for line in group["lines"]}
        catalog = self.catalog(snapshot, include_ids={line["material_id"] for line in group["lines"]})
        seen_ids, seen_materials, prepared = set(), set(), []
        for line in desired:
            lid, mid, qty = line.get("id", ""), line.get("material_id"), line.get("quantity")
            if lid not in current or lid in seen_ids:
                lid = ""
            if mid not in catalog or mid in seen_materials:
                raise ValueError("物料组合不存在或重复，请刷新目录并合并同规格数量。")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > 1_000_000:
                raise ValueError("数量须为1～1000000之间的整数。")
            seen_ids.add(lid)
            seen_materials.add(mid)
            item = catalog[mid]
            fields = {"申请数量": qty, "备注": str(line.get("remark") or ""), "明细变更说明": note,
                      a.REQUEST_PRICE_SNAPSHOT_FIELD: item["unit_price"],
                      a.REQUEST_LINE_SUBTOTAL_FIELD: round(qty * item["unit_price"], 2)}
            a.set_request_line_material_fields(fields, item["row"], item["product"], item["model"], item["language"])
            # These fields belong to the existing allocation/dispatch workflow.
            fields = {k: v for k, v in fields.items() if not k.startswith("实际发放")}
            if not lid:
                fields.update({"明细编号": f"{group['request_no']}-P{uuid.uuid4().hex[:10]}",
                               "所属申请单": [group["id"]], "明细状态": a.REQUEST_LINE_STATUS_PENDING,
                               "原申请数量": str(qty), "提交时库存快照": str(item["stock"]),
                               "审批通过数量": qty, "实际发放数量": 0, "明细业务类型": "普通物料",
                               rules.GENERATED: "未生成"})
            prepared.append((lid, fields))
        # Require the audit schema already present; never run the old auto-create helper.
        audit_fields = a.feishu_table_fields(a.REQUEST_CHANGE_TABLE_NAME)
        for name in ("文本", "申请单号", "操作人OpenID", "操作时间", "变更说明", "变更前JSON", "变更后JSON", "变更版本"):
            if name not in audit_fields:
                raise ValueError(f"申请物料变更记录表缺少{name}，暂不能安全编辑。")
        request_updates = {}
        if payload.get("arrival_start"):
            role_ids = a.feishu_person_open_ids(group["fields"], ["申请人"])
            submitted = rules.as_date(group["fields"].get("提交时间"))
            if submitted is None:
                raise ValueError("原申请缺少提交时间，请先核实，不能伪造时效。")
            request_updates.update(self.request_dates({**payload, "requester_open_id": role_ids[0] if role_ids else ""}, submitted=submitted))
        version = a.feishu_int(group["fields"], "排期编辑版本") + 1
        progress["edit_started"] = True
        checkpoint(dict(progress))
        audit = self.create(a.REQUEST_CHANGE_TABLE_NAME, {
            "文本": f"排期-{group['request_no']}-{version}", "申请单号": group["request_no"],
            "操作人OpenID": payload["operator_open_id"], "操作时间": int(datetime.now(rules.CHINA_TZ).timestamp() * 1000),
            "变更说明": f"下单排期编辑（不确认库存）：{note}",
            "变更前JSON": json.dumps(group["lines"], ensure_ascii=False),
            "变更后JSON": json.dumps(desired, ensure_ascii=False), "变更版本": version,
        })
        progress["audit_id"] = a.feishu_record_id(audit)
        checkpoint(dict(progress))
        for lid, fields in prepared:
            self.write(a.REQUEST_LINE_TABLE_NAME, lid, fields) if lid else self.create(a.REQUEST_LINE_TABLE_NAME, fields)
        removed = set(current) - seen_ids
        if removed:
            a.feishu_batch_delete_record_ids(a.REQUEST_LINE_TABLE_NAME, sorted(removed))
        request_updates.update({"排期编辑版本": version,
                                "申请变更次数": str(a.feishu_int(group["fields"], "申请变更次数") + 1),
                                "物料明细文字信息": a.request_material_detail_text([
                                    {"product": catalog[line["material_id"]]["category"],
                                     "model": catalog[line["material_id"]]["model"],
                                     "language": catalog[line["material_id"]]["language"],
                                     "quantity": line["quantity"]} for line in desired]),
                                a.REQUEST_TOTAL_RMB_FIELD: round(sum(f[a.REQUEST_LINE_SUBTOTAL_FIELD] for _, f in prepared), 2)})
        self.write(a.REQUEST_TABLE_NAME, group["id"], request_updates)
        progress.update(write_done=True, request_no=group["request_no"])
        checkpoint(dict(progress))
        self.refresh()
        return progress

    def prepare_export(self, payload, snapshot, *, strict_request_fingerprint=True):
        """Pure preparation from a supplied snapshot; no network or Base writes."""
        groups = self.grouped_requests(snapshot)
        selections = list(payload.get("selections") or [])
        if not selections:
            raise ValueError("请选择至少一条下单明细。")
        catalog = self.catalog(snapshot, include_ids={l["material_id"] for g in groups.values() for l in g["lines"]})
        prepared, seen = [], set()
        for selection in selections:
            rid, lid = selection.get("request_id"), selection.get("line_id")
            group = groups.get(rid)
            expected = dict(payload.get("fingerprints") or {}).get(rid)
            if not strict_request_fingerprint and group:
                expected = group["fingerprint"]
            self.check_group(group, expected,
                             generation_key=str(payload.get("generation_key") or ""))
            lines = {line["id"]: line for line in group["lines"]}
            if lid not in lines or lid in seen:
                raise ValueError("选择的明细不属于申请单或存在重复。")
            seen.add(lid)
            line = lines[lid]
            if line["status"] in {"已撤回", "已取消", "已发放"} or line["material_id"] not in catalog:
                raise ValueError("所选明细已失效或未关联有效物料。")
            item = catalog[line["material_id"]]
            if line["quantity"] <= 0:
                raise ValueError("下单数量必须大于零。")
            planned = rules.validate_planned_receipt(selection.get("planned_date"), now=rules.today(),
                                                     confirmed_arrived=selection.get("confirmed_arrived") is True)
            prepared.append({"request_id": rid, "line_id": lid, "material_id": line["material_id"],
                "category": item["category"], "model": item["model"], "language": item["language"],
                "quantity": line["quantity"], "usage": group["usage"], "remark": line["remark"],
                "planned_date": planned.isoformat(), "confirmed_arrived": selection.get("confirmed_arrived") is True,
                "usage_date": group["fields"].get(rules.USAGE_DATE),
                "order_date": group["fields"].get(rules.ORDER_DATE),
                "arrival_date": group["fields"].get(rules.ARRIVAL_DATE),
                "ship_date": group["fields"].get(rules.SHIP_DATE)})
        return prepared

    def record_schedule(self, payload, progress, checkpoint):
        """Persist scheduling records only. XLSX construction belongs to the page."""
        a = self.app
        self.require_admin(payload.get("operator_open_id"))
        self.validate_schema()
        if progress.get("write_done"):
            self.refresh()
            return progress
        snapshot = self.snapshot(live=True)
        key = str(payload.get("generation_key") or "")
        if not key:
            raise ValueError("下单批次生成幂等键不能为空。")
        found = [r for r in snapshot[rules.BATCH_TABLE] if a.feishu_text(a.feishu_fields(r), "生成幂等键") == key]
        if len(found) > 1:
            raise ValueError("检测到重复生成幂等键，请管理员核对，不能继续生成。")
        batch = found[0] if found else None
        if batch and a.feishu_text(a.feishu_fields(batch), "批次状态") == "已作废":
            raise ValueError("此下单批次已作废。")
        if batch and a.feishu_text(a.feishu_fields(batch), "批次状态") == "已生成":
            # Final status is a commit marker: repair source flags after interrupted completion.
            bid = a.feishu_record_id(batch)
            for row in snapshot[rules.DETAIL_TABLE]:
                f = a.feishu_fields(row)
                if bid in a.feishu_link_ids(f, "所属下单批次"):
                    for lid in a.feishu_link_ids(f, "来源申请明细"):
                        self.write(a.REQUEST_LINE_TABLE_NAME, lid, {rules.GENERATED: "已生成"})
            self.sync_in_transit_stock()
            progress.update(write_done=True, batch_id=bid)
            checkpoint(dict(progress))
            self.refresh()
            return progress
        if progress.get("generation_started") and not batch:
            raise RuntimeError("上次创建批次结果不明确，请核对后再恢复；不会盲目新建重复批次。")
        groups = self.grouped_requests(snapshot)
        selections = list(payload.get("selections") or [])
        if not selections:
            raise ValueError("请选择至少一条下单明细。")
        prepared = []
        if progress.get("prepared"):
            prepared = list(progress["prepared"])
            # A partial export resumes its frozen values, but never ignores canceled sources.
            for item in prepared:
                g = groups.get(item["request_id"])
                expected = payload["fingerprints"].get(item["request_id"])
                if "export_rows" in payload and g:
                    expected = g["fingerprint"]
                self.check_group(g, expected, generation_key=key)
        else:
            prepared = self.prepare_export(payload, snapshot,
                                           strict_request_fingerprint="export_rows" not in payload)
            progress["prepared"] = prepared
            checkpoint(dict(progress))
        for item in prepared:
            rules.validate_planned_receipt(item["planned_date"], now=rules.today(), confirmed_arrived=item["confirmed_arrived"])
        if "export_rows" in payload and rules.fingerprint(payload["export_rows"]) != rules.fingerprint(prepared):
            raise ValueError("下载明细与最新申请不一致，请刷新并重新生成；未登记批次。")
        if not batch:
            progress["generation_started"] = True
            checkpoint(dict(progress))
            batch_fields = {
                "下单批次号": rules.batch_number(key), "批次状态": "生成中",
                "生成幂等键": key, "生成人": [{"id": payload["operator_open_id"]}],
                "生成时间": int(datetime.now(rules.CHINA_TZ).timestamp() * 1000),
                # Arm only after every batch line is durably saved.
                "启用自动补库": False, "批次备注": str(payload.get("note") or ""),
            }
            for field_name, item_key in ((rules.USAGE_DATE, "usage_date"), (rules.ORDER_DATE, "order_date"),
                                         (rules.ARRIVAL_DATE, "arrival_date"), (rules.SHIP_DATE, "ship_date")):
                values = {item.get(item_key) for item in prepared if item.get(item_key) not in (None, "")}
                if len(values) == 1:
                    batch_fields[field_name] = next(iter(values))
            batch = self.create(rules.BATCH_TABLE, batch_fields)
        bid = a.feishu_record_id(batch)
        existing_details = {a.feishu_text(a.feishu_fields(r), rules.RESTOCK_KEY): r for r in snapshot[rules.DETAIL_TABLE]}
        for item in prepared:
            line_key = f"order:{key}:{item['line_id']}"
            if line_key in existing_details:
                continue
            # An uncertain create is not repeated until its key has been observed on reread.
            if progress.get("creating_line") == line_key:
                raise RuntimeError("批次明细创建结果待核对，暂停重复创建。")
            progress["creating_line"] = line_key
            checkpoint(dict(progress))
            self.create(rules.DETAIL_TABLE, {
                "批次明细编号": line_key, "所属下单批次": [bid], "来源申请单": [item["request_id"]],
                "来源申请明细": [item["line_id"]], "关联物料": [item["material_id"]],
                "品类名称快照": item["category"], "型号或尺码快照": item["model"], "语种快照": item["language"],
                "下单数量": item["quantity"], "申请用途快照": item["usage"], "明细备注快照": item["remark"],
                rules.USAGE_DATE: item.get("usage_date"), rules.ORDER_DATE: item.get("order_date"),
                rules.ARRIVAL_DATE: item.get("arrival_date"),
                rules.DETAIL_ARRIVAL_DATE: rules.date_ms(item["planned_date"]),
                rules.SHIP_DATE: item.get("ship_date") or (rules.date_ms(item["planned_date"]) if item["confirmed_arrived"] else None),
                rules.FULFILLMENT_STATUS: "已到货" if item["confirmed_arrived"] else "已下单",
                "补库状态": "待补库",
                rules.RESTOCK_KEY: line_key,
                "补库异常说明": "管理员已确认制作完成并到仓" if item["confirmed_arrived"] else "",
            })
            progress.pop("creating_line", None)
            checkpoint(dict(progress))
        # Re-read all saved detail keys before marking the batch complete. Never
        # publish a partial export as successful if a provider dropped a record.
        saved = [a.feishu_fields(row) for row in a.fresh_feishu_rows(rules.DETAIL_TABLE)
                 if bid in a.feishu_link_ids(a.feishu_fields(row), "所属下单批次")]
        saved_keys = [a.feishu_text(f, rules.RESTOCK_KEY) for f in saved]
        expected_keys = {f"order:{key}:{item['line_id']}" for item in prepared}
        if set(saved_keys) != expected_keys or len(saved_keys) != len(expected_keys):
            raise RuntimeError("批次明细写入尚未完整确认，暂不标记生成成功、不启用补库。")
        self.write(rules.BATCH_TABLE, bid, {"批次状态": "已生成", "启用自动补库": True})
        for item in prepared:
            self.write(a.REQUEST_LINE_TABLE_NAME, item["line_id"], {rules.GENERATED: "已生成"})
        self.sync_in_transit_stock()
        progress.update(write_done=True, batch_id=bid)
        checkpoint(dict(progress))
        self.refresh()
        return progress

    def generate(self, payload, progress, checkpoint):
        """Backward-compatible method name; does not generate a workbook."""
        return self.record_schedule(payload, progress, checkpoint)

    def due_details(self, snapshot, *, now=None):
        a = self.app
        now = now or rules.today()
        batches = self.index(snapshot[rules.BATCH_TABLE])
        requests = self.index(snapshot[a.REQUEST_TABLE_NAME])
        result = []
        for row in snapshot[rules.DETAIL_TABLE]:
            f = a.feishu_fields(row)
            if a.feishu_text(f, "补库状态") != "待补库" or not a.feishu_text(f, rules.RESTOCK_KEY):
                continue
            bids = a.feishu_link_ids(f, "所属下单批次")
            rids = a.feishu_link_ids(f, "来源申请单")
            mids = a.feishu_link_ids(f, "关联物料")
            if len(bids) != 1 or len(rids) != 1 or len(mids) != 1 or a.feishu_link_ids(f, "关联文化周边库存"):
                continue
            bf = a.feishu_fields(batches.get(bids[0], {}))
            if a.feishu_text(bf, "批次状态") != "已生成" or bf.get("启用自动补库") is not True:
                continue
            if not rules.ordinary_request(a.feishu_fields(requests.get(rids[0], {}))):
                continue
            planned, generated = rules.as_date(f.get(rules.DETAIL_ARRIVAL_DATE)), rules.as_date(bf.get("生成时间"))
            if planned is None or generated is None or planned > now or a.feishu_int(f, "下单数量") <= 0:
                continue
            # Old dates entered directly in Base must not silently backfill inventory.
            if planned < generated and a.feishu_text(f, "补库异常说明") != "管理员已确认制作完成并到仓":
                continue
            result.append(row)
        return result

    def enqueue_due(self):
        from submission_queue import QUEUE_TASK_TYPE_ORDER_RESTOCK, QUEUE_STATUS_COMPLETED, find_task_by_idempotency_key
        snapshot = self.snapshot(live=True)
        # The due scanner is also the reconciliation loop for manual Base edits
        # to quantities, cancellation state, or batch status.
        self.sync_in_transit_stock(snapshot)
        count = 0
        for row in self.due_details(snapshot):
            key = self.app.feishu_text(self.app.feishu_fields(row), rules.RESTOCK_KEY)
            task_key = f"schedule-restock:{key}"
            # A job can become ineligible between enqueue and execution (pause or
            # postponement). Once eligible again, start a new attempt only after a
            # provably skipped, completed job. Active/failed/uncertain writes must
            # retain their original journal and must never be automatically reset.
            for _ in range(100):
                previous = find_task_by_idempotency_key(self.app.feishu_client(), task_key)
                if previous is None:
                    break
                if (previous.status != QUEUE_STATUS_COMPLETED or not previous.result.get("skipped") or
                        previous.result.get("stock_write_started") or previous.result.get("write_done")):
                    task_key = ""
                    break
                task_key = f"schedule-restock:{key}:after:{previous.task_id}"
            else:
                raise RuntimeError("补库任务改期次数过多，请核对任务历史后恢复。")
            if not task_key:
                continue
            _, created = self.app.enqueue_feishu_background_write(QUEUE_TASK_TYPE_ORDER_RESTOCK,
                {"detail_id": self.app.feishu_record_id(row)}, task_key)
            count += int(created)
        return count

    def plan(self, payload, progress, checkpoint):
        a = self.app
        self.require_admin(payload.get("operator_open_id"))
        self.validate_schema()
        if progress.get("write_done"):
            self.refresh()
            return progress
        snapshot = self.snapshot(live=True)
        action = payload.get("action")
        if action == "batch_edit":
            edits = list(payload.get("edits") or [])
            refreshed_requests = set()
            for edit in edits:
                edit_payload = {**edit, "operator_open_id": payload.get("operator_open_id")}
                request_id = str(edit_payload.get("request_id") or "")
                if request_id and request_id in refreshed_requests:
                    current_group = self.grouped_requests(self.snapshot(live=True)).get(request_id)
                    if current_group:
                        edit_payload["expected_fingerprint"] = current_group["fingerprint"]
                self.plan(edit_payload, {}, checkpoint)
                if request_id:
                    refreshed_requests.add(request_id)
            progress["write_done"] = True
            checkpoint(dict(progress))
            self.refresh()
            return progress
        if action == "request_dates":
            group = self.grouped_requests(snapshot).get(payload.get("request_id"))
            if not group:
                raise ValueError("申请单不存在，或不是普通物料申请。")
            if group["status"] in {"已撤回", "已驳回", "已拒绝", "已取消", "已发放", "已完成", "审批拒绝"}:
                raise ValueError("申请已结束，不能修改申请日期。")
            f = group["fields"]
            submitted = rules.as_date(f.get("提交时间"))
            if submitted is None:
                raise ValueError("原申请没有提交时间，不能伪造时效。")
            ids = a.feishu_person_open_ids(f, ["申请人"])
            role_snapshot = a.feishu_text(f, "申请时角色快照")
            roles = role_snapshot.split("、") if role_snapshot else self.roles(ids[0] if ids else "")
            dates = rules.calculate_dates(payload.get("arrival_start"), payload.get("arrival_end"),
                str(payload.get("request_reason") or ""), roles, submitted=submitted)
            dates["排期编辑版本"] = a.feishu_int(f, "排期编辑版本") + 1
            self.write(a.REQUEST_TABLE_NAME, group["id"], dates)
            self.sync_request_schedule_dates(
                group["id"], {**f, **dates},
                snapshot[a.REQUEST_LINE_TABLE_NAME], snapshot[rules.DETAIL_TABLE],
                snapshot[rules.BATCH_TABLE],
            )
        elif action == "request_ship_date":
            group = self.grouped_requests(snapshot).get(payload.get("request_id"))
            if not group:
                raise ValueError("申请单不存在，或不是普通物料申请。")
            if group["status"] in {"已撤回", "已驳回", "已拒绝", "已取消", "已发放", "已完成"}:
                raise ValueError("申请已结束，不能修改发货日期。")
            ship_date = rules.as_date(payload.get("ship_date"))
            if ship_date is None:
                raise ValueError("请选择申请单发货日期。")
            ship_date_value = rules.date_ms(ship_date)
            self.write(a.REQUEST_TABLE_NAME, group["id"], {rules.SHIP_DATE: ship_date_value})
            for line_row in snapshot[a.REQUEST_LINE_TABLE_NAME]:
                line_fields = a.feishu_fields(line_row)
                if group["id"] in a.feishu_link_ids_any(line_fields, ["所属申请单", "申请单"]):
                    self.write(a.REQUEST_LINE_TABLE_NAME, a.feishu_record_id(line_row), {rules.SHIP_DATE: ship_date_value})
            for detail_row in snapshot[rules.DETAIL_TABLE]:
                detail_fields = a.feishu_fields(detail_row)
                if group["id"] in a.feishu_link_ids(detail_fields, "来源申请单"):
                    self.write(
                        rules.DETAIL_TABLE,
                        a.feishu_record_id(detail_row),
                        {rules.SHIP_DATE: ship_date_value},
                    )
            batch_ids = {
                bid
                for detail_row in snapshot[rules.DETAIL_TABLE]
                if group["id"] in a.feishu_link_ids(a.feishu_fields(detail_row), "来源申请单")
                for bid in a.feishu_link_ids(a.feishu_fields(detail_row), "所属下单批次")
            }
            for batch_row in snapshot[rules.BATCH_TABLE]:
                if a.feishu_record_id(batch_row) in batch_ids:
                    self.write(rules.BATCH_TABLE, a.feishu_record_id(batch_row), {rules.SHIP_DATE: ship_date_value})
        elif action == "batch_enabled":
            row = self.index(snapshot[rules.BATCH_TABLE]).get(payload.get("batch_id"), {})
            if a.feishu_text(a.feishu_fields(row), "批次状态") != "已生成":
                raise ValueError("仅有效已生成批次可调整自动补库开关。")
            self.write(rules.BATCH_TABLE, a.feishu_record_id(row), {"启用自动补库": payload.get("enabled") is True})
        elif action == "receipt_date":
            row = self.index(snapshot[rules.DETAIL_TABLE]).get(payload.get("detail_id"), {})
            f = a.feishu_fields(row)
            if not row:
                raise ValueError("下单批次明细不存在。")
            if a.feishu_text(f, "补库状态") not in {"待补库", "已取消"}:
                raise ValueError("明细正在补库、已补库或结果不明确，不能直接改期。")
            planned = rules.validate_planned_receipt(payload.get("planned_date"), now=rules.today(),
                                                     confirmed_arrived=payload.get("confirmed_arrived") is True)
            planned_value = rules.date_ms(planned)
            receipt_fields = {
                rules.DETAIL_ARRIVAL_DATE: planned_value,
                "补库异常说明": "管理员已确认制作完成并到仓" if payload.get("confirmed_arrived") is True else "",
            }
            if rules.ARRIVAL_DATE in a.feishu_table_fields(rules.DETAIL_TABLE):
                receipt_fields[rules.ARRIVAL_DATE] = planned_value
            self.write(rules.DETAIL_TABLE, a.feishu_record_id(row), receipt_fields)
        elif action == "fulfillment_update":
            row = self.index(snapshot[rules.DETAIL_TABLE]).get(payload.get("detail_id"), {})
            f = a.feishu_fields(row)
            if not row:
                raise ValueError("下单批次明细不存在。")
            status = str(payload.get("status") or "")
            allowed = {"待安排", "已下单", "制作中", "已发货", "已到货", "已完成", "无需下单", "已取消"}
            if status not in allowed:
                raise ValueError("无效的物料到货状态。")
            fields = {rules.FULFILLMENT_STATUS: status}
            restock_status = a.feishu_text(f, "补库状态")
            if status == "已取消" and restock_status not in {"已补库", "补库中"}:
                fields["补库状态"] = "已取消"
            elif status != "已取消" and restock_status == "已取消":
                fields["补库状态"] = "待补库"
            if payload.get("ship_date"):
                fields[rules.SHIP_DATE] = rules.date_ms(payload["ship_date"])
            if payload.get("arrival_date"):
                arrival_value = rules.date_ms(payload["arrival_date"])
                fields[rules.DETAIL_ARRIVAL_DATE] = arrival_value
                if rules.ARRIVAL_DATE in a.feishu_table_fields(rules.DETAIL_TABLE):
                    fields[rules.ARRIVAL_DATE] = arrival_value
                fields["补库异常说明"] = "管理员已确认制作完成并到仓" if status == "已到货" else ""
            self.write(rules.DETAIL_TABLE, a.feishu_record_id(row), fields)
            request_ids = a.feishu_link_ids(f, "来源申请单")
            if request_ids:
                lines = [a.feishu_fields(r) for r in snapshot[rules.DETAIL_TABLE]
                         if request_ids[0] in a.feishu_link_ids(a.feishu_fields(r), "来源申请单")]
                statuses = {a.feishu_text(line, rules.FULFILLMENT_STATUS) for line in lines}
                if statuses and statuses <= {"已到货", "已完成", "无需下单", "已取消"}:
                    self.write(a.REQUEST_TABLE_NAME, request_ids[0], {rules.FULFILLMENT_STATUS: "全部已到货"})
            self.sync_in_transit_stock()
        elif action == "fulfillment_bulk_update":
            detail_index = self.index(snapshot[rules.DETAIL_TABLE])
            line_index = self.index(snapshot[a.REQUEST_LINE_TABLE_NAME])
            for detail_id in payload.get("detail_ids") or []:
                row = detail_index.get(detail_id, {})
                table = rules.DETAIL_TABLE
                if not row:
                    row = line_index.get(detail_id, {})
                    table = a.REQUEST_LINE_TABLE_NAME
                f = a.feishu_fields(row)
                if not row:
                    continue
                status = str(payload.get("status") or "")
                fields = {rules.FULFILLMENT_STATUS: status}
                if table == rules.DETAIL_TABLE:
                    restock_status = a.feishu_text(f, "补库状态")
                    if status == "已取消" and restock_status not in {"已补库", "补库中"}:
                        fields["补库状态"] = "已取消"
                    elif status != "已取消" and restock_status == "已取消":
                        fields["补库状态"] = "待补库"
                if payload.get("ship_date"):
                    fields[rules.SHIP_DATE] = rules.date_ms(payload["ship_date"])
                if payload.get("arrival_date"):
                    arrival_value = rules.date_ms(payload["arrival_date"])
                    fields[rules.DETAIL_ARRIVAL_DATE] = arrival_value
                    if rules.ARRIVAL_DATE in a.feishu_table_fields(table):
                        fields[rules.ARRIVAL_DATE] = arrival_value
                self.write(table, detail_id, fields)
            self.sync_in_transit_stock()
        else:
            raise ValueError("未知排期操作。")
        progress["write_done"] = True
        checkpoint(dict(progress))
        self.refresh()
        return progress

    def restock(self, payload, progress, checkpoint):
        a = self.app
        self.validate_schema()
        snapshot = self.snapshot(live=True)
        rid = payload.get("detail_id")
        row = self.index(snapshot[rules.DETAIL_TABLE]).get(rid)
        if not row:
            raise ValueError("下单批次明细不存在。")
        f = a.feishu_fields(row)
        if a.feishu_text(f, "补库状态") == "已补库":
            self.sync_in_transit_stock(snapshot)
            return {**progress, "write_done": True, "detail_id": rid}
        key = a.feishu_text(f, rules.RESTOCK_KEY)
        if not key:
            raise ValueError("补库幂等键为空，禁止自动补库或按空键匹配流水。")
        ledgers = [r for r in a.fresh_feishu_rows(a.LEDGER_TABLE_NAME)
                   if a.feishu_text(a.feishu_fields(r), "幂等键") == key]
        if len(ledgers) > 1:
            raise ValueError("重复补库流水，请人工核对。")
        if ledgers:
            lf = a.feishu_fields(ledgers[0])
            if (a.feishu_link_ids(lf, "物料编码") != a.feishu_link_ids(f, "关联物料") or
                a.feishu_int(lf, "数量") != a.feishu_int(f, "下单数量") or
                a.feishu_text(lf, "操作状态") != "有效"):
                raise ValueError("已有同键流水与本次物料、数量或状态不一致，禁止重复补库。")
        if not ledgers and progress.get("stock_write_started") and not progress.get("stock_written"):
            self.write(rules.DETAIL_TABLE, rid, {"补库状态": "补库异常", "补库异常说明": "库存写入结果不明确，需核对库存及任务检查点；禁止盲目重试增加库存。"})
            raise RuntimeError("库存写入结果不明确，暂停自动补库，避免重复增加。")
        if not ledgers and not progress.get("stock_written") and rid not in {a.feishu_record_id(r) for r in self.due_details(snapshot)}:
            return {**progress, "skipped": "批次未启用、未到期或明细已取消"}
        if not ledgers:
            mid = a.feishu_link_ids(f, "关联物料")[0]
            material = self.index(snapshot[a.MATERIAL_TABLE_NAME]).get(mid)
            if not material:
                raise ValueError("补库物料已删除，不能按名称猜测创建新物料。")
            if progress.get("stock_write_started") and not progress.get("stock_written"):
                self.write(rules.DETAIL_TABLE, rid, {"补库状态": "补库异常", "补库异常说明": "库存写入结果不明确，需核对库存及任务检查点；禁止盲目重试增加库存。"})
                raise RuntimeError("库存写入结果不明确，暂停自动补库，避免重复增加。")
            if not progress.get("stock_written"):
                before = a.feishu_int(a.feishu_fields(material), "当前库存")
                qty = a.feishu_int(f, "下单数量")
                progress.update(stock_write_started=True, before=before, after=before + qty,
                                quantity=qty, material_id=mid)
                checkpoint(dict(progress))
                self.write(a.MATERIAL_TABLE_NAME, mid, {"当前库存": before + qty, "启用状态": "启用"})
                progress["stock_written"] = True
                checkpoint(dict(progress))
            self.write(rules.DETAIL_TABLE, rid, {"补库状态": "补库中"})
            ledger_fields = a.build_feishu_ledger_fields(
                progress["material_id"], "入库", a.feishu_text(f, "品类名称快照"),
                a.feishu_text(f, "型号或尺码快照"), a.feishu_text(f, "语种快照"),
                progress["quantity"], progress["before"], progress["after"],
                f"下单排期制作完成自动补库：{a.feishu_text(f, '批次明细编号')}",
                datetime.now(rules.CHINA_TZ),
                source_request_id=(a.feishu_link_ids(f, "来源申请单") or [""])[0],
                source_line_id=(a.feishu_link_ids(f, "来源申请明细") or [""])[0], idempotency_key=key)
            # The existing ledger builder supplies optional legacy aliases as well.
            ledger_fields = a.filter_feishu_fields(a.LEDGER_TABLE_NAME, ledger_fields)
            if progress.get("ledger_create_started"):
                raise RuntimeError("入库流水创建结果不明确，请先核对，避免重复流水。")
            progress["ledger_create_started"] = True
            checkpoint(dict(progress))
            ledgers = [self.create(a.LEDGER_TABLE_NAME, ledger_fields)]
        self.write(rules.DETAIL_TABLE, rid, {
            "补库状态": "已补库", "实际补库时间": int(datetime.now(rules.CHINA_TZ).timestamp() * 1000),
            "关联库存流水": [a.feishu_record_id(ledgers[0])], "补库异常说明": "",
        })
        self.sync_in_transit_stock()
        progress.update(write_done=True, detail_id=rid)
        checkpoint(dict(progress))
        a.refresh_page_cache_tables((a.MATERIAL_TABLE_NAME, a.LEDGER_TABLE_NAME, rules.BATCH_TABLE, rules.DETAIL_TABLE))
        return progress
