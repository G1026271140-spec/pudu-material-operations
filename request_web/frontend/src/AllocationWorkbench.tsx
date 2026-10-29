import SplitSelectionEditor from "./SplitSelectionEditor";
import { chooseAllocationMaterial, nextAllocationMaterial, mergeAllocationRows } from "./allocationRows";
import ToastMessage from "./ToastMessage";
import { splitCategoryRows } from "./categoryGroups";
import { groupByCategory } from "./categoryGroups";
import { CategoryRows } from "./CategoryGroups";
import RequiredMark from "./RequiredMark";
import { useEffect, useMemo, useRef, useState } from "react";
import "./allocation.css";
import "./pending-followup.css";
import PendingAllocationList from "./PendingAllocationList";
import PendingFollowupDialog from "./PendingFollowupDialog";
import { requiredArrivalText } from "./allocationPresentation";

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
const PENDING_SESSION_CACHE_KEY = "pudu-allocation-pending-session-v2";
const usesLiveData = () => document.querySelector('meta[name="pudu-live-data"]')?.getAttribute('content') === '1';

type PendingSessionCache = {
  requests: any[];
  operators: any[];
  cachedAt: string;
};

function readPendingSessionCache(): PendingSessionCache | null {
  if (usesLiveData()) return null;
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
  if (usesLiveData()) return;
  try {
    window.sessionStorage.setItem(PENDING_SESSION_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Session storage can be unavailable. Live reads remain the fallback.
  }
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
  const [followup, setFollowup] = useState<any>(null);
  const [operators, setOperators] = useState<any[]>([]);
  const [requestId, setRequestId] = useState(directRequestId);
  const [operatorId, setOperatorId] = useState(operator);
  const [context, setContext] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [editingUid, setEditingUid] = useState<string | null>(null);
  const editorRef = useRef<HTMLDialogElement>(null);
  const [splitCategory, setSplitCategory] = useState<string | null>(null);
  const [splitQuantities, setSplitQuantities] = useState<Record<string, number>>({});
  const [splitDrafts, setSplitDrafts] = useState<Record<string, Record<string, number>>>({});
  const [shipDate, setShipDate] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [ack, setAck] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [withdrawConfirm, setWithdrawConfirm] = useState(false);
  const [withdrawQueued, setWithdrawQueued] = useState(false);
  const submitLockRef = useRef(false);
  const [, setPendingCachedAt] = useState("");
  const [, setPendingRefreshing] = useState(false);
  const [pendingWarning, setPendingWarning] = useState("");
  const [liveChecking, setLiveChecking] = useState(false);
  const [liveWarning, setLiveWarning] = useState("");
  const contextLoadRef = useRef(0);
  const signedQuery = `operator=${encodeURIComponent(operator)}&review_token=${encodeURIComponent(reviewToken)}`;

  useEffect(() => {
    if (directRequestId) loadContext(directRequestId);
    else loadPending();
    return () => { contextLoadRef.current += 1; };
  }, [directRequestId]);

  useEffect(() => {
    const dialog = editorRef.current;
    if (!dialog) return;
    if (editingUid && !dialog.open) dialog.showModal();
    if (!editingUid && dialog.open) dialog.close();
  }, [editingUid]);

  function applyPending(body: PendingSessionCache) {
    setPending(body.requests || []);
    setOperators(body.operators || []);
    setPendingCachedAt(body.cachedAt || "");
    if (!operatorId && body.operators?.length) setOperatorId(body.operators[0].open_id);
  }

  async function loadPending(forceRefresh = false) {
    const previous = readPendingSessionCache();
    const cached = !forceRefresh ? previous : null;
    if (cached) applyPending(cached);
    setLoading(!cached && pending.length === 0);
    setError("");
    try {
      const body = await jsonFetch("/api/admin/allocation/pending");
      const snapshot = {
        requests: body.requests || [],
        operators: body.operators || [],
        cachedAt: body.updatedAt || new Date().toISOString(),
      };
      writePendingSessionCache(snapshot);
      applyPending(snapshot);
      setPendingRefreshing(Boolean(body.refreshing));
      setPendingWarning(body.refreshError || "");
    } catch (e) {
      const message = e instanceof Error ? e.message : "读取失败";
      if (cached) setPendingWarning(message);
      else setError(message);
    }
    finally { setLoading(false); }
  }

  function applyContext(body: any, id: string) {
      setRequestId(id); setContext(body); setShipDate(body.shipDate || "");
      setOperators(body.operators || []);
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
  }

  async function loadContext(id: string) {
    if (!id) return;
    setEditingUid(null);
    const sequence = ++contextLoadRef.current;
    setWithdrawConfirm(false); setWithdrawQueued(false);
    setLoading(true); setError(""); setSuccess(""); setLiveWarning("");
    const base = `/api/allocation/${encodeURIComponent(id)}`;
    const query = directRequestId ? `${signedQuery}&` : "";
    let hasSnapshot = false;
    try {
      const cached = usesLiveData() ? null : await jsonFetch(`${base}?${query}snapshot=true`);
      if (!cached) throw Error('Live source mode');
      if (sequence !== contextLoadRef.current) return;
      applyContext(cached, id);
      hasSnapshot = true;
      setLoading(false);
    } catch {
      // A new request may not be present in the published cache yet.
    }
    if (sequence !== contextLoadRef.current) return;
    setLiveChecking(true);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      let retryable = false;
      try {
        const response = await fetch(`${base}${directRequestId ? `?${signedQuery}` : ""}`);
        const body = await response.json();
        if (!response.ok) {
          retryable = response.headers.get("X-Pudu-Retryable") === "1";
          throw Error(detail(body.detail, "实时读取失败"));
        }
        if (sequence !== contextLoadRef.current) return;
        applyContext(body, id);
        setLiveWarning(""); setLiveChecking(false); setLoading(false);
        return;
      } catch (e) {
        if (sequence !== contextLoadRef.current) return;
        const message = e instanceof Error ? e.message : "实时读取失败";
        if (retryable && attempt < 2) {
          setLiveWarning(tr("飞书正在准备数据，系统会自动重试。", "Feishu is preparing data; retrying automatically."));
          await new Promise(resolve => window.setTimeout(resolve, 4000 * (attempt + 1)));
          continue;
        }
        setLiveChecking(false); setLoading(false);
        if (hasSnapshot) setLiveWarning(tr("实时核对暂不可用，当前仅显示历史快照，不能提交。请稍后重试。", "Live verification is unavailable. This snapshot is read-only; retry shortly."));
        else setError(message);
        return;
      }
    }
  }

  const materials = context?.materials || [];
  const materialById = useMemo(() => Object.fromEntries(materials.map((x: any) => [x.record_id, x])), [materials]);
  const originalTotal = (context?.lines || []).reduce((sum: number, x: any) => sum + Number(x.subtotal_rmb || Number(x.unit_price_rmb || 0) * Number(x.quantity || 0)), 0);
  const currentTotal = rows.reduce((sum: number, x: any) => sum + Number(materialById[x.material_record_id]?.unit_price_rmb || 0) * Number(x.quantity || 0), 0);
  const canEdit = Boolean(context?.verifiedLive) && !withdrawQueued && !submitting;
  const editingIndex = rows.findIndex(row => row.uid === editingUid);
  const editingRow = editingIndex >= 0 ? rows[editingIndex] : null;
  const editingMaterial = materialById[editingRow?.material_record_id] || {};
  const canOrder = isPrintMaterial(editingMaterial);
  const categories = useMemo(() => unique(materials.map((x: any) => x.category)), [materials]);
  const editorModels = unique(materials.filter((x: any) => x.category === editingRow?.category).map((x: any) => x.model));
  const editorLanguages = unique(materials.filter((x: any) => x.category === editingRow?.category && x.model === editingRow?.model).map((x: any) => x.language));

  function openLine(uid: string) {
    if (canEdit) setEditingUid(uid);
  }

  function removeLine(uid: string) {
    if (!canEdit || rows.length <= 1) return;
    setRows(current => current.length > 1 ? current.filter(row => row.uid !== uid) : current);
    setEditingUid(null);
  }

  function selectMaterial(index: number, key: "category" | "model" | "language", value: string) {
    const row = rows[index];
    const chosen = chooseAllocationMaterial(materials, row, key, value);
    if (!chosen) return setError(tr("未找到对应的物料规格。", "No matching material specification."));
    try {
      const next = mergeAllocationRows(rows.map((item, i) => i !== index ? item : {
        ...item, category: chosen.category, model: chosen.model, language: chosen.language,
        material_record_id: chosen.record_id, order_required: defaultOrderRequired(chosen, Number(item.quantity)),
      }));
      const merged = next.length < rows.length;
      setRows(next);
      if (merged) {
        setEditingUid(next.find(item => item.material_record_id === chosen.record_id)?.uid || null);
        setError(tr("相同规格已合并数量，请核对合并后的明细。", "Matching specifications were merged. Please review the combined quantity."));
      }
    } catch (error) { setError(error instanceof Error ? error.message : "修改失败"); }
  }

  function addRow() {
    const first = nextAllocationMaterial(materials, rows);
    if (!first) return setError(tr("所有物料规格均已在明细中，请直接修改已有明细的数量。", "All specifications are selected. Edit an existing quantity."));
    const uid = crypto.randomUUID();
    setRows([...rows, { uid, line_record_id: "", material_record_id: first.record_id, category: first.category, model: first.model, language: first.language, quantity: 1, remark: "", order_required: defaultOrderRequired(first, 1) }]);
    setEditingUid(uid);
  }

  function openSplit(category: string) {
    const group = rows.filter(row => row.category === category);
    if (!group.length) return;
    setEditingUid(null); setSplitCategory(category); setSplitDrafts({});
    const quantities: Record<string, number> = {};
    group.forEach(row => { quantities[row.material_record_id] = (quantities[row.material_record_id] || 0) + Number(row.quantity || 0); });
    setSplitQuantities(quantities);
  }

  function switchSplitCategory(category: string) {
    if (category === splitCategory) return;
    if (splitCategory) setSplitDrafts(current => ({ ...current, [splitCategory]: { ...splitQuantities } }));
    const quantities = splitDrafts[category] ? { ...splitDrafts[category] } : {};
    if (!splitDrafts[category]) rows.filter(row => row.category === category).forEach(row => { quantities[row.material_record_id] = (quantities[row.material_record_id] || 0) + Number(row.quantity || 0); });
    setSplitCategory(category); setSplitQuantities(quantities);
  }

  function applySplit() {
    if (splitCategory === null) return;
    try {
      let next = rows;
      for (const [category, quantities] of Object.entries({ ...splitDrafts, [splitCategory]: splitQuantities })) {
        const sources = (context.lines || []).filter((line: any) => line.product === category).map((line: any) => String(line.record_id || "")).filter(Boolean);
        next = splitCategoryRows(next, category, quantities, materialById, sources, () => crypto.randomUUID());
      }
      setRows(next); setSplitCategory(null); setSplitDrafts({}); setSplitQuantities({}); setError("");
    } catch (error) { setError(error instanceof Error ? error.message : tr("分装失败", "Unable to split category")); }
  }

  function validate(mode: "confirm" | "edit") {
    if (!context?.verifiedLive) return tr("尚未完成实时核对，不能提交。请先重试实时读取。", "Live verification is required before submission.");
    if (!shipDate) return tr("请选择申请单发货日期。", "Select a shipping date.");
    if (!operatorId) return tr("请选择本次配货操作人。", "Select an allocation operator.");
    if (mode === "edit") {
      if (!rows.length) return tr("配货方案必须至少保留一条物料明细。", "Keep at least one material line.");
      if (rows.some(x => !x.material_record_id || Number(x.quantity) < 1)) return tr("配货方案中存在无效物料或数量。", "The allocation contains an invalid material or quantity.");
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
      draft.lines = rows.map(x => ({ line_record_id: x.line_record_id, split_source_line_id: x.split_source_line_id || "", split_source_line_ids: x.split_source_line_ids || [], material_record_id: x.material_record_id, quantity: Number(x.quantity), remark: x.remark || "", order_required: x.order_required === true }));
    }
    return draft;
  }

  async function submit(mode: "confirm" | "edit") {
    if (submitLockRef.current || withdrawQueued) return;
    const message = validate(mode);
    if (message) return setError(message);
    submitLockRef.current = true;
    setSubmitting(true); setError("");
    try {
      const suffix = directRequestId ? `?${signedQuery}` : "";
      const draft = allocationDraft(mode);
      if (mode === "edit") {
        const normalized = mergeAllocationRows(rows);
        setRows(normalized);
        draft.lines = normalized.map(x => ({ line_record_id: x.line_record_id, split_source_line_id: x.split_source_line_id || "", split_source_line_ids: x.split_source_line_ids || [], material_record_id: x.material_record_id, quantity: Number(x.quantity), remark: x.remark || "", order_required: x.order_required === true }));
      }
      const body = await jsonFetch(`/api/allocation/${encodeURIComponent(requestId)}/submit${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation: mode, draft }) });
      setSuccess(`${tr("配货任务已进入后台队列", "Allocation task queued")}（${body.taskId}）`);
      // Queue acceptance is not inventory-review completion. Keep the request
      // visible until the Worker confirms the write and SQLite removes it.
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败"); }
    finally { setSubmitting(false); submitLockRef.current = false; }
  }

  async function withdrawRequest() {
    if (submitLockRef.current || withdrawQueued) return;
    submitLockRef.current = true;
    setSubmitting(true); setError("");
    try {
      const suffix = directRequestId ? `?${signedQuery}` : "";
      const body = await jsonFetch(`/api/allocation/${encodeURIComponent(requestId)}/withdraw${suffix}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: Number(context.request.inventory_review_version || 0) }),
      });
      setWithdrawQueued(true); setWithdrawConfirm(false);
      setSuccess(`${tr("申请删除任务已提交，完成后会通知申请人与管理员", "Deletion queued. The applicant and administrators will be notified after completion")}（${body.taskId}）`);
    } catch (e) { setWithdrawConfirm(false); setError(e instanceof Error ? e.message : tr("删除申请失败", "Could not delete the request")); }
    finally { setSubmitting(false); submitLockRef.current = false; }
  }

  if (loading) return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`} aria-label={tr("配货工作台", "Allocation Workbench")}><div className="allocation-loading"><i/><b>{tr("正在读取本机待核实申请单……", "Loading local pending requests…")}</b></div></main>;
  if (!requestId || !context) return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`} aria-label={tr("配货工作台", "Allocation Workbench")}>

    {error && <ToastMessage className="allocation-toast" onClick={() => setError("")}>{error} ×</ToastMessage>}
    {pendingWarning && <ToastMessage className="allocation-toast" onClick={() => setPendingWarning("")}>{pendingWarning} ×</ToastMessage>}
    <section className="pending-panel"><div className="pending-head"><h2>{tr("待库存核实申请", "Pending Inventory Reviews")}</h2><span>{pending.length} {tr("条", "requests")}</span><button className="allocation-refresh" onClick={() => loadPending(true)}>↻ {tr("刷新数据", "Refresh data")}</button></div>{pending.length ? <PendingAllocationList requests={pending} lang={lang} onOpen={loadContext} onAnnotate={setFollowup} /> : <div className="allocation-empty">{tr("本机暂无待核实申请；后台会定时与飞书核对。", "No pending requests in the local index; background reconciliation runs periodically.")}</div>}</section>
    {success && <ToastMessage className="allocation-toast" role="status" onClick={() => setSuccess("")}>{success} ×</ToastMessage>}
    {followup && <PendingFollowupDialog key={followup.requestId} request={followup} lang={lang} onClose={() => setFollowup(null)}
      save={(id, body) => jsonFetch(`/api/admin/allocation/${encodeURIComponent(id)}/follow-up`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })}
      onSaved={result => { setPending(items => items.map(item => item.requestId === result.request.requestId ? { ...item, ...result.request } : item)); setFollowup(null); setSuccess(tr("标签和备注已保存。", "Label and note saved.")); }} />}
  </main>;

  const request = context.request;
  const splitGroup = groupByCategory(rows, row => row.category).find(group => group.category === splitCategory);
  const splitOriginals = (context.lines || []).filter((line: any) => line.product === splitCategory);
  const splitBaseQuantity = Math.max(1, splitOriginals.reduce((sum: number, line: any) => sum + Number(line.quantity || 0), 0) || splitGroup?.quantity || 1);
  const splitOptions = materials.filter((item: any) => item.category === splitCategory);
  const splitTotal = Object.values(splitQuantities).reduce((sum, quantity) => sum + Number(quantity || 0), 0);
  return <main className={`allocation-page ${embedded ? "embedded" : "standalone"}`} aria-label={tr("配货工作台", "Allocation Workbench")}>
    {!directRequestId && <div className="allocation-toolbar"><button onClick={() => { contextLoadRef.current += 1; setRequestId(""); setContext(null); loadPending(); }}>← {tr("返回申请单列表", "Back to requests")}</button></div>}
    {error && <ToastMessage className="allocation-toast" onClick={() => setError("")}>{error} ×</ToastMessage>}
    {success && <ToastMessage className="allocation-toast allocation-task-toast" role="status">
      <button type="button" className="allocation-toast-close" aria-label={tr("关闭提示", "Close notification")} onClick={() => setSuccess("")}>×</button>
      <strong>{success}</strong>
      <small>{withdrawQueued ? tr("删除完成后，申请人与管理员将收到撤回通知。", "The applicant and administrators will receive a withdrawal notice after deletion.") : tr("后台完成后，申请人与管理员飞书卡片会按原流程更新。", "The requester and administrator cards will update after background completion.")}</small>
    </ToastMessage>}
    {!context.verifiedLive && <div className="allocation-live-banner" role="status"><span>{liveChecking ? tr("正在核对实时申请明细和库存。下方为历史快照，核对完成前不能提交。", "Checking live request lines and stock. The snapshot below is read-only until verification finishes.") : (liveWarning || tr("当前仅显示历史快照，不能提交。", "Showing a read-only snapshot."))}</span>{!liveChecking && <button onClick={() => loadContext(requestId)}>{tr("重试实时读取", "Retry live verification")}</button>}</div>}
    {request.inventory_review_status === "已核实库存" ? <div className="allocation-success">✓ {tr("该申请已经完成库存核实，无需再次处理。", "This request has already completed inventory review.")}</div> : <>
      <section className="request-overview">
        <div className="allocation-title">
          <div className="allocation-request-heading"><b>{request.request_no || "-"}</b><span>{context.verifiedLive ? tr("实时库存更新于", "Live stock updated at") : tr("历史快照更新于", "Snapshot updated at")} {context.snapshotAt}</span></div>
          <div className="allocation-arrival"><span>{tr("物料要求到达时间", "Required Material Arrival")}</span><strong>{requiredArrivalText(request, lang)}</strong></div>
        </div>
        <div className="allocation-metrics"><span>{tr("申请人", "Requester")}<b>{request.requester || "-"}</b></span><span>{tr("申请部门", "Department")}<b>{request.department || "-"}</b></span><span>{tr("当前结论", "Current Result")}<b>{context.result || "-"}</b></span><span>{tr("变更次数", "Changes")}<b>{request.inventory_review_version || 0}</b></span><span>{tr("原申请总金额", "Original Total")}<b>{money(originalTotal)}</b></span></div><div className="request-notes"><p><b>{tr("申请原因", "Reason")}：</b>{request.request_reason || "-"}</p><p><b>{tr("物料用途", "Usage")}：</b>{request.material_usage || "-"}</p><p><b>{tr("收件人信息", "Recipient")}：</b>{request.recipient_info || "-"}</p></div>
      </section>
      <div className="allocation-withdraw-action"><button className="withdraw-request" disabled={submitting || withdrawQueued} onClick={() => setWithdrawConfirm(true)}>{withdrawQueued ? tr("删除任务已提交", "Deletion queued") : tr("删除申请", "Delete Request")}</button></div>
      <fieldset className="allocation-readonly-guard" disabled={!context.verifiedLive || withdrawQueued}>
      <section className="allocation-form"><div className="allocation-control"><label><span className="field-label">{tr("申请单发货日期", "Shipping Date")}<RequiredMark /></span><input type="date" value={shipDate} onChange={e => setShipDate(e.target.value)}/></label>{!context.signedCardAccess && <label><span className="field-label">{tr("本次配货操作人", "Allocation Operator")}<RequiredMark /></span><select value={operatorId} onChange={e => setOperatorId(e.target.value)}><option value="">{tr("请选择管理员", "Select administrator")}</option>{operators.map(x => <option key={x.open_id} value={x.open_id}>{x.name} · {(x.department_paths || []).join(" / ")}</option>)}</select></label>}</div>
        <div className="allocation-section-title"><div><h2>{tr("配货明细", "Allocation Lines")}</h2><p>{usesLiveData() ? tr("品类、型号、语种和库存均为本次飞书实时读取。", "Category, model, language and stock were read live from Feishu.") : context.verifiedLive ? tr(`品类、型号和语种来自页面缓存（${context.cacheGeneratedAt || "未知时间"}）；库存来自本次实时读取。`, `Options use the page cache (${context.cacheGeneratedAt || "unknown"}); stock is live.`) : tr("当前为历史快照，库存尚未实时核对。", "This is a snapshot; stock has not been verified live.")}</p></div><button className="confirm-original" disabled={submitting} onClick={() => submit("confirm")}>✓ {tr("按原申请提交配货方案", "Submit Original Allocation")}</button></div>
        <div className="allocation-table-toolbar"><strong>{rows.length} {tr("条明细", "lines")}</strong><span>{canEdit ? tr("按品类分组查看；点击组内明细调整规格和数量，或点击整组分装。", "Select a line to edit its material, quantity or split allocation.") : tr("完成实时核对后可调整明细。", "Editing is available after live verification.")}</span></div>
        <div className="allocation-table-scroll" role="region" aria-label={tr("配货明细表，可左右滚动", "Allocation lines, horizontally scrollable")} tabIndex={0}>
          <table className="allocation-detail-table">
            <caption className="allocation-sr-only">{tr("配货明细，按 Enter 或空格打开所选行", "Allocation lines. Press Enter or Space to edit a focused row.")}</caption>
            <thead><tr><th scope="col">#</th><th scope="col">{tr("物料品类", "Material")}</th><th scope="col">{tr("型号 / 语种", "Model / Language")}</th><th scope="col" className="numeric">{tr("数量", "Qty")}</th><th scope="col" className="numeric">{context.verifiedLive ? tr("实时库存", "Live Stock") : tr("快照库存", "Snapshot Stock")}</th><th scope="col" className="numeric">{tr("在途", "In Transit")}</th><th scope="col" className="numeric">{tr("单价", "Unit Price")}</th><th scope="col" className="numeric">{tr("小计", "Subtotal")}</th><th scope="col">{tr("下单", "Order")}</th><th scope="col">{tr("备注", "Remark")}</th><th scope="col"><span className="allocation-sr-only">{tr("操作", "Actions")}</span></th></tr></thead>
            <tbody><CategoryRows items={rows} category={row => row.category} lang={lang} columns={11} actions={group => <button type="button" disabled={!canEdit} onClick={() => openSplit(group.category)}>{tr("整组分装", "Split category")}</button>} render={(row, index, displayIndex) => {
              const material = materialById[row.material_record_id] || {};
              const low = Number(material.quantity || 0) < Number(row.quantity);
              return <tr key={row.uid} className={`${low ? "stock-shortage" : ""} ${editingUid === row.uid ? "is-selected" : ""}`} tabIndex={canEdit ? 0 : -1} aria-disabled={!canEdit} aria-label={`${index + 1}. ${row.category} / ${row.model} / ${row.language}`} onClick={() => openLine(row.uid)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); openLine(row.uid); } }}>
                <td className="line-number">{displayIndex + 1}</td>
                <th scope="row" className="material-cell"><span>{row.category}</span>{row.split_source_line_id ? <small className="line-origin">{tr("分装", "Split")}</small> : !row.line_record_id && <small className="line-origin">{tr("新增", "New")}</small>}</th>
                <td className="spec-cell"><strong>{row.model}</strong><small>{row.language}</small></td>
                <td className="numeric line-quantity">{row.quantity}</td>
                <td className={`numeric ${low ? "low" : ""}`}>{Number(material.quantity || 0)}{low && <small>{tr("不足", "Short")}</small>}</td>
                <td className="numeric">{Number(material.in_transit_quantity || 0)}</td>
                <td className="numeric">{money(material.unit_price_rmb || 0)}</td>
                <td className="numeric line-subtotal">{money(Number(material.unit_price_rmb || 0) * Number(row.quantity || 0))}</td>
                <td><span className={`order-indicator ${isPrintMaterial(material) && row.order_required ? "required" : ""}`}>{isPrintMaterial(material) && row.order_required ? tr("需要下单", "Required") : tr("无需下单", "No order")}</span></td>
                <td className="line-remark" title={row.remark || ""}>{row.remark || "-"}</td>
                <td><button type="button" className="edit-allocation-line" disabled={!canEdit} onClick={event => { event.stopPropagation(); openLine(row.uid); }}>{tr("调整", "Edit")}</button></td>
              </tr>;
            }} /></tbody>
          </table>
        </div>
        <p className="allocation-table-mobile-hint">{tr("左右滑动查看完整信息，点击行进行调整。", "Swipe horizontally for all columns. Select a line to edit.")}</p>
        <button className="add-allocation-line" onClick={addRow}>＋ {tr("新增明细", "Add Line")}</button>
        <div className="amount-comparison"><span>{tr("原申请总金额", "Original Total")}<b>{money(originalTotal)}</b></span><span>{tr("当前配货总金额", "Allocation Total")}<b>{money(currentTotal)}</b><em className={currentTotal - originalTotal < 0 ? "negative" : ""}>{currentTotal - originalTotal >= 0 ? "+" : ""}{money(currentTotal - originalTotal)}</em></span></div>
        <label className="change-note"><span className="field-label">{tr("配货调整说明", "Allocation Change Note")}<RequiredMark /></span><textarea placeholder={tr("请说明替换、增加、删除物料或调整数量的原因；该说明会发送给申请人。", "Explain replacements, additions, deletions, or quantity changes. This will be sent to the requester.")} value={changeNote} onChange={e => setChangeNote(e.target.value)}/></label>
        <label className="allocation-ack"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>{tr("我已核对配货方案，并确认向申请人发送变更通知", "I reviewed this plan and confirm notifying the requester")}</label>
        <button className="submit-allocation" disabled={!ack || submitting} onClick={() => submit("edit")}>{tr("提交配货方案", "Submit Allocation Plan")}</button>
      </section>
      </fieldset>
    </>}
    <dialog className="allocation-line-editor" ref={editorRef} aria-labelledby="allocation-line-editor-title" onCancel={() => setEditingUid(null)} onClose={() => setEditingUid(null)} onClick={event => { if (event.target === event.currentTarget) setEditingUid(null); }}>
      {editingRow && <div className="allocation-editor-panel">
        <div className="allocation-editor-heading"><div><small>{tr("明细", "Line")} {editingIndex + 1} / {rows.length}</small><h2 id="allocation-line-editor-title">{tr("调整配货明细", "Edit Allocation Line")}</h2></div><button type="button" className="editor-close" aria-label={tr("关闭明细调整", "Close line editor")} onClick={() => setEditingUid(null)}>×</button></div>
        <p className="allocation-editor-hint">{tr("调整暂存在当前方案，提交配货方案后才会写入。", "Edits stay in this draft until you submit the allocation plan.")}</p>
        <div className="allocation-editor-body">
          <fieldset disabled={!canEdit} className="allocation-editor-fields">
            <label>{tr("物料品类", "Material Category")}<select value={editingRow.category} onChange={event => selectMaterial(editingIndex, "category", event.target.value)}>{categories.map(value => <option key={value}>{value}</option>)}</select></label>
            <div className="allocation-editor-specs">
              <label>{tr("型号", "Model")}<select value={editingRow.model} onChange={event => selectMaterial(editingIndex, "model", event.target.value)}>{editorModels.map(value => <option key={value}>{value}</option>)}</select></label>
              <label>{tr("语种", "Language")}<select value={editingRow.language} onChange={event => selectMaterial(editingIndex, "language", event.target.value)}>{editorLanguages.map(value => <option key={value}>{value}</option>)}</select></label>
            </div>
            <div className="allocation-editor-specs">
              <label>{tr("配货数量", "Allocation Quantity")}<input type="number" min="1" step="1" value={editingRow.quantity} onChange={event => { const quantity = Math.max(1, Math.floor(Number(event.target.value) || 1)); setRows(current => current.map(row => row.uid === editingUid ? { ...row, quantity, order_required: canOrder ? row.order_required : false } : row)); }}/></label>
              <label>{tr("是否下单", "Order Required")}<select disabled={!canOrder} value={canOrder && editingRow.order_required ? "yes" : "no"} onChange={event => setRows(current => current.map(row => row.uid === editingUid ? { ...row, order_required: canOrder && event.target.value === "yes" } : row))}>{canOrder && <option value="yes">{tr("需要下单", "Order")}</option>}<option value="no">{tr("无需下单", "No Order")}</option></select></label>
            </div>
            <div className="allocation-editor-stock"><span>{tr("实时库存", "Live Stock")}<b className={Number(editingMaterial.quantity || 0) < Number(editingRow.quantity) ? "low" : ""}>{Number(editingMaterial.quantity || 0)}</b></span><span>{tr("在途库存", "In Transit")}<b>{Number(editingMaterial.in_transit_quantity || 0)}</b></span><span>{tr("单价", "Unit Price")}<b>{money(editingMaterial.unit_price_rmb || 0)}</b></span></div>
            <label>{tr("备注", "Remark")}<textarea aria-label={tr("备注", "Remark")} rows={3} value={editingRow.remark} onChange={event => setRows(current => current.map(row => row.uid === editingUid ? { ...row, remark: event.target.value } : row))}/></label>
            <div className="allocation-editor-line-total"><span>{tr("当前明细小计", "Line Subtotal")}</span><b>{money(Number(editingMaterial.unit_price_rmb || 0) * Number(editingRow.quantity || 0))}</b></div>
            <div className="allocation-editor-actions"><button type="button" className="split-line-button" onClick={() => openSplit(editingRow.category)}>{tr("分装整个品类", "Split entire category")}</button><button type="button" className="delete-allocation-line" disabled={rows.length <= 1} title={rows.length <= 1 ? tr("至少保留一条明细", "Keep at least one line") : undefined} onClick={() => removeLine(editingRow.uid)}>{tr("删除此明细", "Delete Line")}</button></div>
          </fieldset>
        </div>
        <footer className="allocation-editor-footer"><button type="button" onClick={() => setEditingUid(null)}>{tr("完成调整", "Done Editing")}</button></footer>
      </div>}
    </dialog>
    {splitGroup && <div className="allocation-modal-backdrop" onMouseDown={() => setSplitCategory(null)}>
      <div className="allocation-modal split-modal" role="dialog" aria-modal="true" aria-label={tr("按品类整组分装", "Split entire category")} onMouseDown={event => event.stopPropagation()}>
        <button className="close" aria-label={tr("关闭", "Close")} onClick={() => setSplitCategory(null)}>×</button>
        <h2>{tr("按品类整组分装", "Split Entire Category")}</h2>
        <p className="split-intro">{splitGroup.category} · {splitGroup.entries.length} {tr("条本批明细", "lines in this plan")} · {tr("原申请", "Originally requested")} {splitBaseQuantity} {tr("件", "items")}</p>
        <p className="split-hint">{tr("在下方框选池选择型号，在上方表格修改语种、数量和比例。已选型号标蓝，切换品类保留修改。", "Choose models in the pool below, then edit languages, quantities and percentages in the selected table above. Category changes keep your draft.")}</p>
        <div className="split-category-cards" aria-label={tr("本批申请品类", "Request categories")}>
          {groupByCategory(rows, row => row.category).map(group => {
            const picture = context.categoryImages?.[group.category]?.[0];
            return <button type="button" key={group.category} className={`split-category-card${group.category === splitCategory ? " chosen" : ""}`} aria-pressed={group.category === splitCategory} onClick={() => switchSplitCategory(group.category)}>
              {picture ? <img src={picture} alt="" loading="lazy" /> : <span className="split-category-placeholder">PUDU</span>}
              <strong>{group.category}</strong><small>{tr(`${group.entries.length} 条 · ${group.quantity} 件`, `${group.entries.length} lines · ${group.quantity} items`)}</small>
            </button>;
          })}
        </div>
        <SplitSelectionEditor options={splitOptions} quantities={splitQuantities} total={splitBaseQuantity} lang={lang} onChange={setSplitQuantities} />
        <div className="split-totals"><span>{tr("原申请", "Original")}: <b>{splitBaseQuantity}</b></span><span>{tr("分装后", "After split")}: <b>{splitTotal}</b></span><span>{tr("差额", "Difference")}: <b>{splitTotal - splitBaseQuantity > 0 ? "+" : ""}{splitTotal - splitBaseQuantity}</b></span></div>
        <div className="modal-actions"><button onClick={() => setSplitCategory(null)}>{tr("取消", "Cancel")}</button><button className="primary" onClick={applySplit}>{tr("应用分装修改", "Apply split changes")}</button></div>
      </div>
    </div>}
    {withdrawConfirm && <div className="allocation-modal-backdrop" onMouseDown={() => !submitting && setWithdrawConfirm(false)}><div className="allocation-modal" role="dialog" aria-modal="true" aria-labelledby="withdraw-title" onMouseDown={e => e.stopPropagation()}><h2 id="withdraw-title">{tr("删除申请", "Delete Request")}</h2><p><b>{request.request_no}</b> · {request.requester}</p><p>{tr("确认删除该申请单及全部申请明细？删除完成后，将向申请人与已启用管理员发送撤回通知。", "Delete this request and all its lines? The applicant and enabled administrators will receive a withdrawal notice after deletion.")}</p><div className="modal-actions"><button autoFocus disabled={submitting} onClick={() => setWithdrawConfirm(false)}>{tr("取消", "Cancel")}</button><button className="withdraw-request" disabled={submitting} onClick={withdrawRequest}>{tr("确认删除", "Delete Request")}</button></div></div></div>}
    {submitting && <div className="allocation-submit-overlay"><i/><b>{withdrawConfirm ? tr("正在提交删除任务……", "Submitting deletion task…") : tr("正在提交配货方案，请稍后……", "Submitting allocation plan…")}</b><span>{tr("任务正在进入后台队列，请勿重复提交", "The task is entering the background queue")}</span></div>}
  </main>;
}
