import test from 'node:test';
import assert from 'node:assert/strict';
import { toAdminEvent } from '../src/api/incidentAdapter.js';

const incident = { id: 'fall-test', type: 'fall', status: 'active', zoneId: 'A',
  ts: new Date('2026-10-01T00:00:00Z'), personId: '7', note: 'TEST ONLY', source: 'safe-integration-test' };

test('administrator review outcome and update time survive the live adapter', () => {
  const updatedAt = new Date('2026-10-01T01:00:00Z');
  const event = toAdminEvent({ ...incident, status: 'resolved', outcome: 'false_alarm', updatedAt, responder: 'admin-uid' });
  assert.equal(event.outcome, 'false_alarm');
  assert.equal(event.updatedAt, updatedAt.toISOString());
  assert.equal(event.assignedTo, 'admin-uid');
  assert.equal(event.notes[0].actor, 'Detector');
});

test('Firebase records map to the team dashboard without demo identities', () => {
  const event = toAdminEvent(incident);
  assert.equal(event.type, 'fall');
  assert.equal(event.severity, 'high');
  assert.equal(event.trackId, '7');
  assert.equal(event.source, 'safe-integration-test');
  assert.equal(event.notes[0].text, 'TEST ONLY');
  assert.equal(event.occurredAt, incident.ts.toISOString());
});

test('all current detector types retain their labels', () => {
  for (const type of ['fall', 'prolonged_sitting', 'isolation', 'wandering', 'distress']) {
    assert.equal(toAdminEvent({ ...incident, type }).type, type);
  }
  assert.equal(toAdminEvent({ ...incident, type: 'unknown' }).type, 'distress');
});
