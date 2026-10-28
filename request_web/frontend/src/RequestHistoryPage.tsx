import { useEffect, useMemo, useRef, useState } from 'react';
import type { CurrentUser } from './identity';
import './account-tools.css';

type Lang = 'zh' | 'en';
type RecordItem = { can_reject?: boolean; card_sync?: string; id: string; number: string; type: string; requester: string; department: string; submitted_at: string; submitted_date: string; status: string; review_status: string; ship_date: string; arrival_start: string; arrival_end: string; shipped: boolean; shipping_text: string; usage: string; reason: string; customer: string; country: string; recipient: string; total_rmb: number; detail_text: string; lines: { id: string; product: string; model: string; dimension: string; quantity: number; approved: number; issued: number; status: string; remark: string }[] };
type Catalog = { requests: RecordItem[]; quotas: { key: string; name: string; limit: number; used: number; remaining: number; visible: boolean }[]; mode: string; scope: string; types: string[] };

export default function RequestHistoryPage({ lang, currentUser }: { lang: Lang; currentUser: CurrentUser }) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const [scope, setScope] = useState(currentUser.permission_status === 'enabled' && currentUser.roles.includes('HR') && !currentUser.roles.includes('管理员') ? 'all' : 'mine');
  const [data, setData] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [status, setStatus] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<RecordItem | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const rejectDialog = useRef<HTMLDialogElement>(null);
  const [confirmReject, setConfirmReject] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectError, setRejectError] = useState('');
  const [notice, setNotice] = useState('');
  const generation = useRef(0);
  async function load() {
    const request = ++generation.current; setLoading(true); setError('');
    try {
      const response = await fetch(`/api/request-history?scope=${scope}`, { cache: 'no-store' });
      const body = await response.json();
      if (!response.ok) throw Error(body.detail || tr('申请记录读取失败', 'Unable to load history'));
      if (request === generation.current) { setData(body); setPage(0); }
    } catch (e) { if (request === generation.current) setError(e instanceof Error ? e.message : '读取失败'); }
    finally { if (request === generation.current) setLoading(false); }
  }
  useEffect(() => { setData(null); void load(); return () => { ++generation.current; }; }, [scope]);
  useEffect(() => { if (selected && dialog.current && !dialog.current.open) dialog.current.showModal(); if (!selected && dialog.current?.open) dialog.current.close(); }, [selected]);
  useEffect(() => { setPage(0); }, [search, kind, status, from, to]);
  useEffect(() => { if (confirmReject && rejectDialog.current && !rejectDialog.current.open) rejectDialog.current.showModal(); if (!confirmReject && rejectDialog.current?.open) rejectDialog.current.close(); }, [confirmReject]);
  async function reject() {
    if (!selected || rejecting) return;
    setRejecting(true); setRejectError('');
    try {
      const response = await fetch('/api/request-history/reject-apparel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: selected.id, confirmed: true }) });
      const body = await response.json(); if (!response.ok) throw Error(body.detail || tr('驳回失败', 'Rejection failed'));
      setConfirmReject(false); setSelected(null); setNotice(tr('申领已驳回，库存和额度已恢复，飞书卡片将由后台更新。', 'Request rejected, stock and allowance restored. Feishu cards will update in the background.')); void load();
    } catch (e) { setRejectError(e instanceof Error ? e.message : '驳回失败'); } finally { setRejecting(false); }
  }
  const filtered = useMemo(() => (data?.requests || []).filter(row => (!kind || row.type === kind) && (!status || row.status === status) && (!from || row.submitted_date >= from) && (!to || row.submitted_date <= to) && (!search.trim() || [row.number, row.requester, row.department, row.usage, ...row.lines.map(line => `${line.product} ${line.model} ${line.dimension}`)].join(' ').toLowerCase().includes(search.trim().toLowerCase()))), [data, search, kind, status, from, to]);
  const rows = filtered.slice(page * 30, (page + 1) * 30);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 30));
  return <main className="account-tools-page">
    <header className="at-heading"><div><h2>{tr('申请记录与额度', 'Request History & Allowances')}</h2><p>{data?.mode === 'hr' ? tr('文化周边与企业文化衫申请记录', 'Cultural merchandise and apparel requests') : tr('申请记录及我的企业文化衫领取额度', 'Request history and my corporate apparel allowances')}</p></div><button onClick={() => void load()} disabled={loading}>{loading ? tr('读取中…', 'Loading…') : tr('刷新数据', 'Refresh')}</button></header>
    {notice && <div className="at-notice" role="status">{notice}</div>}
    {error && <div className="at-error" role="alert">{error}</div>}
    <section className="at-quota-section"><div className="at-section-heading"><h3>{tr('我的企业文化衫额度', 'My Apparel Allowances')}</h3><span>{tr('累计领取额度', 'Cumulative allowances')}</span></div><div className="at-quota-grid">{data?.quotas.map(quota => <article key={quota.key} className={!quota.visible ? 'unavailable' : ''}><div><strong>{quota.name}</strong><small>{quota.visible ? tr('开放申领', 'Available') : tr('未开放申领', 'Not available')}</small></div><p><span>{tr('剩余', 'Remaining')}<b>{quota.remaining}</b></span><span>{tr('已领', 'Claimed')}<b>{quota.used}</b></span><span>{tr('上限', 'Limit')}<b>{quota.limit}</b></span></p></article>)}</div></section>
    <section className="at-record-section"><div className="at-section-heading"><h3>{tr('历史申请', 'Request History')}</h3>{data?.mode === 'admin' && <nav className="at-scope" aria-label={tr('数据范围', 'Data scope')}><button className={scope === 'mine' ? 'active' : ''} onClick={() => setScope('mine')}>{tr('个人数据', 'My requests')}</button><button className={scope === 'all' ? 'active' : ''} onClick={() => setScope('all')}>{tr('所有数据', 'All requests')}</button></nav>}<span>{tr(`${filtered.length} 条`, `${filtered.length} records`)}</span></div>
      <div className="at-filters"><input aria-label={tr('搜索申请', 'Search requests')} type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={tr('搜索单号、申请人、部门或物料', 'Search number, requester, department or item')} /><select aria-label={tr('申请类型', 'Request type')} value={kind} onChange={e => setKind(e.target.value)}><option value="">{tr('全部类型', 'All types')}</option>{data?.types.map(type => <option key={type}>{type}</option>)}</select><select aria-label={tr('申请状态', 'Status')} value={status} onChange={e => setStatus(e.target.value)}><option value="">{tr('全部状态', 'All statuses')}</option>{[...new Set(data?.requests.map(row => row.status).filter(Boolean))].sort().map(value => <option key={value}>{value}</option>)}</select><label>{tr('从', 'From')}<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label><label>{tr('至', 'To')}<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label></div>
      <div className="at-table-wrap"><table className="at-table"><thead><tr><th>{tr('申请单号 / 类型', 'Request / Type')}</th><th>{tr('申请人 / 部门', 'Requester / Department')}</th><th>{tr('物料明细', 'Items')}</th><th>{tr('提交时间', 'Submitted')}</th><th>{tr('状态', 'Status')}</th><th>{tr('发货日期', 'Ship date')}</th><th></th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><strong>{row.number}</strong><small>{row.type}</small></td><td>{row.requester || '—'}<small>{row.department}</small></td><td><span className="at-item-summary">{row.lines.slice(0, 2).map(line => `${line.product} ×${line.quantity}`).join('；') || row.detail_text || '—'}</span>{row.lines.length > 2 && <small>{tr(`共 ${row.lines.length} 项`, `${row.lines.length} items`)}</small>}</td><td>{row.submitted_at || '—'}</td><td><span className="at-badge">{row.status || '—'}</span>{row.card_sync && <small>{row.card_sync === 'done' ? tr('卡片已更新', 'Cards updated') : row.card_sync === 'failed' ? tr('卡片更新需核对', 'Card update needs review') : tr('卡片待同步', 'Cards pending sync')}</small>}</td><td>{row.ship_date || '—'}</td><td><button className="at-text-button" onClick={() => setSelected(row)}>{tr('查看详情', 'View details')}</button></td></tr>)}</tbody></table>{!rows.length && <div className="at-empty">{loading ? tr('正在读取…', 'Loading…') : tr('暂无符合条件的申请记录', 'No matching requests')}</div>}</div>
      <div className="at-pagination"><button disabled={page === 0} onClick={() => setPage(value => value - 1)}>{tr('上一页', 'Previous')}</button><span>{page + 1} / {pageCount}</span><button disabled={page + 1 >= pageCount} onClick={() => setPage(value => value + 1)}>{tr('下一页', 'Next')}</button></div>
    </section>
    <dialog ref={dialog} className="at-dialog at-history-dialog" onCancel={() => setSelected(null)} aria-labelledby="at-record-title">{selected && <><header><div><h2 id="at-record-title">{selected.number}</h2><p>{selected.type} · {selected.requester} · {selected.department}</p></div><button onClick={() => setSelected(null)} aria-label={tr('关闭', 'Close')}>×</button></header><div className="at-dialog-body"><dl className="at-facts">{[[tr('状态', 'Status'), selected.status], [tr('提交时间', 'Submitted'), selected.submitted_at], [tr('发货日期', 'Shipping date'), selected.ship_date], [tr('到达时间', 'Arrival'), [selected.arrival_start, selected.arrival_end].filter(Boolean).join(' – ')], [tr('用途 / 原因', 'Usage / Reason'), [selected.usage, selected.reason].filter(Boolean).join(' / ')], [tr('客户 / 国家', 'Customer / Country'), [selected.customer, selected.country].filter(Boolean).join(' / ')], [tr('收件人信息', 'Recipient'), selected.recipient], [tr('发货单号及文字信息', 'Shipping details'), selected.shipping_text]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '—'}</dd></div>)}</dl><div className="at-table-wrap"><table className="at-table"><thead><tr><th>{tr('物料 / 型号 / 语种或战区', 'Item / Model / Language or region')}</th><th>{tr('申请', 'Requested')}</th><th>{tr('核准', 'Approved')}</th><th>{tr('发放', 'Issued')}</th><th>{tr('状态', 'Status')}</th></tr></thead><tbody>{selected.lines.map(line => <tr key={line.id}><td><strong>{line.product || '—'}</strong><small>{[line.model, line.dimension].filter(Boolean).join(' / ')}</small>{line.remark && <small>{line.remark}</small>}</td><td>{line.quantity}</td><td>{line.approved}</td><td>{line.issued}</td><td>{line.status || '—'}</td></tr>)}</tbody></table></div>{!selected.lines.length && <p className="at-prewrap">{selected.detail_text || tr('暂无明细', 'No details')}</p>}</div><footer>{selected.can_reject && <button className="at-reject" onClick={() => { setRejectError(''); setConfirmReject(true); }}>{tr('驳回申领', 'Reject request')}</button>}<button onClick={() => setSelected(null)}>{tr('关闭', 'Close')}</button></footer></>}</dialog>
    <dialog ref={rejectDialog} className="at-dialog at-permission-dialog" aria-labelledby="at-reject-title" onCancel={event => { if (rejecting) event.preventDefault(); else setConfirmReject(false); }}><header><h2 id="at-reject-title">{tr('确认驳回企业文化衫申领', 'Reject Corporate Apparel Request')}</h2></header><div className="at-dialog-body"><p>{selected?.number} · {selected?.requester}</p><p>{tr('驳回后将恢复本次申领占用的库存和个人额度，并更新申请人与 HR 的飞书卡片通知。', 'Stock and personal allowance will be restored. Applicant and HR Feishu cards will be updated.')}</p>{rejectError && <div className="at-error" role="alert">{rejectError}</div>}</div><footer><button disabled={rejecting} onClick={() => setConfirmReject(false)}>{tr('取消', 'Cancel')}</button><button className="at-reject" disabled={rejecting} onClick={() => void reject()}>{rejecting ? tr('正在驳回…', 'Rejecting…') : tr('确定驳回', 'Confirm rejection')}</button></footer></dialog>
  </main>;
}
