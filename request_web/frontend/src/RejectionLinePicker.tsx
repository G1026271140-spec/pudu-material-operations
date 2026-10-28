import { CategoryRows } from './CategoryGroups';

export type RejectionLine = { id: string; product: string; model: string; dimension: string; quantity: number; approved: number; issued: number; status: string; remark: string; can_reject?: boolean };
export function chosenRejectionLines(lines: readonly RejectionLine[], ids: readonly string[]) {
  const selected = new Set(ids);
  return lines.filter(line => line.can_reject && selected.has(line.id));
}

export default function RejectionLinePicker({ lines, selectedIds = [], onChange, enabled = false, lang }: {
  lines: RejectionLine[]; selectedIds?: string[]; onChange?: (ids: string[]) => void; enabled?: boolean; lang: 'zh' | 'en';
}) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const eligible = lines.filter(line => line.can_reject);
  const selected = chosenRejectionLines(lines, selectedIds);
  return <div className="at-rejection-lines">
    {enabled && <div className="at-rejection-toolbar"><span>{tr('勾选要驳回的明细，所选行的发放数量全部退回。', 'Select lines to reject. The full issued quantity of each selected line will be returned.')}</span><div><button type="button" onClick={() => onChange?.(eligible.map(line => line.id))}>{tr('全选可驳回明细', 'Select eligible')}</button><button type="button" onClick={() => onChange?.([])}>{tr('清空', 'Clear')}</button><strong>{tr(`已选 ${selected.length} 项 / ${selected.reduce((sum, line) => sum + line.issued, 0)} 件`, `${selected.length} lines / ${selected.reduce((sum, line) => sum + line.issued, 0)} items selected`)}</strong></div></div>}
    <div className="at-table-wrap"><table className="at-table"><thead><tr>{enabled && <th>{tr('选择', 'Select')}</th>}<th>{tr('物料 / 型号 / 语种或战区', 'Item / Model / Language or region')}</th><th>{tr('申请', 'Requested')}</th><th>{tr('核准', 'Approved')}</th><th>{tr('发放', 'Issued')}</th><th>{tr('状态', 'Status')}</th></tr></thead><tbody>
      <CategoryRows items={lines} category={line => line.product} quantity={line => line.quantity} lang={lang} columns={enabled ? 6 : 5} render={line => {
        const checked = !!line.can_reject && selectedIds.includes(line.id);
        return <tr key={line.id} className={checked ? 'at-rejection-selected' : line.status === '已驳回' ? 'at-rejection-complete' : ''}>
          {enabled && <td className="at-rejection-checkbox"><input type="checkbox" aria-label={tr(`驳回 ${line.product} ${line.model} ${line.dimension}`, `Reject ${line.product} ${line.model} ${line.dimension}`)} checked={checked} disabled={!line.can_reject} onChange={() => onChange?.(checked ? selectedIds.filter(id => id !== line.id) : [...selectedIds, line.id])}/></td>}
          <td><strong>{line.product || '—'}</strong><small>{[line.model, line.dimension].filter(Boolean).join(' / ')}</small>{line.remark && <small>{line.remark}</small>}</td><td>{line.quantity}</td><td>{line.approved}</td><td>{line.issued}</td><td>{line.status || '—'}</td>
        </tr>;
      }}/>
    </tbody></table></div>
  </div>;
}
