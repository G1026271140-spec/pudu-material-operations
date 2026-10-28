import assert from 'node:assert/strict';
import test from 'node:test';
import { chinaToday, monthDays, shiftMonth, urgency, groupRequests, matchesSearch, shippingDraft, stageShippingDraft, shippingBatchChanges } from '../src/shippingCalendar.ts';
const request = { request_id: 'a', request_no: 'REQ-1', requester: 'Test', department: 'APAC', region: '', customer: '', country: '', usage: '', shipping_text: 'DHL 456', ship_date: '2026-10-27', arrival_start: '2026-11-01', shipped: false, lines: [{ product: 'Brochure', model: 'GT7', language: 'Japanese' }] };
test('China calendar date does not drift at UTC or browser timezone boundaries', () => {
  assert.equal(chinaToday(new Date('2026-10-27T16:01:00Z')), '2026-10-28');
  assert.equal(monthDays('2028-02').length, 29);
  assert.equal(shiftMonth('2026-12', 1), '2027-01');
  assert.equal(shiftMonth('2026-01', -1), '2025-12');
});
test('Calendar basis switches dates while retaining unscheduled orders', () => {
  const unscheduled = { ...request, request_id: 'b', ship_date: '', arrival_start: '' };
  assert.deepEqual(groupRequests([unscheduled, request], 'ship_date').map(([date]) => date), ['2026-10-27', '']);
  assert.deepEqual(groupRequests([request, unscheduled], 'arrival_start').map(([date]) => date), ['2026-11-01', '']);
});
test('Shipped status suppresses overdue warnings and search covers line and tracking data', () => {
  assert.equal(urgency(request, '2026-10-28'), 'overdue');
  assert.equal(urgency({ ...request, shipped: true }, '2026-10-28'), '');
  assert.equal(urgency(request, '2026-10-27'), 'today');
  assert.ok(matchesSearch(request, 'japanese'));
  assert.ok(matchesSearch(request, 'dhl 456'));
  assert.ok(!matchesSearch(request, 'unknown'));
});

test('Restaging preserves the first base version and reverting removes a no-op draft', () => {
  const original = { ...request, version: 5, images: [], shipping_text: 'old' };
  const once = stageShippingDraft({}, original, { ...shippingDraft(original), shipping_text: 'draft one' });
  const refreshed = { ...original, version: 6 };
  const twice = stageShippingDraft(once, refreshed, { ...shippingDraft(original), shipping_text: 'draft two' });
  assert.equal(twice.a.base.version, 5);
  assert.equal(twice.a.draft.shipping_text, 'draft two');
  assert.deepEqual(stageShippingDraft(twice, refreshed, shippingDraft(original)), {});
  assert.equal(original.shipping_text, 'old');
});
test('Batch includes every staged order with stable ordering and no UI attachment metadata', () => {
  const a = { ...request, version: 1, images: [] };
  const b = { ...a, request_id: 'b', request_no: 'REQ-2', version: 4 };
  let staged = stageShippingDraft({}, b, { ...shippingDraft(b), shipped: true });
  staged = stageShippingDraft(staged, a, { ...shippingDraft(a), images: [{ local_media_id: 'local-photo', path: '/private', name: 'image' }] });
  const rows = shippingBatchChanges(staged);
  assert.deepEqual(rows.map(row => row.request_id), ['a', 'b']);
  assert.equal(rows[1].expected_version, 4);
  assert.deepEqual(rows[0].images, [{ local_media_id: 'local-photo' }]);
});

test('Date-only administrator edits remain staged and included in batch payload', () => {
  const original = { ...request, version: 9, images: [] };
  const staged = stageShippingDraft({}, original, { ...shippingDraft(original), ship_date: '2026-11-09' });
  assert.equal(shippingBatchChanges(staged)[0].ship_date, '2026-11-09');
  assert.equal(original.ship_date, '2026-10-27');
});
