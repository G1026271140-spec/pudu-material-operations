import { groupPendingByDate, submissionDateLabel } from './pendingAllocation';
import type { PendingRequest } from './pendingAllocation';
import { requiredArrivalText } from './allocationPresentation';

type Props = { requests: PendingRequest[]; lang: 'zh' | 'en'; onOpen: (id: string) => void; onAnnotate: (request: PendingRequest) => void };

export default function PendingAllocationList({ requests, lang, onOpen, onAnnotate }: Props) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  return <div className="pending-date-groups">{groupPendingByDate(requests).map(group => <section className="pending-date-group" key={group.date || 'undated'} aria-label={submissionDateLabel(group.date, lang)}>
    <div className="pending-date-heading"><h3>{group.date ? <time dateTime={group.date}>{submissionDateLabel(group.date, lang)}</time> : submissionDateLabel('', lang)}</h3><span>{group.requests.length} {tr('单', 'requests')}</span></div>
    <div className="pending-grid">{group.requests.map(item => <article className={`pending-card${item.reviewLabel?.trim() ? ' is-tagged' : ''}`} key={item.requestId} aria-label={item.requestNo}>
      <button className="pending-open" type="button" onClick={() => onOpen(item.requestId)}>
        <span className="pending-card-heading"><strong>{item.requestNo}</strong><em>{item.inventoryReviewResult || tr('待核实', 'Pending')}</em></span>
        <span>{item.requester} · {item.department}</span>
        <span>{item.reason || '—'} · {item.lineCount || 0} {tr('条明细', 'lines')}</span>
        <span className="pending-arrival">{tr('要求到达：', 'Required arrival: ')}{requiredArrivalText(item, lang)}</span>
      </button>
      {(item.reviewLabel || item.reviewNote) && <div className="pending-followup-content">{item.reviewLabel && <span className="pending-label-badge">{item.reviewLabel}</span>}{item.reviewNote && <p title={item.reviewNote}>{item.reviewNote}</p>}</div>}
      {typeof item.recordVersion === 'number' && <div className="pending-card-actions"><button type="button" onClick={() => onAnnotate(item)} aria-label={`${tr('标签和备注', 'Label and note')} ${item.requestNo}`}>{item.reviewLabel || item.reviewNote ? tr('编辑标签 / 备注', 'Edit label / note') : tr('添加标签 / 备注', 'Add label / note')}</button></div>}
    </article>)}</div>
  </section>)}</div>;
}
