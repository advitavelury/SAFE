import { after, before, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, getDoc, setDoc, updateDoc, deleteDoc, writeBatch, serverTimestamp } from 'firebase/firestore';
import { submitIncidentReview } from '../../src/api/incidentReview.js';

let env;
const user = uid => ({ uid, isAnonymous: false });
const dbFor = uid => env.authenticatedContext(uid, { firebase: { sign_in_provider: 'password' } }).firestore();
const parent = db => doc(db, 'incidents/event-1');
const review = (db, id = 'review-1') => doc(db, 'incidents/event-1/reviews', id);
before(async () => {
  env = await initializeTestEnvironment({ projectId: 'demo-safe-roles', firestore: {
    host: '127.0.0.1', port: 8088,
    rules: await readFile(new URL('../../../firestore.rules', import.meta.url), 'utf8'),
  } });
});
after(async () => { await env?.cleanup(); });
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async context => {
    const db = context.firestore();
    for (const [uid, role, active] of [['admin', 'admin', true], ['operator', 'operator', true], ['disabled', 'admin', false]]) {
      await setDoc(doc(db, 'users', uid), { role, active });
    }
    await setDoc(parent(db), { type: 'fall', status: 'active', note: 'Original detection', createdAt: new Date(), zoneId: 'A' });
  });
});

function batchReview(db, { action = 'acknowledge', status = 'acknowledged', outcome = 'unconfirmed', actorId = 'admin', note = '', extra = {}, id = 'review-1' } = {}) {
  const batch = writeBatch(db);
  batch.update(parent(db), { status, outcome, responder: actorId, updatedAt: serverTimestamp(), lastReviewId: id, ...extra });
  batch.set(review(db, id), { action, status, outcome, actorId, note, createdAt: serverTimestamp() });
  return batch.commit();
}

test('active admin and operator read incidents; others cannot', async () => {
  for (const uid of ['admin', 'operator']) await assertSucceeds(getDoc(parent(dbFor(uid))));
  for (const uid of ['disabled', 'unknown']) await assertFails(getDoc(parent(dbFor(uid))));
  await assertFails(getDoc(parent(env.unauthenticatedContext().firestore())));
  await assertFails(getDoc(parent(env.authenticatedContext('admin', { firebase: { sign_in_provider: 'anonymous' } }).firestore())));
});
test('real transaction supports acknowledge, resolve and notes with immutable history', async () => {
  const db = dbFor('admin');
  await assertSucceeds(submitIncidentReview(db, user('admin'), 'event-1', 'acknowledge', 'Checked'));
  await assertSucceeds(submitIncidentReview(db, user('admin'), 'event-1', 'resolve', 'Confirmed'));
  await assertSucceeds(submitIncidentReview(db, user('admin'), 'event-1', 'add_note', 'Follow-up'));
  const data = (await getDoc(parent(db))).data();
  assert.equal(data.status, 'resolved');
  assert.equal(data.outcome, 'confirmed');
  assert.equal(data.note, 'Original detection');
  const entry = review(db, data.lastReviewId);
  assert.equal((await getDoc(entry)).data().actorId, 'admin');
  await assertFails(updateDoc(entry, { note: 'Tampered' }));
  await assertFails(deleteDoc(entry));
  await assertSucceeds(getDoc(review(dbFor('operator'), data.lastReviewId)));
});
test('operators cannot write even when bypassing the application', async () => {
  const db = dbFor('operator');
  await assertFails(batchReview(db, { actorId: 'operator' }));
  await assertFails(updateDoc(parent(db), { status: 'resolved' }));
  await assertFails(setDoc(review(db), { note: 'Bypass' }));
  await assertFails(deleteDoc(parent(db)));
});
test('unapproved and disabled admins cannot write', async () => {
  for (const uid of ['disabled', 'unknown']) await assertFails(batchReview(dbFor(uid), { actorId: uid }));
});
test('admins cannot alter detection data, invent incidents or self-promote accounts', async () => {
  const db = dbFor('admin');
  await assertFails(batchReview(db, { extra: { type: 'false' } }));
  await assertFails(batchReview(db, { extra: { note: 'Rewritten detection' } }));
  await assertFails(setDoc(doc(db, 'incidents/new'), { type: 'fall' }));
  await assertFails(deleteDoc(parent(db)));
  await assertFails(updateDoc(doc(db, 'users/admin'), { role: 'operator' }));
  await assertFails(updateDoc(doc(dbFor('operator'), 'users/operator'), { role: 'admin' }));
});
test('writes require atomic matching audit with genuine actor and valid transition', async () => {
  const db = dbFor('admin');
  await assertFails(updateDoc(parent(db), { status: 'acknowledged', outcome: 'unconfirmed', responder: 'admin', updatedAt: serverTimestamp(), lastReviewId: 'missing' }));
  await assertFails(setDoc(review(db), { action: 'acknowledge', status: 'acknowledged', outcome: 'unconfirmed', actorId: 'admin', note: '', createdAt: serverTimestamp() }));
  await assertFails(batchReview(db, { actorId: 'operator' }));
  await assertFails(batchReview(db, { action: 'reopen' }));
  await assertFails(batchReview(db, { action: 'add_note', note: '' }));
  await assertFails(batchReview(db, { note: 'x'.repeat(1001) }));
});
test('false alarm resolves without changing detector type; stale responses fail', async () => {
  const db = dbFor('admin');
  await assertSucceeds(batchReview(db, { action: 'false_alarm', status: 'resolved', outcome: 'false_alarm' }));
  const data = (await getDoc(parent(db))).data();
  assert.equal(data.type, 'fall');
  assert.equal(data.outcome, 'false_alarm');
  await assertFails(batchReview(db, { id: 'stale-review' }));
  await assert.rejects(submitIncidentReview(db, user('admin'), 'event-1', 'resolve', 'Stale'));
});
test('role demotion immediately prevents subsequent Firestore writes', async () => {
  const db = dbFor('admin');
  await assertSucceeds(batchReview(db));
  await env.withSecurityRulesDisabled(context => updateDoc(doc(context.firestore(), 'users/admin'), { role: 'operator' }));
  await assertFails(batchReview(db, { action: 'resolve', status: 'resolved', outcome: 'confirmed', id: 'after-demotion' }));
});
