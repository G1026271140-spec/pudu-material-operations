import { useEffect, useMemo, useRef, useState } from "react";
import "./allocation.css";

type Lang = "zh" | "en";
type Props = {
  lang: Lang;
  directRequestId?: string;
  operator?: string;
  reviewToken?: string;
  embedded?: boolean;
};

const unique = (values: string[]) => [...new Set(values.filter(Boolean))];
const money = (value: number) => `¥${Number(value || 0).toFixed(2)}`;
const detail = (value: unknown, fallback: string) =>
  Array.isArray(value) ? value.join("；") : typeof value === "string" ? value : fallback;
const isPrintMaterial = (material: any) =>
  material?.category_definition === "印刷物料";
const defaultOrderRequired = (material: any, quantity: number) =>
  isPrintMaterial(material) && Number(material?.quantity || 0) < Number(quantity || 0);
const PENDING_SESSION_CACHE_KEY = "pudu-allocation-pending-session-v1";

type PendingSessionCache = {
  requests: any[];
  operators: any[];
  cachedAt: string;
};

function readPendingSessionCache(): PendingSessionCache | null {
  try {
    const raw = window.sessionStorage.getItem(PENDING_SESSION_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (!Array.isArray(cached?.requests) || !Array.isArray(cached?.operators)) return null;
    return {
      requests: cached.requests,
      operators: cached.operators,
      cachedAt: typeof cached.cachedAt === "string" ? cached.cachedAt : "",
    };
  } catch {
    return null;
  }
}

function writePendingSessionCache(cache: PendingSessionCache) {
  try {
    window.sessionStorage.setItem(PENDING_SESSION_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Session storage can be unavailable. Live reads remain the fallback.
  }
}

function removePendingRequestFromSessionCache(requestId: string) {
  const cached = readPendingSessionCache();
  if (!cached) return;
  writePendingSessionCache({
    ...cached,
    requests: cached.requests.filter(item => item.requestId !== requestId),
  });
}

async function jsonFetch(url: string, options?: RequestInit) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw Error(detail(body.detail, "操作失败"));
  return body;
}

export default function AllocationWorkbench({ lang, directRequestId = "", operator = "", reviewToken = "", embedded = false }: Props) {
  const tr = (zh: string, en: string) => lang === "zh" ? zh : en;
  const [pending, setPending] = useState<any[]>([]);
  const [operators, setOperators] = useState<any[]>([]);
  const [requestId, setRequestId] = useState(directRequestId);
  const [operatorId, setOperatorId] = useState(operator);
  const [context, setContext] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [shipDate, setShipDate] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [ack, setAck] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [confirmMode, setConfirmMode] = useState<"confirm" | "edit" | "">("");
  const [orderPreview, setOrderPreview] = useState<any>(null);
  const [pendingCachedAt, setPendingCachedAt] = useState("");
  const [pendingRefreshing, setPendingRefreshing] = useState(false);
  const [pendingWarning, setPendingWarning] = useState("");
  const pendingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPollCount = useRef(0);
  const signedQuery = `operator=${encodeURIComponent(operator)}&review_token=${encodeURIComponent(reviewToken)}`;

  useEffect(() => {
    if (directRequestId) loadContext(directRequestId);
    else loadPending();
    return () => { if (pendingPollRef.current) clearTimeout(pendingPollRef.current); };
  }, [directRequestId]);

  function applyPending(body: PendingSessionCache) {
    setPending(body.requests || []);
    setOperators(body.operators || []);
    setPendingCachedAt(body.cachedAt || "");
    if (!operatorId && body.operators?.length) setOperatorId(body.operators[0].open_id);
  }

  async function loadPending(forceRefresh = false) {
    if (forceRefresh) pendingPollCount.current = 0;
    const cached = !forceRefresh ? readPendingSessionCache() : null;
    if (cached) applyPending(cached);
    setLoading(!cached && pending.length === 0);
    setError("");
    try {
      const body = await jsonFetch(`/api/admin/allocation/pending${forceRefresh ? "?refresh=true" : ""}`);
      const cache = {
        requests: body.requests || [],
        operators: body.operators || [],
        cachedAt: body.updatedAt || new Date().toISOString(),
      };
      writePendingSessionCache(cache);
      applyPending(cache);
      setPendingRefreshing(Boolean(body.refreshing));
      setPendingWarning(body.refreshError || "");
      if (pendingPollRef.current) clearTimeout(pendingPollRef.current);
      if (body.refreshing && pendingPollCount.current < 45) {
        pendingPollCount.current += 1;
        pendingPollRef.current = setTimeout(() => void loadPending(), 4000);
      } else pendingPollCount.current = 0;
    } catch (e) {
      const message = e instanceof Error ? e.message : "读取失败";
      if (cached) setPendingWarning(message);
      else setError(message);
    }
    finally { setLoading(false); }
  }

  async function loadContext(id: string) {
    if (!id) return;
    setLoading(true); setError(""); setSuccess("");
    try {
      const suffix = directRequestId ? `?${signedQuery}` : "";
      const body = await jsonFetch(`/api/allocation/${encodeURIComponent(id)}${suffix}`);
      setRequestId(id); setContext(body); setShipDate(body.shipDate || "");
      setOperators(body.operators || operators);
      if (body.operatorOpenId) setOperatorId(body.operatorOpenId);
      setRows((body.lines || []).map((line: any) => ({
        uid: line.record_id || crypto.randomUUID(),
        line_record_id: line.record_id || "",
        material_record_id: line.material_record_id || "",
        category: line.product || "",
        model: line.model || "无需型号",
        language: line.language || "无需语种",
        quantity: Math.max(1, Number(line.quantity || 1)),
        remark: line.remark || "",
        order_required:
          line.category_definition === "印刷物料" &&
          Number(line.current_stock || 0) < Number(line.quantity || 0),
      })));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); setContext(null); }
    finally { setLoading(false); }
  }

  const materials = context?.materials || [];
  const materialById = useMemo(() => Object.fromEntries(materials.map((x: any) => [x.record_id, x])), [materials]);
  const originalTotal = (context?.lines || []).reduce((sum: number, x: any) => sum + Number(x.subtotal_rmb || Number(x.unit_price_rmb || 0) * Number(x.quantity || 0)), 0);
  const currentTotal = rows.reduce((sum: number, x: any) => sum + Number(materialById[x.material_record_id]?.unit_price_rmb || 0) * Number(x.quantity || 0), 0);

  function selectMaterial(index: number, key: "category" | "model" | "language", value: string) {
    setRows(rows.map((row, i) => {
      if (i !== index) return row;
      const next = { ...row, [key]: value };
      const candidates = materials.filter((x: any) =>
        (key === "category" ? x.category === value : x.category === next.category) &&
        (key === "model" ? x.model === value : key === "language" ? x.model === next.model && x.language === value : true));
      const chosen = candidates[0];
      if (key === "category" && chosen) { next.model = chosen.model; next.language = chosen.language; }
      if (key === "model" && chosen) next.language = chosen.language;
      const exact = materials.find((x: any) => x.category === next.category && x.model === next.model && x.language === next.language);
      next.material_record_id = exact?.record_id || "";
      next.order_required = defaultOrderRequired(exact, Number(next.quantity));
      return next;
    }));
  }

  function addRow() {
    const first = materials[0];
    if (!first) return setError(tr("物料目录为空，无法新增明细。", "The material catalog is empty."));
    setRows([...rows, { uid: crypto.randomUUID(), line_record_id: "", material_record_id: first.record_id, category: first.category, model: first.model, language: first.language, quantity: 1, remark: "", order_required: defaultOrderRequired(first, 1) }]);
  }

  function validate(mode: "confirm" | "edit") {
    if (!shipDate) return tr("请选择申请单发货日期。", "Select a shipping date.");
    if (!operatorId) return tr("请选择本次配货操作人。", "Select an allocation operator.");
    if (mode === "edit") {
      if (!rows.length) return tr("配货方案必须至少保留一条物料明细。", "Keep at least one material line.");
      if (rows.some(x => !x.material_record_id || Number(x.quantity) < 1)) return tr("配货方案中存在无效物料或数量。", "The allocation contains an invalid material or quantity.");
      if (new Set(rows.map(x => x.material_record_id)).size !== rows.length) return tr("同一物料不能重复添加，请合并数量。", "Duplicate materials must be merged.");
      if (!changeNote.trim()) return tr("请填写配货调整说明。", "Enter an allocation change note.");
      if (!ack) return tr("请确认已核对方案并同意向申请人发送变更通知。", "Confirm the plan and requester notification.");
    }
    return "";
  }

  function allocationDraft(mode: "confirm" | "edit") {
    const version = Number(context.request.inventory_review_version || 0);
    const draft: any = {
      request_id: requestId,
      expected_version: version,
      operator_open_id: operatorId,
      ship_date: shipDate,
      generation_key: `allocation:${requestId}:${version}`,
    };
    if (mode === "edit") {
      draft.change_note = changeNote.trim();
      draft.before_lines = (context.lines || []).map((x: any) => ({ record_id: x.record_id || "", material_record_id: x.material_record_id || "", product: x.product || "", model: x.model || "", language: x.language || "", quantity: Number(x.quantity || 0), remark: x.remark || "", unit_price_rmb: Number(x.unit_price_rmb || 0), subtotal_rmb: Number(x.subtotal_rmb || 0) }));
      draft.lines = rows.map(x => ({ line_record_id: x.line_record_id, material_record_id: x.material_record_id, quantity: Number(x.quantity), remark: x.remark || "", order_required: x.order_required === true }));
    }
    return draft;
  }

  async function openConfirm(mode: "confirm" | "edit") {
    const message = validate(mode);
    if (message) return setError(message);
    setPreviewing(true); setError("");
    try {
      const suffix = directRequestId ? `?${signedQuery}` : "";
      const draft = allocationDraft(mode);
      const preview = await jsonFetch(`/api/allocation/${encodeURIComponent(requestId)}/order-preview${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation: mode, draft }) });
      setOrderPreview(preview);
      setConfirmMode(mode);
    } catch (e) { setError(e instanceof Error ? e.message : "下单信息预览失败"); }
    finally { setPreviewing(false); }
  }

  async function submit() {
    const mode = confirmMode as "confirm" | "edit";
    const draft = allocationDraft(mode);
    setSubmitting(true); setError("");
    try {
      const suffix = directRequestId ? `?${signedQuery}` : "";
      let workbook: Blob | null = null;
      if (orderPreview?.workbookAvailable) {
        const workbookResponse = await fetch(`/api/allocation/${encodeURIComponent(requestId)}/order-workbook${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation: mode, draft }) });
        if (!workbookResponse.ok) {
          const failure = await workbookResponse.json().catch(() => ({}));
          throw Error(detail(failure.detail, "下单表生成失败"));
        }
        workbook = await workbookResponse.blob();
      }
      const body = await jsonFetch(`/api/allocation/${encodeURIComponent(requestId)}/submit${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation: mode, draft }) });
      if (workbook) {
        const url = URL.createObjectURL(workbook);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = orderPreview.workbookFilename || `物料下单表-${request.request_no || requestId}.xlsx`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      setSuccess(`${tr("配货任务已进入后台队列", "Allocation task queued")}（${body.taskId}）`);
      removePendingRequestFromSessionCache(requestId);
      setPending(current => current.filter(item => item.requestId !== requestId));
      setConfirmMode("");
      setOrderPreview(null);
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败"); }
    finally { setSubmitting(false); }
  }

  if (loading) return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`}><div className="allocation-loading"><i/><b>{tr("正在抓取实时申请与库存数据，请稍候……", "Loading live request and inventory data…")}</b></div></main>;
  if (!requestId || !context) return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`}>
    <header><div><small>{tr("人工库存复核", "Manual Inventory Review")}</small><h1>{tr("配货工作台", "Allocation Workbench")}</h1><p>{tr("从当前未核实库存的申请单中选择并制定配货方案", "Select a pending request and prepare its allocation plan")}</p>{pendingCachedAt && <p className="pending-cache-note">{tr("列表快照：", "List snapshot: ")}{pendingCachedAt}{pendingRefreshing ? tr(" · 正在后台同步实时申请单", " · refreshing live requests") : ""}</p>}</div><button onClick={() => loadPending(true)}>↻ {tr("刷新实时申请单", "Refresh live requests")}</button></header>
    {error && <div className="allocation-toast" onClick={() => setError("")}>{error} ×</div>}
    {pendingWarning && <div className="allocation-toast" onClick={() => setPendingWarning("")}>{pendingWarning} ×</div>}
    <section className="pending-panel"><div className="pending-head"><h2>{tr("待库存核实申请", "Pending Inventory Reviews")}</h2><span>{pending.length} {tr("条", "requests")}</span></div>{pending.length ? <div className="pending-grid">{pending.map(item => <button key={item.requestId} onClick={() => loadContext(item.requestId)}><strong>{item.requestNo}</strong><span>{item.requester} · {item.department}</span><span>{item.reason || "-"} · {item.lineCount} {tr("条明细", "lines")}</span><em>{item.inventoryReviewResult || tr("待核实", "Pending")}</em></button>)}</div> : <div className="allocation-empty">{pendingRefreshing || pendingWarning ? tr("正在核对实时申请单；当前快照中没有待处理记录。", "Checking live requests; none in the current snapshot.") : tr("当前没有等待库存核实的普通物料申请。", "There are no material requests waiting for inventory review.")}</div>}</section>
  </main>;

  const request = context.request;
  return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`}>
    <header><div><small>{tr("人工库存复核", "Manual Inventory Review")}</small><h1>{tr("配货工作台", "Allocation Workbench")}</h1><p>{tr("调整本次申请的配货方案", "Adjust the allocation plan for this request")}</p></div>{!directRequestId && <button onClick={() => { setRequestId(""); setContext(null); loadPending(); }}>← {tr("返回申请单列表", "Back to requests")}</button>}</header>
    {error && <div className="allocation-toast" onClick={() => setError("")}>{error} ×</div>}
    {success && <div className="allocation-toast allocation-task-toast" role="status">
      <button type="button" className="allocation-toast-close" aria-label={tr("关闭提示", "Close notification")} onClick={() => setSuccess("")}>×</button>
      <strong>{success}</strong>
      <small>{tr("后台完成后，申请人与管理员飞书卡片会按原流程更新。", "The requester and administrator cards will update after background completion.")}</small>
    </div>}
    {request.inventory_review_status === "已核实库存" ? <div className="allocation-success">✓ {tr("该申请已经完成库存核实，无需再次处理。", "This request has already completed inventory review.")}</div> : <>
      <section className="request-overview"><div className="allocation-title"><b>{request.request_no || "-"}</b><span>{tr("实时库存更新于", "Live stock updated at")} {context.snapshotAt}</span></div><div className="allocation-metrics"><span>{tr("申请人", "Requester")}<b>{request.requester || "-"}</b></span><span>{tr("申请部门", "Department")}<b>{request.department || "-"}</b></span><span>{tr("当前结论", "Current Result")}<b>{context.result || "-"}</b></span><span>{tr("变更次数", "Changes")}<b>{request.inventory_review_version || 0}</b></span><span>{tr("原申请总金额", "Original Total")}<b>{money(originalTotal)}</b></span></div><div className="request-notes"><p><b>{tr("申请原因", "Reason")}：</b>{request.request_reason || "-"}</p><p><b>{tr("物料用途", "Usage")}：</b>{request.material_usage || "-"}</p><p><b>{tr("收件人信息", "Recipient")}：</b>{request.recipient_info || "-"}</p></div></section>
      <section className="allocation-form"><div className="allocation-control"><label>{tr("申请单发货日期", "Shipping Date")} *<input type="date" value={shipDate} onChange={e => setShipDate(e.target.value)}/></label>{!context.signedCardAccess && <label>{tr("本次配货操作人", "Allocation Operator")} *<select value={operatorId} onChange={e => setOperatorId(e.target.value)}><option value="">{tr("请选择管理员", "Select administrator")}</option>{operators.map(x => <option key={x.open_id} value={x.open_id}>{x.name} · {(x.department_paths || []).join(" / ")}</option>)}</select></label>}</div>
        <div className="allocation-section-title"><div><h2>{tr("配货明细", "Allocation Lines")}</h2><p>{tr(`品类、型号和语种来自页面缓存（${context.cacheGeneratedAt || "未知时间"}）；库存来自本次实时读取。`, `Options use the page cache (${context.cacheGeneratedAt || "unknown"}); stock is live.`)}</p></div><button className="confirm-original" onClick={() => openConfirm("confirm")}>✓ {tr("按原申请确认配货方案", "Review Original Allocation")}</button></div>
        <div className="allocation-lines">{rows.map((row, index) => {
          const categories = unique(materials.map((x: any) => x.category));
          const models = unique(materials.filter((x: any) => x.category === row.category).map((x: any) => x.model));
          const languages = unique(materials.filter((x: any) => x.category === row.category && x.model === row.model).map((x: any) => x.language));
          const material = materialById[row.material_record_id] || {};
          const canOrder = isPrintMaterial(material);
          return <article key={row.uid}><div className="line-index">{String(index + 1).padStart(2, "0")}</div><div className="line-fields"><label>{tr("品类", "Category")}<select value={row.category} onChange={e => selectMaterial(index, "category", e.target.value)}>{categories.map(x => <option key={x}>{x}</option>)}</select></label><label>{tr("型号", "Model")}<select value={row.model} onChange={e => selectMaterial(index, "model", e.target.value)}>{models.map(x => <option key={x}>{x}</option>)}</select></label><label>{tr("语种", "Language")}<select value={row.language} onChange={e => selectMaterial(index, "language", e.target.value)}>{languages.map(x => <option key={x}>{x}</option>)}</select></label><label>{tr("数量", "Quantity")}<input type="number" min="1" value={row.quantity} onChange={e => { const quantity = Math.max(1, Number(e.target.value)); setRows(rows.map((x, i) => i === index ? {...x, quantity, order_required: canOrder ? x.order_required : false} : x)); }}/></label><label>{tr("是否下单", "Order Required")}<select disabled={!canOrder} value={canOrder && row.order_required ? "yes" : "no"} onChange={e => setRows(rows.map((x, i) => i === index ? {...x, order_required: canOrder && e.target.value === "yes"} : x))}>{canOrder && <option value="yes">{tr("需要下单", "Order")}</option>}<option value="no">{tr("无需下单", "No Order")}</option></select></label><label className="remark">{tr("备注", "Remark")}<input value={row.remark} onChange={e => setRows(rows.map((x, i) => i === index ? {...x, remark: e.target.value} : x))}/></label></div><div className="stock-info"><span>{tr("实时库存", "Live Stock")}<b className={Number(material.quantity || 0) < Number(row.quantity) ? "low" : ""}>{Number(material.quantity || 0)}</b></span><span>{tr("在途库存", "In Transit")}<b>{Number(material.in_transit_quantity || 0)}</b></span><span>{tr("单价", "Unit Price")}<b>{money(material.unit_price_rmb || 0)}</b></span><button disabled={rows.length <= 1} onClick={() => setRows(rows.filter((_, i) => i !== index))}>{tr("删除", "Delete")}</button></div></article>;
        })}</div>
        <button className="add-allocation-line" onClick={addRow}>＋ {tr("新增明细", "Add Line")}</button>
        <div className="amount-comparison"><span>{tr("原申请总金额", "Original Total")}<b>{money(originalTotal)}</b></span><span>{tr("当前配货总金额", "Allocation Total")}<b>{money(currentTotal)}</b><em className={currentTotal - originalTotal < 0 ? "negative" : ""}>{currentTotal - originalTotal >= 0 ? "+" : ""}{money(currentTotal - originalTotal)}</em></span></div>
        <label className="change-note">{tr("配货调整说明", "Allocation Change Note")} *<textarea placeholder={tr("请说明替换、增加、删除物料或调整数量的原因；该说明会发送给申请人。", "Explain replacements, additions, deletions, or quantity changes. This will be sent to the requester.")} value={changeNote} onChange={e => setChangeNote(e.target.value)}/></label>
        <label className="allocation-ack"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>{tr("我已核对配货方案，并确认向申请人发送变更通知", "I reviewed this plan and confirm notifying the requester")}</label>
        <button className="submit-allocation" disabled={!ack} onClick={() => openConfirm("edit")}>{tr("提交配货方案", "Submit Allocation Plan")}</button>
      </section>
    </>}
    {confirmMode && orderPreview && <div className="allocation-modal-backdrop" onMouseDown={() => { setConfirmMode(""); setOrderPreview(null); }}><div className="allocation-modal order-confirm-modal" onMouseDown={e => e.stopPropagation()}><button className="close" onClick={() => { setConfirmMode(""); setOrderPreview(null); }}>×</button><h2>{tr("确认配货与下单信息", "Confirm Allocation and Order")}</h2><p><b>{request.request_no}</b> · {request.requester} · {shipDate}</p><div className="modal-summary"><span>{tr("配货明细", "Allocation Lines")}<b>{confirmMode === "confirm" ? context.lines.length : rows.length}</b></span><span>{tr("需要下单", "Order Lines")}<b>{orderPreview.lineCount}</b></span><span>{tr("下单总数量", "Order Quantity")}<b>{orderPreview.totalQuantity}</b></span></div><div className="order-confirm-section"><h3>{tr("需要下单的印刷物料汇总", "Printed Materials to Order")}</h3>{orderPreview.lines.length ? <div className="order-confirm-table-wrap"><table className="order-confirm-table"><thead><tr><th>{tr("类型", "Type")}</th><th>{tr("物料名称", "Material")}</th><th>{tr("语种", "Language")}</th><th>{tr("数量", "Quantity")}</th><th>{tr("用途", "Purpose")}</th></tr></thead><tbody>{orderPreview.lines.map((line: any, index: number) => <tr key={`${line.category}-${line.model}-${line.language}-${index}`}><td>{line.category}</td><td>{line.model}</td><td>{line.language}</td><td>{line.quantity}</td><td>{line.usage || "-"}</td></tr>)}</tbody></table></div> : <div className="order-confirm-empty">{tr("本次配货没有需要下单的印刷物料，不会生成下单表。", "No printed materials require ordering; no order workbook will be generated.")}</div>}</div>{confirmMode === "edit" && <p className="note-preview">{changeNote}</p>}<p className="order-confirm-hint">{orderPreview.workbookAvailable ? tr("再次确认后，配货任务将写入后台队列，并立即下载物料下单表。", "Final confirmation queues the allocation and downloads the order workbook.") : tr("再次确认后，配货任务将写入后台队列。", "Final confirmation queues the allocation.")}</p><div className="modal-actions"><button onClick={() => { setConfirmMode(""); setOrderPreview(null); }}>{tr("返回修改", "Back")}</button><button className="primary" onClick={submit}>{orderPreview.workbookAvailable ? tr("确认写入并下载下单表", "Confirm and Download") : tr("确认写入配货方案", "Confirm Allocation")}</button></div></div></div>}
    {(previewing || submitting) && <div className="allocation-submit-overlay"><i/><b>{previewing ? tr("正在汇总下单信息……", "Preparing order summary…") : tr("正在提交配货方案，请稍后……", "Submitting allocation plan…")}</b><span>{previewing ? tr("正在核对实时申请明细与下单表模板", "Checking live lines and the order template") : tr("任务正在进入后台队列，请勿重复提交", "The task is entering the background queue")}</span></div>}
  </main>;
}
