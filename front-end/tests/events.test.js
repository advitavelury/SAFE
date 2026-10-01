import test from 'node:test';
import assert from 'node:assert/strict';
import { seedEvents, transitionEvent } from '../src/data/events.js';
test('acknowledgement and false alarm preserve detector type and audit history', () => {
 const initial = seedEvents()[0];
 const ack = transitionEvent(initial, 'acknowledge', 'staff-1', 'Checking camera', '2026-09-10T01:00:00Z');
 assert.equal(ack.status, 'acknowledged');
 assert.equal(initial.history.length, 1);
 assert.equal(ack.notes[0].text, 'Checking camera');
 const closed = transitionEvent(ack, 'false_alarm', 'staff-1');
 assert.equal(closed.status, 'resolved');
 assert.equal(closed.outcome, 'false_alarm');
 assert.equal(closed.type, 'fall');
 assert.equal(closed.history.length, 3);
 assert.equal(transitionEvent(closed, 'acknowledge', 'staff-2'), closed);
});
test('duplicate acknowledgement and invalid actions do not add history', () => {
 const ack = transitionEvent(seedEvents()[0], 'acknowledge', 'staff-1');
 assert.equal(transitionEvent(ack, 'acknowledge', 'staff-1'), ack);
 assert.equal(transitionEvent(ack, 'delete', 'staff-1'), ack);
});
test('direct confirmed resolution records reviewer and ignores blank notes', () => {
 const result = transitionEvent(seedEvents()[0], 'resolve', 'staff-2', '   ');
 assert.equal(result.outcome, 'confirmed');
 assert.equal(result.assignedTo, 'staff-2');
 assert.equal(result.notes.length, 0);
 assert.equal(result.status, 'resolved');
});
