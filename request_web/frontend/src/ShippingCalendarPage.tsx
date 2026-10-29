import ToastMessage from "./ToastMessage";
import { useDatabaseRefresh } from './useDatabaseRefresh';
import { groupByCategory } from "./categoryGroups";
import { CategoryRows } from "./CategoryGroups";
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CategoryImageEditor from './CategoryImageEditor';
import RequiredMark from './RequiredMark';
import { shippingDraft as editDraft, draftSignature as editSignature, stageShippingDraft, shippingBatchChanges, chinaToday, groupRequests, matchesSearch, monthDays, shiftMonth, urgency } from './shippingCalendar';
import type { DateBasis, ShippingRequest, ShippingDraft as Draft, ShippingStaging } from './shippingCalendar';
import './shipping-calendar.css';

type Lang = 'zh' | 'en';
async function jsonFetch(url: string, options?: RequestInit) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (response.status === 401) throw Error('登录已过期，请重新通过飞书登录。 / Please sign in again.');
  if (!response.headers.get('content-type')?.includes('application/json')) throw Error('未能读取服务器响应，请刷新后重试。 / Please refresh and try again.');
  const body = await response.json();
  if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail : '读取或保存失败 / Request failed');
  return body;
}

export default function ShippingCalendarPage({ lang, active = true, editable = false }: { lang: Lang; active?: boolean; editable?: boolean }) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const today = chinaToday();
  const [serverCanEdit, setServerCanEdit] = useState(false);
  const [automaticShipping, setAutomaticShipping] = useState(false);
  const applicantView = new URLSearchParams(window.location.search).get('shipping_view') === 'readonly';
  const canEdit = editable && serverCanEdit && !applicantView;
  const [requests, setRequests] = useState<ShippingRequest[]>([]);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [basis, setBasis] = useState<DateBasis>('ship_date');
  const [day, setDay] = useState('');
  const [allDates, setAllDates] = useState(false);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<ShippingRequest | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [staged, setStaged] = useState<ShippingStaging>({});
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [batchError, setBatchError] = useState('');
  const confirmDialog = useRef<HTMLDialogElement>(null);
  const [uploading, setUploading] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [confirmClose, setConfirmClose] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const saveAttempt = useRef<{ signature: string; token: string } | null>(null);
  const loadGeneration = useRef(0);
  const directRequestOpened = useRef(false);
  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true); setError('');
    try {
      const data = await jsonFetch(applicantView ? '/api/shipping-calendar?view=applicant' : '/api/shipping-calendar');
      if (generation === loadGeneration.current) { setRequests(data.requests); setServerCanEdit(data.can_edit === true); setAutomaticShipping(data.automatic_shipping === true); }
      return data.requests as ShippingRequest[];
    } catch (e) {
      if (generation === loadGeneration.current) setError(e instanceof Error ? e.message : '读取失败 / Failed to load');
      return null;
    } finally { if (generation === loadGeneration.current) setLoading(false); }
  }, [applicantView]);
  useEffect(() => { void load(); return () => { ++loadGeneration.current; }; }, [load]);
  // Revision checks refresh visible data every three seconds without replacing an edit draft.
  useDatabaseRefresh(async () => {
    if (!active || document.hidden || saving || (selected && canEdit)) return;
    const rows = await load();
    if (selected && !canEdit) {
      const current = rows?.find(row => row.request_id === selected.request_id);
      if (current) { setSelected(current); setDraft(editDraft(current)); }
    }
  });
  useEffect(() => {
    if (selected && dialog.current && !dialog.current.open) dialog.current.showModal();
    if (!selected && dialog.current?.open) dialog.current.close();
  }, [selected]);
  useEffect(() => {
    if (loading || directRequestOpened.current || selected) return;
    directRequestOpened.current = true;
    const key = new URLSearchParams(window.location.search).get('shipping_request');
    const request = requests.find(item => item.request_id === key);
    if (request) { setSelected(request); setDraft(editDraft(request)); }
  }, [loading, requests, selected]);
  const previewRequests = useMemo(() => requests.map(request => staged[request.request_id] ? { ...request, ...staged[request.request_id].draft } : request), [requests, staged]);
  const matches = useMemo(() => previewRequests.filter(request => matchesSearch(request, search)), [previewRequests, search]);
  const stagedEntries = Object.values(staged);
  useEffect(() => {
    if (confirmSubmit && confirmDialog.current && !confirmDialog.current.open) confirmDialog.current.showModal();
    if (!confirmSubmit && confirmDialog.current?.open) confirmDialog.current.close();
  }, [confirmSubmit]);
  const datedInMonth = matches.filter(request => request[basis].startsWith(month));
  const visible = matches.filter(request => allDates || (day ? request[basis] === day : !request[basis] || request[basis].startsWith(month)));
  const pending = visible.filter(request => !request.shipped);
  const shipped = visible.filter(request => request.shipped);
  const overdue = matches.filter(request => urgency(request, today) === 'overdue').length;
  const undated = matches.filter(request => !request[basis]).length;
  const days = monthDays(month);
  const offset = (new Date(`${month}-01T00:00:00Z`).getUTCDay() + 6) % 7;
  const totals = new Map(days.map(date => [date, { pending: datedInMonth.filter(r => r[basis] === date && !r.shipped).length, shipped: datedInMonth.filter(r => r[basis] === date && r.shipped).length }]));
  const formatDay = (value: string, weekday = false) => value ? new Intl.DateTimeFormat(lang === 'zh' ? 'zh-CN' : 'en-GB', { month: 'short', day: 'numeric', ...(weekday ? { weekday: 'short' as const } : {}), timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : tr('未设置', 'Not set');
  const dirty = Boolean(selected && draft && editSignature(draft) !== editSignature(staged[selected.request_id]?.draft || editDraft(selected)));
  useEffect(() => {
    if (!dirty && stagedEntries.length === 0 && !uploading && !saving) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, stagedEntries.length, uploading, saving]);
  function open(request: ShippingRequest) {
    const entry = staged[request.request_id];
    setSelected(entry?.base || request); setDraft(entry?.draft || editDraft(request)); setSaveError(''); setConfirmClose(false);
  }
  function close(force = false) {
    if (saving || uploading) return;
    if (dirty && !force) { setConfirmClose(true); return; }
    setSelected(null); setDraft(null); setConfirmClose(false); setSaveError('');
  }
  function save() {
    if (!canEdit || !selected || !draft || saving || uploading) return;
    setStaged(current => stageShippingDraft(current, selected, draft));
    setSelected(null); setDraft(null); setSaveError('');
    setNotice(tr('修改已暂存，完成编辑后请点击“统一提交修改”。', 'Edits staged. Choose “Submit all changes” when ready.'));
  }
  async function submitBatch() {
    if (!canEdit || saving || stagedEntries.length === 0) return;
    const changes = shippingBatchChanges(staged);
    const signature = JSON.stringify(changes);
    if (saveAttempt.current?.signature !== signature) saveAttempt.current = { signature, token: crypto.randomUUID() };
    setSaving(true); setBatchError('');
    try {
      const result = await jsonFetch('/api/admin/shipping-calendar/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ changes, confirmed: true, idempotency_key: saveAttempt.current.token }) });
      setRequests(current => current.map(request => staged[request.request_id] ? { ...request, ...staged[request.request_id].draft, sync_state: 'pending', notification: { state: 'pending', error: '' } } : request));
      setStaged({}); setConfirmSubmit(false); saveAttempt.current = null;
      setNotice(tr(`已提交 ${result.changed} 张申请单，飞书更新成功后将同步通知申请人。`, `${result.changed} requests submitted. Applicants will be notified after Feishu updates succeed.`));
      void load();
    } catch (e) { setBatchError(e instanceof Error ? e.message : tr('提交失败，暂存修改仍保留。', 'Submission failed. Your staged edits are retained.')); }
    finally { setSaving(false); }
  }
  function removeStaged(id: string) { setStaged(current => { const updated = { ...current }; delete updated[id]; return updated; }); }
  async function reloadSelected() {
    if (!selected) return;
    setSaveError('');
    const current = await load();
    const latest = current?.find(request => request.request_id === selected.request_id);
    if (latest) { removeStaged(selected.request_id); setSelected(latest); setDraft(editDraft(latest)); setSaveError(''); }
    else setSaveError(tr('该申请单已不在发货日历中，或数据读取失败，请关闭窗口并刷新。', 'This request is no longer available, or loading failed. Close and refresh.'));
  }
  function changeMonth(step: number) { setMonth(value => shiftMonth(value, step)); setDay(''); setAllDates(false); }
  function card(request: ShippingRequest) {
    const urgent = urgency(request, today);
    return <button type="button" className={`sc-card ${request.shipped ? 'is-shipped' : ''} ${urgent ? `is-${urgent}` : ''}`} key={request.request_id} onClick={() => open(request)}>
      <span className="sc-card-top"><strong>{request.request_no}{staged[request.request_id] && <em className="sc-staged-tag">{tr('未提交', 'Draft')}</em>}</strong><span className={`sc-status ${request.shipped ? 'done' : 'waiting'}`}>{request.shipped ? tr('已发货', 'Shipped') : tr('未发货', 'Not shipped')}</span></span>
      <span className="sc-person"><b>{request.requester || '—'}</b><span>{[request.department, request.country].filter(Boolean).join(' · ')}</span></span>
      {(request.usage || request.customer) && <span className="sc-purpose">{[request.usage, request.customer].filter(Boolean).join(' · ')}</span>}
      <span className="sc-card-dates"><span>{tr('计划发货', 'Planned ship')}<b>{formatDay(request.ship_date)}</b></span><span>{tr('要求到达', 'Arrival from')}<b>{formatDay(request.arrival_start)}</b></span></span>
      <span className="sc-line-summary">{groupByCategory(request.lines, line => line.product, line => line.approved_quantity || line.quantity).slice(0, 2).map(group => <span key={group.category}>{group.category || tr('物料', 'Material')}<small>{tr(`${group.entries.length} 条明细`, `${group.entries.length} lines`)}</small><b>× {group.quantity}</b></span>)}</span>
      {!request.lines.length && request.detail_text && <span className="sc-purpose">{request.detail_text}</span>}
      <span className="sc-card-footer"><span>{tr(`${request.lines.length} 项物料`, `${request.lines.length} items`)}{request.images.length > 0 && ` · ${tr(`${request.images.length} 张发货图片`, `${request.images.length} photos`)}`}</span>
        {urgent && <b className="sc-urgent">{urgent === 'overdue' ? tr('计划发货日已过', 'Past planned ship date') : tr('今日待发', 'Ship today')}</b>}
        {!urgent && request.sync_state === 'pending' && <span>{tr('待同步', 'Sync pending')}</span>}
        {request.sync_state === 'conflict' && <b className="sc-urgent">{tr('同步需核对', 'Sync needs review')}</b>}
      </span>
      {request.notification && !staged[request.request_id] && <span title={request.notification.error || undefined} className={`sc-notification-state ${['failed','blocked'].includes(request.notification.state) ? 'failed' : ''}`}>{request.notification.state === 'waiting_approval' ? tr('待审批通过后通知', 'Awaiting approval') : request.notification.state === 'waiting_information' ? tr('待填写物流信息', 'Shipping details required') : request.notification.state === 'done' ? tr('申请人已通知', 'Applicant notified') : request.notification.state === 'blocked' ? tr('飞书同步需核对，尚未通知申请人', 'Feishu sync needs review; applicant not notified') : request.notification.state === 'failed' ? tr('申请人通知失败，需核对', 'Applicant notification failed') : tr('申请人待通知', 'Applicant notification pending')}</span>}
      {request.shipping_text && <span className="sc-tracking">{request.shipping_text}</span>}
    </button>;
  }
  return <section className="shipping-calendar" aria-label={tr('物料发货日历', 'Material Shipping Calendar')}>

    {canEdit && stagedEntries.length > 0 && <div className="sc-batch-bar" role="status"><div><strong>{tr(`${stagedEntries.length} 张申请单有暂存修改`, `${stagedEntries.length} requests have staged changes`)}</strong><span>{tr('点击统一提交，确认后同步飞书并通知申请人。', 'Submit together to update Feishu and notify applicants.')}</span><div className="sc-draft-list">{stagedEntries.map(({ base }) => <span className="sc-draft-chip" key={base.request_id}><button type="button" disabled={saving} onClick={() => open(base)}>{base.request_no}</button><button type="button" disabled={saving} aria-label={tr(`撤销 ${base.request_no} 的暂存修改`, `Discard staged edits for ${base.request_no}`)} onClick={() => removeStaged(base.request_id)}>×</button></span>)}</div></div><button type="button" disabled={saving} onClick={() => { if (window.confirm(tr('放弃全部暂存修改？', 'Discard all staged changes?'))) setStaged({}); }}>{tr('放弃全部', 'Discard all')}</button><button type="button" className="primary" disabled={saving || uploading} onClick={() => { setBatchError(''); setConfirmSubmit(true); }}>{tr('统一提交修改', 'Submit all changes')}</button></div>}
    {notice && <ToastMessage className="sc-notice" role="status">{notice}<button type="button" onClick={() => setNotice('')} aria-label={tr('关闭提示', 'Dismiss')}>×</button></ToastMessage>}
    {error && <ToastMessage className="sc-error" role="alert">{error}<button type="button" onClick={() => void load()}>{tr('重试', 'Retry')}</button></ToastMessage>}
    <div className="sc-filters"><label><span>{tr('搜索申请单', 'Search requests')}</span><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={tr('单号、申请人、物料或发货信息', 'Number, requester, item or tracking info')} /></label>
      <label><span>{tr('日期依据', 'Date basis')}</span><select value={basis} onChange={e => { setBasis(e.target.value as DateBasis); setDay(''); }}><option value="ship_date">{tr('计划发货日', 'Planned ship date')}</option><option value="arrival_start">{tr('要求到达开始日', 'Required arrival start')}</option></select></label>
      <button type="button" className={allDates ? 'active' : ''} aria-pressed={allDates} onClick={() => { setAllDates(value => !value); setDay(''); }}>{tr('全部日期', 'All dates')}</button><button type="button" onClick={() => void load()} disabled={loading}>{loading ? tr('读取中…', 'Loading…') : tr('刷新', 'Refresh')}</button>
    </div>
    <div className="sc-layout">
      <aside className="sc-month-panel" aria-label={tr('日期筛选', 'Date filter')}>
        <div className="sc-month-nav"><button type="button" onClick={() => changeMonth(-1)} aria-label={tr('上个月', 'Previous month')}>‹</button><strong>{new Intl.DateTimeFormat(lang === 'zh' ? 'zh-CN' : 'en-GB', { year: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${month}-01T00:00:00Z`))}</strong><button type="button" onClick={() => changeMonth(1)} aria-label={tr('下个月', 'Next month')}>›</button></div>
        <div className="sc-calendar-week">{(lang === 'zh' ? ['一', '二', '三', '四', '五', '六', '日'] : ['M', 'T', 'W', 'T', 'F', 'S', 'S']).map((name, index) => <span key={index}>{name}</span>)}</div>
        <div className="sc-calendar-grid">{Array.from({ length: offset }, (_, index) => <span key={`blank-${index}`} />)}{days.map(date => {
          const count = totals.get(date)!;
          return <button type="button" key={date} className={`${day === date && !allDates ? 'selected' : ''} ${date === today ? 'today' : ''}`} aria-pressed={day === date && !allDates} aria-label={`${date}, ${tr(`未发货 ${count.pending}，已发货 ${count.shipped}`, `${count.pending} not shipped, ${count.shipped} shipped`)}`} onClick={() => { setDay(value => value === date ? '' : date); setAllDates(false); }}>
            <span>{Number(date.slice(-2))}</span><small>{count.pending > 0 && <i className="pending">{count.pending}</i>}{count.shipped > 0 && <i className="shipped">{count.shipped}</i>}</small>
          </button>;
        })}</div>
        <div className="sc-legend"><span><i className="pending" />{tr('未发货', 'Not shipped')}</span><span><i className="shipped" />{tr('已发货', 'Shipped')}</span></div>
        <div className="sc-date-actions"><button type="button" onClick={() => { setMonth(today.slice(0, 7)); setDay(''); setAllDates(false); }}>{tr('回到本月', 'This month')}</button><button type="button" onClick={() => { setDay(''); setAllDates(false); }}>{tr('显示整月', 'Whole month')}</button></div>
        <div className="sc-month-notes"><span>{tr('待发逾期', 'Past planned ship date')}<b>{overdue}</b></span><span>{tr('未设置当前依据日期', 'Missing selected date')}<b>{undated}</b></span></div>
        {(overdue > 0 || undated > 0) && <button type="button" className="sc-see-all" onClick={() => { setAllDates(true); setDay(''); }}>{tr('查看全部待处理申请', 'View all requests')}</button>}
      </aside>
      <div className="sc-board-wrap">
        <div className="sc-range"><strong>{allDates ? tr('全部日期', 'All dates') : day ? formatDay(day, true) : tr('本月及未设置日期', 'This month + unscheduled')}</strong><span>{tr(`${visible.length} 张申请单`, `${visible.length} requests`)}</span></div>
        {loading && requests.length === 0 ? <div className="sc-empty" role="status">{tr('正在读取申请单…', 'Loading requests…')}</div> : <div className="sc-board">{[{ label: tr('未发货', 'Not shipped'), data: pending, done: false }, { label: tr('已发货', 'Shipped'), data: shipped, done: true }].map(lane => <section key={lane.label} className={`sc-lane ${lane.done ? 'done' : 'waiting'}`} aria-label={lane.label}>
          <h3><span><i />{lane.label}</span><b>{lane.data.length}</b></h3>
          {lane.data.length === 0 && <div className="sc-empty">{tr('当前范围内暂无申请单', 'No requests in this range')}</div>}
          {groupRequests(lane.data, basis).map(([date, items]) => <div className="sc-day-group" key={date}><h4>{date ? formatDay(date, true) : tr('未设置日期', 'Unscheduled')}<span>{items.length}</span></h4>{items.map(card)}</div>)}
        </section>)}</div>}
      </div>
    </div>
    <dialog ref={dialog} className="sc-dialog" aria-labelledby="sc-dialog-title" onCancel={event => { event.preventDefault(); close(); }}>
      {selected && draft && <>
        <header className="sc-dialog-heading"><div><span className={`sc-status ${selected.shipped ? 'done' : 'waiting'}`}>{selected.shipped ? tr('已发货', 'Shipped') : tr('未发货', 'Not shipped')}</span><h2 id="sc-dialog-title">{selected.request_no}</h2><p>{selected.requester} · {selected.department}</p></div><button type="button" onClick={() => close()} disabled={saving || uploading} aria-label={tr('关闭详情', 'Close details')}>×</button></header>
        <div className="sc-dialog-body">
          <dl className="sc-facts"><div><dt>{tr("审批状态", "Approval")}</dt><dd>{({ APPROVED: tr("已通过", "Approved"), PENDING: tr("审批中", "Pending"), REJECTED: tr("已驳回", "Rejected"), CANCELED: tr("已撤回", "Canceled") } as Record<string,string>)[selected.approval_status || ""] || selected.status}</dd></div><div><dt>{tr('计划发货日', 'Planned ship date')}</dt><dd>{selected.ship_date || '—'}</dd></div><div><dt>{tr('要求到达时间', 'Required arrival')}</dt><dd>{selected.arrival_start || '—'}{selected.arrival_end && selected.arrival_end !== selected.arrival_start ? ` – ${selected.arrival_end}` : ''}</dd></div><div><dt>{tr('客户 / 国家', 'Customer / country')}</dt><dd>{[selected.customer, selected.country].filter(Boolean).join(' / ') || '—'}</dd></div><div><dt>{tr('申请原因 / 用途', 'Reason / usage')}</dt><dd>{[selected.reason, selected.usage].filter(Boolean).join(' / ') || '—'}</dd></div><div className="wide"><dt>{tr('收件人信息', 'Recipient details')}</dt><dd>{selected.recipient || '—'}</dd></div></dl>
          <section className="sc-details"><h3>{tr('申请明细', 'Request details')}<span>{selected.lines.length}</span></h3><div className="sc-detail-table"><table><thead><tr><th>{tr('物料 / 型号 / 语种', 'Item / model / language')}</th><th>{tr('申请', 'Requested')}</th><th>{tr('核准', 'Approved')}</th><th>{tr('已发放', 'Issued')}</th></tr></thead><tbody><CategoryRows items={selected.lines} category={line => line.product} lang={lang} columns={4} render={line => <tr key={line.id}><td><strong>{line.product || '—'}</strong><span>{[line.model, line.language].filter(Boolean).join(' / ')}</span>{line.remark && <small>{line.remark}</small>}</td><td>{line.quantity}</td><td>{line.approved_quantity}</td><td>{line.issued_quantity}</td></tr>} /></tbody></table></div>{selected.lines.length === 0 && <p className="sc-prewrap">{selected.detail_text || tr('暂无结构化明细', 'No item details available')}</p>}</section>
          <fieldset className="sc-editor" disabled={!canEdit || saving || uploading}><legend>{tr('发货信息', 'Shipping details')}</legend>{canEdit && <label className="sc-date-editor"><span>{tr('物料发货日期', 'Material shipping date')}{selected.ship_date && <RequiredMark />}</span><input type="date" required={Boolean(selected.ship_date)} value={draft.ship_date} onChange={e => { const value = e.target.value; setDraft(current => current && { ...current, ship_date: value }); }} /></label>}<label className="sc-tracking-input"><span>{tr('发货单号及文字信息', 'Tracking number and shipping notes')}</span><textarea rows={4} maxLength={20000} value={draft.shipping_text} onChange={e => { const value = e.target.value; setDraft(current => current && { ...current, shipping_text: value }); }} placeholder={tr('填写物流公司、运单号及其他发货说明', 'Carrier, tracking number and other shipping notes')} /></label>
            {canEdit ? <CategoryImageEditor images={draft.images} uploadUrl="/api/admin/shipping-calendar/images" imageKind="shipping" onBusy={setUploading} tr={tr} onChange={images => setDraft(current => current && { ...current, images })} /> : null}
            <label className={`sc-shipped-toggle ${draft.shipped ? 'checked' : ''}`}><input type="checkbox" checked={draft.shipped} disabled={automaticShipping} onChange={e => { const value = e.target.checked; setDraft(current => current && { ...current, shipped: value }); }} /><span><b>{tr('是否发货', 'Shipped')}</b><small>{automaticShipping ? tr('统一提交真实物流文字或图片后即为已发货并通知申请人；审批通过也会自动标记', 'Submitting real shipping text or an image marks shipped and notifies the applicant; approval also marks shipped') : draft.shipped ? canEdit ? tr('暂存后预览为已发货，统一提交后生效', 'Preview as shipped; takes effect when submitted') : tr('已发货', 'Shipped') : canEdit ? tr('暂存后预览为未发货，统一提交后生效', 'Preview as not shipped; takes effect when submitted') : tr('尚未发货', 'Not shipped yet')}</small></span></label>
          </fieldset>
          {!canEdit && <div className="sc-readonly-images">{draft.images.map(image => <a key={image.local_media_id || image.file_token} href={image.path} target="_blank" rel="noreferrer"><img src={image.path} alt={image.name} loading="lazy" /></a>)}</div>}
          {saveError && <ToastMessage className="sc-error" role="alert">{saveError}<button type="button" disabled={saving || uploading || loading} onClick={() => void reloadSelected()}>{tr('放弃修改并载入最新数据', 'Discard edits and reload latest')}</button></ToastMessage>}
          {confirmClose && <div className="sc-discard" role="alert"><span>{tr('有尚未保存的修改。', 'You have unsaved edits.')}</span><button type="button" onClick={() => setConfirmClose(false)}>{tr('继续编辑', 'Keep editing')}</button><button type="button" onClick={() => close(true)}>{tr('放弃修改', 'Discard edits')}</button></div>}
        </div>
        <footer className="sc-dialog-footer"><span role="status">{uploading ? tr('正在上传图片…', 'Uploading images…') : saving ? tr('正在保存…', 'Saving…') : selected.sync_state === 'conflict' ? tr('飞书同步需核对', 'Feishu sync needs review') : canEdit ? tr('先暂存，全部编辑完成后统一提交', 'Stage edits, then submit all changes together') : tr('发货信息由管理员维护', 'Shipping information is maintained by administrators')}</span><button type="button" disabled={saving || uploading} onClick={() => close()}>{tr('取消', 'Cancel')}</button>{canEdit && <button type="button" className="primary" disabled={saving || uploading || !dirty} onClick={() => void save()}>{tr('暂存修改', 'Stage changes')}</button>}</footer>
      </>}
    </dialog>
    <dialog ref={confirmDialog} className="sc-dialog sc-submit-dialog" aria-labelledby="sc-submit-title" onCancel={event => { if (saving) event.preventDefault(); else setConfirmSubmit(false); }}>
      <header className="sc-dialog-heading"><div><h2 id="sc-submit-title">{tr('发货信息即将同步给申请人，请确定提交', 'Shipping information will be shared with applicants. Please confirm submission.')}</h2><p>{tr(`共 ${stagedEntries.length} 张申请单`, `${stagedEntries.length} requests`)}</p></div></header>
      <div className="sc-dialog-body"><ul className="sc-submit-list">{stagedEntries.map(({ base, draft: value }) => <li key={base.request_id}><strong>{base.request_no}</strong><span>{base.requester}</span><span>{value.ship_date || tr('未设置日期', 'Date not set')}</span><span>{value.shipped ? tr('已发货', 'Shipped') : tr('未发货', 'Not shipped')}</span><small>{tr(`${value.images.length} 张图片`, `${value.images.length} images`)}</small></li>)}</ul>{batchError && <ToastMessage className="sc-error" role="alert">{batchError}</ToastMessage>}</div>
      <footer className="sc-dialog-footer"><span>{saving ? tr('正在提交，请稍候…', 'Submitting…') : tr('确认后保存并提交后台同步', 'Confirm to save and submit for synchronization')}</span><button type="button" disabled={saving} onClick={() => setConfirmSubmit(false)}>{tr('取消', 'Cancel')}</button><button type="button" className="primary" disabled={saving || stagedEntries.length === 0} onClick={() => void submitBatch()}>{tr('确定', 'Confirm')}</button></footer>
    </dialog>
  </section>;
}
