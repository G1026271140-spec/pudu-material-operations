import ToastMessage from "./ToastMessage";
import { useEffect, useRef, useState } from 'react';
import type { CurrentUser } from './identity';
import './account-tools.css';

type Person = { open_id: string; name: string; departments: string[]; roles: string[]; enabled: boolean; configured: boolean; version: number | null; versions: Record<string, number>; record_count: number; sync_state: string; duplicate: boolean };
type Catalog = { users: Person[]; roles: string[]; total: number; directory_updated_at: string };
export default function UserPermissionsPage({ lang, currentUser }: { lang: 'zh' | 'en'; currentUser: CurrentUser }) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const [data, setData] = useState<Catalog | null>(null);
  const [search, setSearch] = useState(''); const [roleFilter, setRoleFilter] = useState(''); const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<Person | null>(null); const [roles, setRoles] = useState<string[]>([]); const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false); const [saveError, setSaveError] = useState(''); const dialog = useRef<HTMLDialogElement>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState('');
  const alive = useRef(false);
  const editing = useRef(false);
  const refreshingRef = useRef(false);
  const pollTimer = useRef<number | null>(null);
  const attempt = useRef<{ signature: string; token: string } | null>(null);
  async function load() {
    setLoading(true); setError('');
    try { const response = await fetch('/api/admin/user-permissions', { cache: 'no-store' }); const body = await response.json(); if (!response.ok) throw Error(body.detail || tr('权限数据读取失败', 'Unable to load permissions')); if (alive.current) setData(body); }
    catch (e) { setError(e instanceof Error ? e.message : '读取失败'); } finally { setLoading(false); }
  }
  async function refreshDirectory() {
    if (refreshingRef.current || !alive.current) return;
    refreshingRef.current = true; setRefreshing(true); setRefreshError('');
    const fail = (e: unknown) => {
      refreshingRef.current = false;
      if (alive.current) { setRefreshing(false); setRefreshError(e instanceof Error ? e.message : tr('飞书通讯录刷新失败，请重试。', 'Directory refresh failed. Please retry.')); }
    };
    const poll = async (job: string) => {
      if (!alive.current) return;
      try {
        const response = await fetch(`/api/admin/user-permissions/directory-refresh/${encodeURIComponent(job)}`, { cache: 'no-store' });
        const body = await response.json(); if (!response.ok) throw Error(body.detail || '刷新状态读取失败');
        if (!alive.current) return;
        if (body.state === 'done') { refreshingRef.current = false; setRefreshing(false); await load(); }
        else if (body.state === 'failed') fail(Error(body.error || tr('飞书通讯录刷新失败，请重试。', 'Directory refresh failed. Please retry.')));
        else pollTimer.current = window.setTimeout(() => void poll(job), 1500);
      } catch (e) { fail(e); }
    };
    try {
      const response = await fetch('/api/admin/user-permissions/directory-refresh', { method: 'POST' });
      const body = await response.json(); if (!response.ok) throw Error(body.detail || tr('通讯录刷新提交失败', 'Unable to refresh directory'));
      await poll(body.job_id);
    } catch (e) { fail(e); }
  }
  useEffect(() => {
    alive.current = true; void load(); void refreshDirectory();
    const interval = window.setInterval(() => { if (!document.hidden && !editing.current) void refreshDirectory(); }, 60000);
    return () => { alive.current = false; window.clearInterval(interval); if (pollTimer.current !== null) window.clearTimeout(pollTimer.current); };
  }, []);
  useEffect(() => { editing.current = selected !== null; }, [selected]);
  useEffect(() => { setPage(0); }, [search, roleFilter]);
  useEffect(() => { if (selected && dialog.current && !dialog.current.open) dialog.current.showModal(); if (!selected && dialog.current?.open) dialog.current.close(); }, [selected]);
  const filtered = (data?.users || []).filter(user => (!roleFilter || user.roles.includes(roleFilter)) && (!search.trim() || [user.name, ...user.departments].join(' ').toLowerCase().includes(search.trim().toLowerCase())));
  const count = Math.max(1, Math.ceil(filtered.length / 50));
  function open(person: Person) { setSelected(person); setRoles(person.roles); setEnabled(person.enabled); setSaveError(''); attempt.current = null; }
  async function save() {
    if (!selected || saving) return;
    const payload = { open_id: selected.open_id, roles: [...roles].sort(), enabled, expected_version: selected.version, expected_versions: selected.versions };
    const signature = JSON.stringify(payload); if (attempt.current?.signature !== signature) attempt.current = { signature, token: crypto.randomUUID() };
    setSaving(true); setSaveError('');
    try { const response = await fetch('/api/admin/user-permissions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, idempotency_key: attempt.current.token }) }); const body = await response.json(); if (!response.ok) throw Error(body.detail || tr('权限保存失败', 'Unable to save permissions')); setNotice(tr(`${selected.name} 的权限已保存，稍后同步飞书。`, `Permissions saved for ${selected.name}. Feishu will sync shortly.`)); setSelected(null); if (selected.open_id === currentUser.open_id) window.dispatchEvent(new Event('pudu-permissions-updated')); void load(); }
    catch (e) { setSaveError(e instanceof Error ? e.message : '保存失败'); } finally { setSaving(false); }
  }
  const changed = selected && (JSON.stringify([...roles].sort()) !== JSON.stringify([...selected.roles].sort()) || enabled !== selected.enabled || !selected.configured);
  return <main className="account-tools-page" aria-label={tr('用户权限管理', 'User Permissions')}>{notice && <ToastMessage className="at-notice" role="status">{notice}</ToastMessage>}{error && <ToastMessage className="at-error" role="alert">{error}</ToastMessage>}{refreshing && <ToastMessage className="at-notice" role="status">{tr('正在从飞书刷新公司通讯录，完成后自动更新人员列表。', 'Refreshing the company directory from Feishu. This list will update automatically.')}</ToastMessage>}{refreshError && <ToastMessage className="at-error" role="alert">{refreshError}</ToastMessage>}
    <section className="at-record-section"><div className="at-section-heading"><h3>{tr('公司人员', 'Company Directory')}</h3><span>{tr(`${data?.total || 0} 人`, `${data?.total || 0} people`)}</span>{data && <small>{tr('通讯录同步时间：', 'Directory synced: ')}{data.directory_updated_at.slice(0, 19)}</small>}<button className="at-refresh" disabled={refreshing} onClick={() => void refreshDirectory()}>{refreshing ? tr('正在刷新通讯录…', 'Refreshing directory…') : tr('实时刷新通讯录', 'Refresh live directory')}</button></div><div className="at-filters"><input type="search" aria-label={tr('搜索人员', 'Search people')} placeholder={tr('搜索姓名或部门', 'Search name or department')} value={search} onChange={e => setSearch(e.target.value)} /><select aria-label={tr('角色筛选', 'Filter roles')} value={roleFilter} onChange={e => setRoleFilter(e.target.value)}><option value="">{tr('全部角色', 'All roles')}</option>{data?.roles.map(role => <option key={role}>{role}</option>)}</select><span>{tr(`${filtered.length} 人符合条件`, `${filtered.length} people`)}</span></div>
      <div className="at-table-wrap"><table className="at-table"><thead><tr><th>{tr('姓名', 'Name')}</th><th>{tr('部门', 'Department')}</th><th>{tr('当前角色', 'Current roles')}</th><th>{tr('状态', 'Status')}</th><th></th></tr></thead><tbody>{filtered.slice(page * 50, (page + 1) * 50).map(user => <tr key={user.open_id}><td><strong>{user.name}</strong>{user.open_id === currentUser.open_id && <small>{tr('我', 'Me')}</small>}</td><td>{user.departments.join(' / ') || '—'}</td><td>{user.roles.map(role => <span key={role} className="at-badge">{role}</span>)}{!user.configured && <small>{tr('未单独配置，默认销售', 'Default Sales access')}</small>}</td><td>{user.sync_state === 'conflict' ? tr('同步需核对', 'Sync needs review') : user.enabled ? tr('已启用', 'Enabled') : tr('已停用', 'Disabled')}{user.record_count > 1 && <small>{tr(`已合并 ${user.record_count} 条权限记录`, `${user.record_count} permission records combined`)}</small>}{user.sync_state === 'pending' && <small>{tr('待同步飞书', 'Sync pending')}</small>}</td><td><button className="at-text-button" onClick={() => open(user)}>{tr('分配权限', 'Edit permissions')}</button></td></tr>)}</tbody></table>{!filtered.length && <div className="at-empty">{loading ? tr('正在读取公司通讯录…', 'Loading directory…') : tr('没有匹配人员', 'No matching people')}</div>}</div><div className="at-pagination"><button disabled={page === 0} onClick={() => setPage(value => value - 1)}>{tr('上一页', 'Previous')}</button><span>{page + 1} / {count}</span><button disabled={page + 1 >= count} onClick={() => setPage(value => value + 1)}>{tr('下一页', 'Next')}</button></div></section>
    <dialog ref={dialog} className="at-dialog at-permission-dialog" aria-labelledby="at-permission-title" onCancel={event => { if (saving) event.preventDefault(); else setSelected(null); }}>{selected && <><header><div><h2 id="at-permission-title">{tr('分配权限', 'Edit permissions')} · {selected.name}</h2><p>{selected.departments.join(' / ')}</p></div><button disabled={saving} onClick={() => setSelected(null)} aria-label={tr('关闭', 'Close')}>×</button></header><div className="at-dialog-body"><fieldset className="at-role-choices" disabled={saving}><legend>{tr('系统角色', 'System roles')}</legend>{data?.roles.map(role => <label key={role}><input type="checkbox" checked={roles.includes(role)} onChange={e => { const checked = e.target.checked; setRoles(current => checked ? [...current, role] : current.filter(value => value !== role)); }} />{role}</label>)}<label className="at-enable"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />{tr('启用该人员的系统权限', 'Enable this person’s system permissions')}</label></fieldset>{selected.record_count > 1 && <p className="at-permission-current">{tr(`该账号有 ${selected.record_count} 条权限记录，保存后将统一更新。`, `All ${selected.record_count} permission records for this account will be updated together.`)}</p>}<p className="at-permission-current">{tr('原角色：', 'Previous roles: ')}{selected.roles.join('、') || '—'} → {roles.join('、') || tr('无', 'None')}</p>{selected.open_id === currentUser.open_id && (!enabled || !roles.includes('管理员')) && <ToastMessage className="at-warning">{tr('保存后，你将失去管理员功能访问权限。', 'You will lose administrator access after saving.')}</ToastMessage>}{saveError && <ToastMessage className="at-error" role="alert">{saveError}</ToastMessage>}</div><footer><button disabled={saving} onClick={() => setSelected(null)}>{tr('取消', 'Cancel')}</button><button className="primary" disabled={saving || !changed || (enabled && roles.length === 0)} onClick={() => void save()}>{saving ? tr('正在保存…', 'Saving…') : tr('确认保存', 'Save permissions')}</button></footer></>}</dialog>
  </main>;
}
