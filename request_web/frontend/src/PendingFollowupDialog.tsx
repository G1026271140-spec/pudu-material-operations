import { useEffect, useRef, useState } from 'react';
import type { PendingRequest } from './pendingAllocation';
import ToastMessage from './ToastMessage';

type Props = { request: PendingRequest; lang: 'zh' | 'en'; onClose: () => void; onSaved: (result: any) => void;
  save: (id: string, body: any) => Promise<any> };

export default function PendingFollowupDialog({ request, lang, onClose, onSaved, save }: Props) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const saveKey = useRef('');
  const [label, setLabel] = useState(request.reviewLabel || '');
  const [note, setNote] = useState(request.reviewNote || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { const el = dialog.current; if (el && !el.open) el.showModal(); return () => el?.close(); }, []);
  function edit(setter: (text: string) => void, value: string) { setter(value); saveKey.current = ''; }
  async function submit() {
    if (lock.current) return;
    lock.current = true; setSaving(true); setError('');
    saveKey.current ||= crypto.randomUUID();
    try { onSaved(await save(request.requestId, { label, note, expected_version: request.recordVersion, idempotency_key: saveKey.current })); }
    catch (e) { setError(e instanceof Error ? e.message : tr('保存失败，请重试。', 'Save failed. Please retry.')); }
    finally { lock.current = false; setSaving(false); }
  }
  return <dialog ref={dialog} className="pending-followup-dialog" aria-labelledby="pending-followup-title" onCancel={e => { if (saving) e.preventDefault(); else onClose(); }}>
    <form onSubmit={e => { e.preventDefault(); submit(); }}>
      <div className="pending-followup-heading"><div><small>{request.requestNo}</small><h2 id="pending-followup-title">{tr('标签和跟进备注', 'Follow-up label and note')}</h2></div><button type="button" className="pending-followup-close" aria-label={tr('关闭标签编辑', 'Close label editor')} disabled={saving} onClick={onClose}>×</button></div>
      <div className="pending-followup-fields"><label><span>{tr('自定义标签', 'Custom label')}</span><input autoFocus maxLength={40} disabled={saving} value={label} onChange={e => edit(setLabel, e.target.value)} placeholder={tr('如：暂缓评估、等待确认', 'e.g. On hold, Awaiting confirmation')} /></label>
        <label><span>{tr('跟进备注', 'Follow-up note')}</span><textarea maxLength={1000} rows={4} disabled={saving} value={note} onChange={e => edit(setNote, e.target.value)} placeholder={tr('记录当前无法判断是否继续流程的原因', 'Why the request cannot proceed yet')} /></label>
        <p>{tr('带标签的申请显示为黄色；清空标签后恢复。此操作不会启动核实、审批或发货。', 'Labeled requests appear yellow. Clear the label to restore their appearance. This does not start review, approval or shipping.')}</p>
      </div>
      <div className="pending-followup-actions"><button type="button" disabled={saving} onClick={onClose}>{tr('取消', 'Cancel')}</button><button type="submit" className="primary" disabled={saving}>{saving ? tr('正在保存…', 'Saving…') : tr('保存标签和备注', 'Save label and note')}</button></div>
    </form>
    {error && <ToastMessage className="allocation-toast" onClick={() => setError('')}>{error} ×</ToastMessage>}
  </dialog>;
}
