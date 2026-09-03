"""Admin-only order scheduling, grouped by request; no direct Base writes."""
from __future__ import annotations

from datetime import timedelta
import uuid
import pandas as pd
import streamlit as st

import order_scheduling as rules
from order_scheduling_service import SchedulingService
from submission_queue import QUEUE_TASK_TYPE_ORDER_EDIT, QUEUE_TASK_TYPE_ORDER_GENERATE, QUEUE_TASK_TYPE_ORDER_PLAN


@st.cache_data(ttl=300, show_spinner=False)
def schema_ready(_app, app_token):
    del app_token
    return SchedulingService(_app).validate_schema()


def date_label(value):
    try:
        parsed = rules.as_date(value)
        return parsed.isoformat() if parsed else "待补充"
    except (ValueError, TypeError, OverflowError):
        return "日期格式异常"


def enqueue(app, kind, payload, key=None):
    with app.fullscreen_data_sync("正在提交数据，请稍后......"):
        task, _ = app.enqueue_feishu_background_write(kind, payload, key or uuid.uuid4().hex)
    st.session_state["order_pending"] = task.idempotency_key
    st.rerun()


@st.fragment(run_every=5)
def pending_task(app):
    key = st.session_state.get("order_pending")
    if not key:
        return
    try:
        task = app.find_task_by_idempotency_key(app.feishu_client(), key)
        if task is None:
            st.info("后台任务正在登记，请稍候。")
        elif task.status == app.QUEUE_STATUS_COMPLETED:
            SchedulingService(app).refresh()
            st.session_state.pop("order_pending", None)
            st.session_state["order_completed_message"] = "后台处理完成，页面已刷新。"
            st.session_state.pop("order_selection_token", None)
            st.rerun(scope="app")
        elif task.status == app.QUEUE_STATUS_FAILED:
            st.error("后台处理失败，不能视为已保存。请核对任务错误后再处理，避免重复下单或补库。")
            st.code(str(getattr(task, "error", "") or task.result))
            if st.button("关闭任务提示", key="order_close_task"):
                st.session_state.pop("order_pending", None)
                st.rerun(scope="app")
        else:
            st.info("已进入后台队列，正在处理；完成后自动更新本页。")
    except Exception as exc:
        st.warning(f"任务状态暂时无法读取：{exc}")


def request_schedule_inputs(app):
    """Normal-material form only. Values are ISO strings for durable queue payloads."""
    en = app.get_ui_language() == app.LANGUAGE_EN
    cols = st.columns([1, 1.5], gap="small")
    reasons_en = {"代理活动": "Dealer activity", "展会需求": "Exhibition", "客户来访": "Customer visit"}
    app.required_field_label(cols[0], "Request reason" if en else "申请原因")
    app.required_field_label(cols[1], "Arrival date / range" if en else "到达日期／范围")
    reason = cols[0].selectbox("Request reason *" if en else "申请原因 *", rules.REASONS,
                              index=None, key="request_schedule_reason",
                              format_func=lambda v: reasons_en[v] if en else v,
                              placeholder="Please select" if en else "请选择", label_visibility="collapsed",
                              on_change=app.mark_request_form_dirty)
    dates = cols[1].date_input("Required arrival date/range *" if en else "要求到达使用场景的日期／范围 *",
                              value=[], min_value=rules.today(), key="request_schedule_dates",
                              format="YYYY-MM-DD", label_visibility="collapsed",
                              on_change=app.mark_request_form_dirty)
    st.caption("Arrival means delivery to the place of use. Calendar days: 7–14 = urgent; 15+ = standard. Customer visits and regional marketing managers are exempt. Date ranges use the start date."
               if en else "到达日期指到达使用场景的日期。按自然日：7～14天加急，15天起普通；客户来访、区域市场经理豁免。范围按开始日倒排，单日可选相同开始和结束日。")
    dates = list(dates) if isinstance(dates, (tuple, list)) else [dates] if dates else []
    return {"scheduling_version": 1, "request_reason": reason or "",
            "arrival_start": dates[0].isoformat() if dates else "",
            "arrival_end": dates[-1].isoformat() if dates else ""}


def edit_dialog(app, group, catalog, operator):
    @st.dialog(f"编辑申请明细 · {group['request_no']}", width="large")
    def render():
        key = f"order_edit_{group['id']}_{group['fingerprint'][:12]}"
        if key not in st.session_state:
            st.session_state[key] = [{"uid": l["id"], "id": l["id"], "material_id": l["material_id"],
                                      "quantity": l["quantity"], "remark": l["remark"]} for l in group["lines"]]
        draft = st.session_state[key]
        st.caption("品类、型号、语种联动选择；保存不会确认库存或修改实际发放数量。")
        remove = None
        categories = sorted({v["category"] for v in catalog.values()})
        for line in draft:
            p = f"{key}_{line['uid']}"
            original = catalog.get(line.get("material_id"), {})
            c = st.columns([1.5, 1.2, 1.2, .7, 1.2, .5], gap="small")
            category = c[0].selectbox("品类", categories, index=categories.index(original["category"]) if original.get("category") in categories else None,
                                      key=p+"_c")
            models = sorted({v["model"] for v in catalog.values() if v["category"] == category})
            if st.session_state.get(p+"_m") not in models:
                st.session_state[p+"_m"] = original.get("model") if original.get("model") in models else None
            model = c[1].selectbox("型号", models, index=None, key=p+"_m")
            langs = sorted({v["language"] for v in catalog.values() if v["category"] == category and v["model"] == model})
            if st.session_state.get(p+"_l") not in langs:
                st.session_state[p+"_l"] = original.get("language") if original.get("language") in langs else None
            language = c[2].selectbox("语种", langs, index=None, key=p+"_l")
            matches = [mid for mid, v in catalog.items() if (v["category"], v["model"], v["language"]) == (category, model, language)]
            if len(matches) > 1:
                # Do not silently pick an arbitrary duplicate inventory row.
                matches = [line["material_id"]] if line.get("material_id") in matches else []
                st.warning("该规格存在重复库存组合，需先核对物料主数据。")
            line["material_id"] = matches[0] if len(matches) == 1 else ""
            line["quantity"] = c[3].number_input("数量", min_value=1, max_value=1_000_000,
                                                value=max(1, int(line["quantity"])), step=1, key=p+"_q")
            line["remark"] = c[4].text_input("备注", value=line["remark"], key=p+"_r")
            if c[5].button("删除", key=p+"_d"):
                remove = line["uid"]
        if remove:
            st.session_state[key] = [r for r in draft if r["uid"] != remove]
            st.rerun(scope="fragment")
        if st.button("新增明细", disabled=len(draft) >= app.MAX_REQUEST_LINE_COUNT):
            draft.append({"uid": uuid.uuid4().hex, "id": "", "material_id": "", "quantity": 1, "remark": ""})
            st.rerun(scope="fragment")
        note = st.text_input("修改说明（必填）", key=key+"_note")
        st.warning("删除会移除该申请明细；后台会保留变更前后记录。已审批、已核实库存或已生成下单表的申请不能在此编辑。")
        if st.button("保存明细修改", type="primary", disabled=not draft or not note or any(not l["material_id"] for l in draft)):
            enqueue(app, QUEUE_TASK_TYPE_ORDER_EDIT, {"request_id": group["id"], "expected_fingerprint": group["fingerprint"],
                    "operator_open_id": operator, "change_note": note, "lines": draft})
    render()


def dates_dialog(app, group, operator):
    @st.dialog(f"补充／调整排期 · {group['request_no']}")
    def render():
        f = group["fields"]
        reason = st.selectbox("申请原因", rules.REASONS,
                              index=rules.REASONS.index(f["申请原因"]) if f.get("申请原因") in rules.REASONS else None)
        start = rules.as_date(f.get(rules.ARRIVAL_START))
        end = rules.as_date(f.get(rules.ARRIVAL_END))
        dates = st.date_input("要求到达使用场景的日期／范围", value=(start, end) if start and end else [], format="YYYY-MM-DD")
        st.caption("以原申请提交日计算提前天数；不会修改提交日期或审批状态。")
        if st.button("保存排期日期", type="primary", disabled=not reason or not dates):
            enqueue(app, QUEUE_TASK_TYPE_ORDER_PLAN, {"action": "request_dates", "request_id": group["id"],
                    "expected_fingerprint": group["fingerprint"], "operator_open_id": operator,
                    "request_reason": reason, "arrival_start": dates[0].isoformat(), "arrival_end": dates[-1].isoformat()})
    render()


def render_order_scheduling_page(app):
    if not app.admin_auth_gate():
        return
    service = SchedulingService(app)
    st.subheader("下单排期管理")
    st.caption("仅普通物料申请 · 按申请单展示 · 任一明细成功生成下单表后，整单退出待下单队列")
    try:
        schema_ready(app, app.feishu_bitable_app_token())
    except Exception as exc:
        st.error(str(exc))
        st.info("仅下单排期功能暂不可用，现有申领、审批与文化周边流程不受影响。")
        return
    if st.session_state.pop("order_completed_message", None):
        st.success("后台处理完成，页面已刷新。")
    pending_task(app)
    snapshot = service.snapshot()
    missing = [table for table in service.tables if table not in dict(app.load_static_page_data_cache().get("tables") or {})
               and not snapshot[table]]
    if missing:
        st.warning("排期缓存尚未准备好，请点击本页刷新数据：" + "、".join(missing))
        return
    admins = {}
    for row in snapshot[app.USER_PERMISSION_TABLE_NAME]:
        f = app.feishu_fields(row)
        if app.feishu_permission_enabled(f) and "管理员" in app.feishu_choice_values(f, "角色"):
            for person in f.get("用户账号") or []:
                admins[person["id"]] = person.get("name") or person["id"]
    operator = st.selectbox("操作管理员", list(admins), index=None, format_func=lambda x: admins[x], key="order_operator")
    mode = st.radio("查看范围", ["未生成下单表", "全部申请", "下单批次历史"], horizontal=True)
    if mode == "下单批次历史":
        render_history(app, service, snapshot, operator)
        return
    filters = st.columns([1.5, 1.5, 1])
    date_range = filters[0].date_input("需要下单日期范围", value=[], key="order_filter_dates")
    query = filters[1].text_input("搜索申请单／申请人／用途", key="order_filter_query").strip().casefold()
    include_missing = filters[2].checkbox("包含待补充日期", value=True)
    groups = service.grouped_requests(snapshot)
    all_material_ids = {l["material_id"] for g in groups.values() for l in g["lines"]}
    catalog = service.catalog(snapshot, include_ids=all_material_ids)
    selections, fingerprints = [], {}
    displayed = 0
    token = st.session_state.setdefault("order_selection_token", uuid.uuid4().hex)
    for group in sorted(groups.values(), key=lambda g: (date_label(g["fields"].get(rules.ORDER_DATE)), g["request_no"])):
        if mode == "未生成下单表" and group["generated"]:
            continue
        if query and query not in f"{group['request_no']} {group['requester']} {group['usage']}".casefold():
            continue
        order_day = rules.as_date(group["fields"].get(rules.ORDER_DATE))
        if order_day is None and not include_missing:
            continue
        if order_day and date_range and not date_range[0] <= order_day <= date_range[-1]:
            continue
        displayed += 1
        with st.expander(f"{group['request_no']} · {group['requester']} · {len(group['lines'])}条明细 · {group['status']}", expanded=True):
            f = group["fields"]
            st.write(f"申请用途：{group['usage'] or '—'}")
            st.caption(f"角色：{f.get('申请时角色快照') or '历史未记录'}　原因：{f.get('申请原因') or '待补充'}　"
                       f"提交：{date_label(f.get('提交时间'))}　时效：{f.get(rules.TIME_CLASS) or '待补充日期'}")
            st.caption(f"需要下单：{date_label(f.get(rules.ORDER_DATE))}　制作完成／到仓：{date_label(f.get(rules.READY_DATE))}　"
                       f"要求到达：{date_label(f.get(rules.ARRIVAL_START))} ～ {date_label(f.get(rules.ARRIVAL_END))}")
            locked = group["generated"] or group["status"] in {"已撤回", "已驳回", "已拒绝", "已取消", "已发放", "已完成"}
            a, b, c = st.columns([1, 1, 2])
            if a.button("编辑申请明细", key="edit_"+group["id"], disabled=not operator or locked):
                try:
                    service.check_group(group, group["fingerprint"], editing=True)
                    edit_dialog(app, group, catalog, operator)
                except ValueError as exc:
                    st.error(str(exc))
            if b.button("补充／调整日期", key="dates_"+group["id"], disabled=not operator or locked):
                dates_dialog(app, group, operator)
            if group["generated"]:
                c.success("本申请已有明细生成过下单表")
            if not group["lines"]:
                st.info("暂无申请明细。")
                continue
            frame = pd.DataFrame([{"选中下单": False, "明细ID": l["id"], "物料品类": l["category"],
                "产品型号": l["model"], "语种": l["language"], "申请数量": l["quantity"],
                "备注": l["remark"], "明细状态": l["status"], "下单表": l["fields"].get(rules.GENERATED) or "未生成"}
                for l in group["lines"]])
            edited = st.data_editor(frame, hide_index=True, width="stretch", num_rows="fixed",
                disabled=True if locked else [col for col in frame.columns if col != "选中下单"],
                column_config={"明细ID": None}, key=f"order_select_{group['id']}_{group['fingerprint'][:12]}_{token}")
            picked = edited.loc[edited["选中下单"] == True, "明细ID"].tolist() if not locked else []
            if picked:
                planned = st.date_input("本次所选明细计划到仓日期", value=rules.as_date(f.get(rules.READY_DATE)),
                                         key="planned_"+group["id"], format="YYYY-MM-DD")
                confirmed = False
                if planned and planned < rules.today():
                    st.warning("计划到仓日期已过：请改期；只有确实已制作完成并到仓时才勾选确认。")
                    confirmed = st.checkbox("我确认这些物料已制作完成并到仓，允许补库", key="arrived_"+group["id"])
                required = rules.as_date(f.get(rules.ARRIVAL_START))
                if planned and required and planned + timedelta(days=10) > required:
                    st.warning("按预留10天运输估算，此排期可能无法满足原要求到达日期；原需求日期不会自动推迟。")
                for lid in picked:
                    selections.append({"request_id": group["id"], "line_id": lid,
                                       "planned_date": planned.isoformat() if planned else "", "confirmed_arrived": confirmed})
                fingerprints[group["id"]] = group["fingerprint"]
    if not displayed:
        st.info("此筛选范围内没有申请单。")
    st.divider()
    st.write(f"已选择 {len(fingerprints)} 张申请单、{len(selections)} 条明细。未选择的明细不会下单或补库。")
    note = st.text_input("下单批次备注（可选）", key="order_batch_note")
    valid = bool(selections) and all(s["planned_date"] and (rules.as_date(s["planned_date"]) >= rules.today() or s["confirmed_arrived"]) for s in selections)
    if st.button("生成下单表", type="primary", disabled=not operator or not valid or bool(st.session_state.get("order_pending"))):
        key = uuid.uuid4().hex
        enqueue(app, QUEUE_TASK_TYPE_ORDER_GENERATE, {"operator_open_id": operator, "generation_key": key,
                "selections": selections, "fingerprints": fingerprints, "note": note}, key)


def render_history(app, service, snapshot, operator):
    batches = [r for r in snapshot[rules.BATCH_TABLE] if app.feishu_text(app.feishu_fields(r), "下单批次号")]
    if not batches:
        st.info("暂无下单批次。")
    for row in reversed(batches):
        bid, f = app.feishu_record_id(row), app.feishu_fields(row)
        with st.expander(f"{f.get('下单批次号')} · {f.get('批次状态')}", expanded=True):
            st.caption(f"生成时间：{app.feishu_datetime_text(f.get('生成时间'))}　自动补库：{'启用' if f.get('启用自动补库') is True else '暂停'}")
            for attachment in app.feishu_attachment_items(f, "下单表文件"):
                if st.button("准备下载下单表", key=f"order_download_{bid}_{attachment.get('file_token')}"):
                    try:
                        data = app.load_feishu_attachment(attachment["file_token"], attachment.get("tmp_url") or attachment.get("url") or "")
                        st.download_button("下载 Excel", data=data, file_name=attachment.get("name") or "物料下单表.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"order_file_{bid}")
                    except Exception as exc:
                        st.error(f"下载失败：{exc}")
            details = [r for r in snapshot[rules.DETAIL_TABLE] if bid in app.feishu_link_ids(app.feishu_fields(r), "所属下单批次")]
            if details:
                st.dataframe(pd.DataFrame([{k: app.feishu_fields(r).get(k) for k in
                    ("品类名称快照", "型号或尺码快照", "语种快照", "下单数量", "补库状态", "补库异常说明")}
                    | {"计划到仓日期": date_label(app.feishu_fields(r).get("计划到仓日期"))} for r in details]), hide_index=True, width="stretch")
            if operator and f.get("批次状态") == "已生成":
                enabled = st.checkbox("启用此批次自动补库", value=f.get("启用自动补库") is True, key="order_auto_"+bid)
                if st.button("保存补库开关", key="order_save_auto_"+bid):
                    enqueue(app, QUEUE_TASK_TYPE_ORDER_PLAN, {"action": "batch_enabled", "batch_id": bid,
                        "operator_open_id": operator, "enabled": enabled})
                for detail in details:
                    df, did = app.feishu_fields(detail), app.feishu_record_id(detail)
                    if df.get("补库状态") not in {"待补库", "已取消"}:
                        continue
                    with st.expander(f"调整到仓日期 · {df.get('品类名称快照')} / {df.get('型号或尺码快照')}"):
                        planned = st.date_input("计划到仓日期", value=rules.as_date(df.get("计划到仓日期")), key="order_change_date_"+did)
                        arrived = st.checkbox("确认该明细已经制作完成并到仓", key="order_change_arrived_"+did) if planned and planned < rules.today() else False
                        if st.button("保存到仓日期", key="order_change_save_"+did, disabled=not planned):
                            enqueue(app, QUEUE_TASK_TYPE_ORDER_PLAN, {"action": "receipt_date", "detail_id": did,
                                "operator_open_id": operator, "planned_date": planned.isoformat(), "confirmed_arrived": arrived,
                                "expected_fingerprint": rules.fingerprint(df)})
