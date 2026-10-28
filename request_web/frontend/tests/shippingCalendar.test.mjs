import assert from 'node:assert/strict';
import test from 'node:test';
import { chinaToday, monthDays, shiftMonth, urgency, groupRequests, matchesSearch } from '../src/shippingCalendar.ts';
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
