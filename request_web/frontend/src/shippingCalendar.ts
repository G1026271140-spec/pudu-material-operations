import type { CategoryImage } from './CategoryImageEditor';

export type ShippingLine = { id: string; line_no: string; product: string; model: string; language: string; quantity: number; approved_quantity: number; issued_quantity: number; remark: string };
export type ShippingRequest = {
  request_id: string; request_no: string; version: number; sync_state: string;
  requester: string; department: string; region: string; customer: string; country: string; recipient: string;
  usage: string; reason: string; submitted_at: string; status: string;
  ship_date: string; arrival_start: string; arrival_end: string; shipped: boolean;
  shipping_text: string; images: CategoryImage[]; lines: ShippingLine[]; detail_text: string;
  notification?: { state: string; error: string } | null;
};
export type DateBasis = 'ship_date' | 'arrival_start';
export function chinaToday(now = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}
export function monthDays(month: string): string[] {
  const [year, number] = month.split('-').map(Number);
  return Array.from({ length: new Date(Date.UTC(year, number, 0)).getUTCDate() }, (_, index) => `${month}-${String(index + 1).padStart(2, '0')}`);
}
export function shiftMonth(month: string, step: number): string {
  const [year, number] = month.split('-').map(Number);
  return new Date(Date.UTC(year, number - 1 + step, 1)).toISOString().slice(0, 7);
}
export function matchesSearch(request: ShippingRequest, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return !needle || [request.request_no, request.requester, request.department, request.region, request.customer, request.country, request.usage, request.shipping_text,
    ...request.lines.flatMap(line => [line.product, line.model, line.language])].join('\n').toLocaleLowerCase().includes(needle);
}
export function urgency(request: ShippingRequest, today: string): 'overdue' | 'today' | '' {
  if (request.shipped || !request.ship_date) return '';
  return request.ship_date < today ? 'overdue' : request.ship_date === today ? 'today' : '';
}
export function groupRequests(requests: ShippingRequest[], basis: DateBasis): [string, ShippingRequest[]][] {
  const groups = new Map<string, ShippingRequest[]>();
  for (const request of requests) {
    const key = request[basis] || '';
    groups.set(key, [...(groups.get(key) || []), request]);
  }
  return [...groups.entries()].sort(([a], [b]) => (a || '9999').localeCompare(b || '9999'))
    .map(([day, items]) => [day, items.sort((a, b) => (a.arrival_start || '9999').localeCompare(b.arrival_start || '9999') || a.request_no.localeCompare(b.request_no))]);
}

export type ShippingDraft = Pick<ShippingRequest, 'shipping_text' | 'shipped' | 'images' | 'ship_date'>;
export type ShippingStaging = Record<string, { base: ShippingRequest; draft: ShippingDraft }>;
export const shippingDraft = (request: ShippingRequest): ShippingDraft => ({ shipping_text: request.shipping_text, shipped: request.shipped, images: request.images, ship_date: request.ship_date });
export const draftSignature = (draft: ShippingDraft) => JSON.stringify({ ...draft, images: draft.images.map(image => ({ local_media_id: image.local_media_id, file_token: image.file_token })) });
export function stageShippingDraft(current: ShippingStaging, request: ShippingRequest, draft: ShippingDraft): ShippingStaging {
  const base = current[request.request_id]?.base || request;
  const next = { ...current };
  if (draftSignature(draft) === draftSignature(shippingDraft(base))) delete next[base.request_id];
  else next[base.request_id] = { base, draft };
  return next;
}
export function shippingBatchChanges(staged: ShippingStaging) {
  return Object.values(staged).map(({ base, draft }) => ({ request_id: base.request_id, expected_version: base.version,
    shipping_text: draft.shipping_text, shipped: draft.shipped, ship_date: draft.ship_date,
    images: draft.images.map(image => image.local_media_id ? { local_media_id: image.local_media_id } : { file_token: image.file_token }) }))
    .sort((a, b) => a.request_id.localeCompare(b.request_id));
}
