import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewTransition } from '../src/api/incidentReview.js';
import { canEditIncidents } from '../src/api/staffAccess.js';

const incident = { status: 'active', type: 'fall', note: 'Original detection' };
test('only active non-anonymous administrators can edit', () => {
  const user = { uid: 'admin', isAnonymous: false };
  assert.equal(canEditIncidents(user, { role: 'admin', active: true }), true);
  for (const profile of [null, { role: 'operator', active: true }, { role: 'admin', active: false }, { role: 'admin', active: 'true' }]) {
    assert.equal(canEditIncidents(user, profile), false);
  }
  assert.equal(canEditIncidents(null, { role: 'admin', active: true }), false);
  assert.equal(canEditIncidents({ ...user, isAnonymous: true }, { role: 'admin', active: true }), false);
});
test('supported review transitions preserve original incident data', () => {
  assert.deepEqual(reviewTransition(incident, 'acknowledge', ' Checked '), { status: 'acknowledged', outcome: 'unconfirmed', note: 'Checked' });
  assert.equal(reviewTransition(incident, 'resolve').outcome, 'confirmed');
  assert.equal(reviewTransition(incident, 'false_alarm').outcome, 'false_alarm');
  assert.equal(incident.note, 'Original detection');
  assert.equal(incident.status, 'active');
});
test('resolved incidents only accept additional notes, never stale status updates', () => {
  const resolved = { ...incident, status: 'resolved', outcome: 'false_alarm' };
  for (const action of ['acknowledge', 'resolve', 'false_alarm', 'unknown']) {
    assert.throws(() => reviewTransition(resolved, action));
  }
  assert.deepEqual(reviewTransition(resolved, 'add_note', 'Follow-up'), { status: 'resolved', outcome: 'false_alarm', note: 'Follow-up' });
});
test('review input validation rejects empty notes and oversized content', () => {
  assert.throws(() => reviewTransition(incident, 'add_note', '  '));
  assert.throws(() => reviewTransition(incident, 'add_note', 'x'.repeat(1001)));
  assert.throws(() => reviewTransition(incident, 'add_note', {}));
  assert.throws(() => reviewTransition({ ...incident, status: 'unknown' }, 'resolve'));
  assert.throws(() => reviewTransition({ ...incident, status: 'acknowledged' }, 'acknowledge'));
  assert.equal(reviewTransition(incident, 'add_note', 'x'.repeat(1000)).note.length, 1000);
});
