import test from 'node:test';
import assert from 'node:assert/strict';
import { toDashboardEvent } from '../src/api/eventAdapter.js';
import { EVENT_TYPES, STATUSES } from '../src/data/events.js';

const record = { event_type: 'fall', alert_level: 'red', status: 'open', person_id: 0,
  timestamp: { toDate: () => new Date('2026-10-14T01:00:00Z') }, image_path: 'events/event-1.jpeg' };

test('maps the backend Firestore schema without incident fields', () => {
  assert.deepEqual(toDashboardEvent('event-1', record), {
    id: 'event-1', type: 'fall', severity: 'high', status: 'open', trackId: 0,
    occurredAt: '2026-10-14T01:00:00.000Z', completedAt: null, completedBy: null,
    imagePath: 'events/event-1.jpeg',
  });
});

test('all four backend types have dashboard labels', () => {
  for (const [event_type, type] of [['fall', 'fall'], ['sitting distress', 'prolonged_sitting'],
    ['isolation distress', 'isolation'], ['wandering distress', 'wandering']]) {
    assert.equal(toDashboardEvent('id', { ...record, event_type }).type, type);
    assert.ok(EVENT_TYPES[type]);
  }
});

test('uses recorded severity instead of guessing from the type', () => {
  for (const event_type of ['fall', 'sitting distress', 'isolation distress', 'wandering distress']) {
    assert.equal(toDashboardEvent('id', { ...record, event_type, alert_level: 'red' }).severity, 'high');
    assert.equal(toDashboardEvent('id', { ...record, event_type, alert_level: 'amber' }).severity, 'medium');
  }
});

test('completion keeps server identity and time without inventing an outcome', () => {
  const event = toDashboardEvent('id', { ...record, status: 'closed', completed_by: 'admin-uid',
    completed_at: '2026-10-14T02:00:00Z' });
  assert.equal(event.status, 'closed');
  assert.equal(event.completedBy, 'admin-uid');
  assert.equal(event.completedAt, '2026-10-14T02:00:00.000Z');
  assert.equal(event.outcome, undefined);
  assert.equal(STATUSES.closed, 'Completed');
});

test('missing and invalid data stays unknown instead of becoming a new alert today', () => {
  for (const value of [null, undefined, '', 'bad-date', {}, { toDate: () => new Date('bad') }]) {
    assert.equal(toDashboardEvent('id', { ...record, timestamp: value }).occurredAt, null);
  }
  const event = toDashboardEvent('id', { event_type: 'constructor', status: 'resolved', alert_level: 'invalid' });
  assert.equal(event.type, 'unknown');
  assert.equal(event.status, 'unknown');
  assert.equal(event.severity, 'unknown');
  assert.equal(event.imagePath, null);
});
