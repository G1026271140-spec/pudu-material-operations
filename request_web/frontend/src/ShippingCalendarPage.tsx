import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CategoryImageEditor from './CategoryImageEditor';
import type { CategoryImage } from './CategoryImageEditor';
import { chinaToday, groupRequests, matchesSearch, monthDays, shiftMonth, urgency } from './shippingCalendar';
import type { DateBasis, ShippingRequest } from './shippingCalendar';
import './shipping-calendar.css';

type Lang = 'zh' | 'en';
type Draft = { shipping_text: string; shipped: boolean; images: CategoryImage[] };
const editDraft = (request: ShippingRequest): Draft => ({ shipping_text: request.shipping_text, shipped: request.shipped, images: request.images });
const editSignature = (draft: Draft) => JSON.stringify({ ...draft, images: draft.images.map(image => ({ local_media_id: image.local_media_id, file_token: image.file_token })) });
async function jsonFetch(url: string, options?: RequestInit) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (response.status === 401) throw Error('登录已过期，请重新通过飞书登录。 / Please sign in again.');
  if (!response.headers.get('content-type')?.includes('application/json')) throw Error('未能读取服务器响应，请刷新后重试。 / Please refresh and try again.');
  const body = await response.json();
  if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail : '读取或保存失败 / Request failed');
  return body;
}

export default function ShippingCalendarPage({ lang }: { lang: Lang }) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const today = chinaToday();
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
  const [uploading, setUploading] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [confirmClose, setConfirmClose] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const saveAttempt = useRef<{ signature: string; token: string } | null>(null);
  const loadGeneration = useRef(0);
  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true); setError('');
    try {
      const data = await jsonFetch('/api/admin/shipping-calendar');
      if (generation === loadGeneration.current) setRequests(data.requests);
      return data.requests as ShippingRequest[];
    } catch (e) {
      if (generation === loadGeneration.current) setError(e instanceof Error ? e.message : '读取失败 / Failed to load');
      return null;
    } finally { if (generation === loadGeneration.current) setLoading(false); }
  }, []);
  useEffect(() => { void load(); return () => { ++loadGeneration.current; }; }, [load]);
  // Refresh from PostgreSQL while visible, keeping an open edit draft untouched.
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden && !selected) void load(); }, 30000);
    return () => window.clearInterval(timer);
  }, [load, selected]);
  useEffect(() => {
    if (selected && dialog.current && !dialog.current.open) dialog.current.showModal();
    if (!selected && dialog.current?.open) dialog.current.close();
  }, [selected]);
  const matches = useMemo(() => requests.filter(request => matchesSearch(request, search)), [requests, search]);
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
  const dirty = Boolean(selected && draft && editSignature(draft) !== editSignature(editDraft(selected)));
  function open(request: ShippingRequest) {
    setSelected(request); setDraft(editDraft(request)); setSaveError(''); setConfirmClose(false); saveAttempt.current = null;
  }
  function close(force = false) {
    if (saving || uploading) return;
    if (dirty && !force) { setConfirmClose(true); return; }
    setSelected(null); setDraft(null); setConfirmClose(false); setSaveError('');
  }
  async function save() {
    if (!selected || !draft || saving || uploading) return;
    const payload = { request_id: selected.request_id, expected_version: selected.version,
      shipping_text: draft.shipping_text, shipped: draft.shipped,
      images: draft.images.map(image => image.local_media_id ? { local_media_id: image.local_media_id } : { file_token: image.file_token }) };
    const signature = JSON.stringify(payload);
    if (saveAttempt.current?.signature !== signature) saveAttempt.current = { signature, token: crypto.randomUUID() };
    setSaving(true); setSaveError('');
    try {
      await jsonFetch('/api/admin/shipping-calendar/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, idempotency_key: saveAttempt.current.token }) });
      // Reflect the durable local write immediately, independently of the next read.
      setRequests(current => current.map(request => request.request_id === selected.request_id ? { ...request, ...draft, sync_state: 'pending' } : request));
      setSelected(null); setDraft(null);
      setNotice(tr('发货信息已保存，稍后将通过飞书同步。', 'Shipping details saved. They will sync to Feishu shortly.'));
      void load();
    } catch (e) { setSaveError(e instanceof Error ? e.message : tr('保存失败', 'Save failed')); }
    finally { setSaving(false); }
  }
  async function reloadSelected() {
    if (!selected) return;
    setSaveError('');
    const current = await load();
    const latest = current?.find(request => request.request_id === selected.request_id);
    if (latest) open(latest);
    else setSaveError(tr('该申请单已不在发货日历中，或数据读取失败，请关闭窗口并刷新。', 'This request is no longer available, or loading failed. Close and refresh.'));
  }
  function changeMonth(step: number) { setMonth(value => shiftMonth(value, step)); setDay(''); setAllDates(false); }
  function card(request: ShippingRequest) {
    const urgent = urgency(request, today);
    return <button type="button" className={`sc-card ${request.shipped ? 'is-shipped' : ''} ${urgent ? `is-${urgent}` : ''}`} key={request.request_id} onClick={() => open(request)}>
      <span className="sc-card-top"><strong>{request.request_no}</strong><span className={`sc-status ${request.shipped ? 'done' : 'waiting'}`}>{request.shipped ? tr('已发货', 'Shipped') : tr('未发货', 'Not shipped')}</span></span>
      <span className="sc-person"><b>{request.requester || '—'}</b><span>{[request.department, request.country].filter(Boolean).join(' · ')}</span></span>
      {(request.usage || request.customer) && <span className="sc-purpose">{[request.usage, request.customer].filter(Boolean).join(' · ')}</span>}
      <span className="sc-card-dates"><span>{tr('计划发货', 'Planned ship')}<b>{formatDay(request.ship_date)}</b></span><span>{tr('要求到达', 'Arrival from')}<b>{formatDay(request.arrival_start)}</b></span></span>
      <span className="sc-line-summary">{request.lines.slice(0, 2).map(line => <span key={line.id}>{line.product || tr('物料', 'Material')}<small>{[line.model, line.language].filter(Boolean).join(' / ')}</small><b>× {line.approved_quantity || line.quantity}</b></span>)}</span>
      {!request.lines.length && request.detail_text && <span className="sc-purpose">{request.detail_text}</span>}
      <span className="sc-card-footer"><span>{tr(`${request.lines.length} 项物料`, `${request.lines.length} items`)}{request.images.length > 0 && ` · ${tr(`${request.images.length} 张发货图片`, `${request.images.length} photos`)}`}</span>
        {urgent && <b className="sc-urgent">{urgent === 'overdue' ? tr('计划发货日已过', 'Past planned ship date') : tr('今日待发', 'Ship today')}</b>}
        {!urgent && request.sync_state === 'pending' && <span>{tr('待同步', 'Sync pending')}</span>}
        {request.sync_state === 'conflict' && <b className="sc-urgent">{tr('同步需核对', 'Sync needs review')}</b>}
      </span>
      {request.shipping_text && <span className="sc-tracking">{request.shipping_text}</span>}
    </button>;
  }
  return <section className="shipping-calendar" aria-labelledby="sc-title">
    <header className="sc-heading"><div><h2 id="sc-title">{tr('物料发货日历', 'Material Shipping Calendar')}</h2><p>{tr('已核实库存的申请单', 'Inventory-verified requests')}</p></div><button type="button" onClick={() => void load()} disabled={loading}>{loading ? tr('读取中…', 'Loading…') : tr('刷新', 'Refresh')}</button></header>
    {notice && <div className="sc-notice" role="status">{notice}<button type="button" onClick={() => setNotice('')} aria-label={tr('关闭提示', 'Dismiss')}>×</button></div>}
    {error && <div className="sc-error" role="alert">{error}<button type="button" onClick={() => void load()}>{tr('重试', 'Retry')}</button></div>}
    <div className="sc-filters"><label><span>{tr('搜索申请单', 'Search requests')}</span><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={tr('单号、申请人、物料或发货信息', 'Number, requester, item or tracking info')} /></label>
      <label><span>{tr('日期依据', 'Date basis')}</span><select value={basis} onChange={e => { setBasis(e.target.value as DateBasis); setDay(''); }}><option value="ship_date">{tr('计划发货日', 'Planned ship date')}</option><option value="arrival_start">{tr('要求到达开始日', 'Required arrival start')}</option></select></label>
      <button type="button" className={allDates ? 'active' : ''} aria-pressed={allDates} onClick={() => { setAllDates(value => !value); setDay(''); }}>{tr('全部日期', 'All dates')}</button>
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
          <dl className="sc-facts"><div><dt>{tr('计划发货日', 'Planned ship date')}</dt><dd>{selected.ship_date || '—'}</dd></div><div><dt>{tr('要求到达时间', 'Required arrival')}</dt><dd>{selected.arrival_start || '—'}{selected.arrival_end && selected.arrival_end !== selected.arrival_start ? ` – ${selected.arrival_end}` : ''}</dd></div><div><dt>{tr('客户 / 国家', 'Customer / country')}</dt><dd>{[selected.customer, selected.country].filter(Boolean).join(' / ') || '—'}</dd></div><div><dt>{tr('申请原因 / 用途', 'Reason / usage')}</dt><dd>{[selected.reason, selected.usage].filter(Boolean).join(' / ') || '—'}</dd></div><div className="wide"><dt>{tr('收件人信息', 'Recipient details')}</dt><dd>{selected.recipient || '—'}</dd></div></dl>
          <section className="sc-details"><h3>{tr('申请明细', 'Request details')}<span>{selected.lines.length}</span></h3><div className="sc-detail-table"><table><thead><tr><th>{tr('物料 / 型号 / 语种', 'Item / model / language')}</th><th>{tr('申请', 'Requested')}</th><th>{tr('核准', 'Approved')}</th><th>{tr('已发放', 'Issued')}</th></tr></thead><tbody>{selected.lines.map(line => <tr key={line.id}><td><strong>{line.product || '—'}</strong><span>{[line.model, line.language].filter(Boolean).join(' / ')}</span>{line.remark && <small>{line.remark}</small>}</td><td>{line.quantity}</td><td>{line.approved_quantity}</td><td>{line.issued_quantity}</td></tr>)}</tbody></table></div>{selected.lines.length === 0 && <p className="sc-prewrap">{selected.detail_text || tr('暂无结构化明细', 'No item details available')}</p>}</section>
          <fieldset className="sc-editor" disabled={saving || uploading}><legend>{tr('发货信息', 'Shipping details')}</legend><label className="sc-tracking-input"><span>{tr('发货单号及文字信息', 'Tracking number and shipping notes')}</span><textarea rows={4} maxLength={20000} value={draft.shipping_text} onChange={e => { const value = e.target.value; setDraft(current => current && { ...current, shipping_text: value }); }} placeholder={tr('填写物流公司、运单号及其他发货说明', 'Carrier, tracking number and other shipping notes')} /></label>
            <CategoryImageEditor images={draft.images} uploadUrl="/api/admin/shipping-calendar/images" imageKind="shipping" onBusy={setUploading} tr={tr} onChange={images => setDraft(current => current && { ...current, images })} />
            <label className={`sc-shipped-toggle ${draft.shipped ? 'checked' : ''}`}><input type="checkbox" checked={draft.shipped} onChange={e => { const value = e.target.checked; setDraft(current => current && { ...current, shipped: value }); }} /><span><b>{tr('是否发货', 'Shipped')}</b><small>{draft.shipped ? tr('保存后移入“已发货”列', 'Moves to Shipped after saving') : tr('保存后保留在“未发货”列', 'Remains in Not shipped after saving')}</small></span></label>
          </fieldset>
          {saveError && <div className="sc-error" role="alert">{saveError}<button type="button" disabled={saving || uploading || loading} onClick={() => void reloadSelected()}>{tr('放弃修改并载入最新数据', 'Discard edits and reload latest')}</button></div>}
          {confirmClose && <div className="sc-discard" role="alert"><span>{tr('有尚未保存的修改。', 'You have unsaved edits.')}</span><button type="button" onClick={() => setConfirmClose(false)}>{tr('继续编辑', 'Keep editing')}</button><button type="button" onClick={() => close(true)}>{tr('放弃修改', 'Discard edits')}</button></div>}
        </div>
        <footer className="sc-dialog-footer"><span role="status">{uploading ? tr('正在上传图片…', 'Uploading images…') : saving ? tr('正在保存…', 'Saving…') : selected.sync_state === 'conflict' ? tr('飞书同步需核对', 'Feishu sync needs review') : tr('保存后更新发货状态', 'Save to update shipping status')}</span><button type="button" disabled={saving || uploading} onClick={() => close()}>{tr('取消', 'Cancel')}</button><button type="button" className="primary" disabled={saving || uploading || !dirty} onClick={() => void save()}>{tr('保存发货信息', 'Save shipping details')}</button></footer>
      </>}
    </dialog>
  </section>;
}
