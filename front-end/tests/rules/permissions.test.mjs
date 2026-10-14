import { after, before, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, getDoc, getDocs, setDoc, updateDoc, deleteDoc } from 'firebase/firestore';
import { createEventQuery } from '../../src/api/eventStore.js';
import { toDashboardEvent } from '../../src/api/eventAdapter.js';

let env;
const dbFor = uid => env.authenticatedContext(uid, { firebase: { sign_in_provider: 'password' } }).firestore();
const record = { person_id: 0, event_type: 'fall', alert_level: 'red', status: 'open',
  timestamp: new Date('2026-10-14T01:00:00Z'), image_path: 'events/event-1.jpeg' };

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
    await setDoc(doc(db, 'events/event-1'), record);
    await setDoc(doc(db, 'incidents/legacy'), { type: 'fall', createdAt: new Date() });
  });
});

test('approved admin and operator read the real events query and backend schema', async () => {
  for (const uid of ['admin', 'operator']) {
    const snapshot = await assertSucceeds(getDocs(createEventQuery(dbFor(uid))));
    assert.equal(snapshot.size, 1);
    const event = toDashboardEvent(snapshot.docs[0].id, snapshot.docs[0].data());
    assert.equal(event.id, 'event-1');
    assert.equal(event.trackId, 0);
    assert.equal(event.severity, 'high');
    assert.equal(event.status, 'open');
    assert.equal(event.occurredAt, record.timestamp.toISOString());
  }
});

test('query uses timestamp ordering and a 50-event limit, not createdAt', async () => {
  await env.withSecurityRulesDisabled(async context => {
    for (let i = 0; i < 55; i++) await setDoc(doc(context.firestore(), 'events', `ordered-${i}`), {
      ...record, timestamp: new Date(record.timestamp.getTime() + (i + 1) * 1000),
    });
  });
  const snapshot = await getDocs(createEventQuery(dbFor('operator')));
  assert.equal(snapshot.size, 50);
  assert.equal(snapshot.docs[0].id, 'ordered-54');
  assert.equal(snapshot.docs.at(-1).id, 'ordered-5');
});

test('unapproved, disabled, anonymous and signed-out users cannot read events', async () => {
  const databases = [dbFor('disabled'), dbFor('unknown'), env.unauthenticatedContext().firestore(),
    env.authenticatedContext('admin', { firebase: { sign_in_provider: 'anonymous' } }).firestore()];
  for (const db of databases) {
    await assertFails(getDoc(doc(db, 'events/event-1')));
    await assertFails(getDocs(createEventQuery(db)));
  }
});

test('all browser writes are denied, including admins bypassing backend completion', async () => {
  for (const uid of ['admin', 'operator', 'disabled', 'unknown']) {
    const db = dbFor(uid);
    await assertFails(setDoc(doc(db, 'events/new'), record));
    await assertFails(updateDoc(doc(db, 'events/event-1'), { status: 'closed', completed_by: uid }));
    await assertFails(deleteDoc(doc(db, 'events/event-1')));
    await assertFails(setDoc(doc(db, 'events/event-1/reviews/new'), { note: 'Bypass' }));
    await assertFails(updateDoc(doc(db, 'users', uid), { role: 'admin', active: true }));
  }
});

test('legacy incidents are inaccessible and staff can only read their own profile', async () => {
  for (const uid of ['admin', 'operator']) {
    const db = dbFor(uid);
    await assertFails(getDoc(doc(db, 'incidents/legacy')));
    await assertFails(setDoc(doc(db, 'incidents/new'), record));
    await assertSucceeds(getDoc(doc(db, 'users', uid)));
    await assertFails(getDoc(doc(db, 'users', uid === 'admin' ? 'operator' : 'admin')));
  }
});

test('staff deactivation denies subsequent event reads', async () => {
  const db = dbFor('operator');
  await assertSucceeds(getDocs(createEventQuery(db)));
  await env.withSecurityRulesDisabled(context => updateDoc(doc(context.firestore(), 'users/operator'), { active: false }));
  await assertFails(getDocs(createEventQuery(db)));
});
