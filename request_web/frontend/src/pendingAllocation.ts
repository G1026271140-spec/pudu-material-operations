export type PendingRequest = {
  requestId: string; requestNo: string; requester?: string; department?: string;
  reason?: string; lineCount?: number; inventoryReviewResult?: string;
  submittedAt?: string | number; requiredArrivalTime?: string;
  requiredArrivalStart?: string; requiredArrivalEnd?: string;
  recordVersion?: number; reviewLabel?: string; reviewNote?: string;
};

export function submissionDay(value: string | number | undefined): string {
  if (value === undefined || value === '') return '';
  const raw = String(value).trim();
  const plain = /^(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$/.exec(raw);
  if (plain) {
    const date = new Date(`${plain[1]}T00:00:00+08:00`);
    if (Number.isNaN(date.valueOf())) return '';
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
    const day = `${parts.find(p => p.type === 'year')?.value}-${parts.find(p => p.type === 'month')?.value}-${parts.find(p => p.type === 'day')?.value}`;
    return day === plain[1] ? day : '';
  }
  const date = typeof value === 'number' ? new Date(value) : new Date(raw);
  if (Number.isNaN(date.valueOf())) return '';
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
  return `${parts.find(p => p.type === 'year')?.value}-${parts.find(p => p.type === 'month')?.value}-${parts.find(p => p.type === 'day')?.value}`;
}

export function groupPendingByDate(requests: PendingRequest[]) {
  const groups = new Map<string, PendingRequest[]>();
  for (const request of requests) {
    const date = submissionDay(request.submittedAt);
    groups.set(date, [...(groups.get(date) || []), request]);
  }
  return [...groups].sort(([a], [b]) => a === '' ? 1 : b === '' ? -1 : b.localeCompare(a))
    .map(([date, requests]) => ({ date, requests }));
}

export function submissionDateLabel(date: string, lang: 'zh' | 'en') {
  if (!date) return lang === 'zh' ? '未填写提交日期' : 'Submission date unavailable';
  return new Date(`${date}T00:00:00+08:00`).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-GB',
    { timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric' });
}
