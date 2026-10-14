import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchEvent, completeEvent } from '../src/api/events.js';
import { canEditEvents } from '../src/api/staffAccess.js';

const user = { uid: 'admin', isAnonymous: false, getIdToken: async () => 'test-token' };

test('only approved admins can complete events in the UI', () => {
  assert.equal(canEditEvents(user, { role: 'admin', active: true }), true);
  for (const profile of [null, {}, { role: 'operator', active: true }, { role: 'admin', active: false }]) {
    assert.equal(canEditEvents(user, profile), false);
  }
  assert.equal(canEditEvents({ ...user, isAnonymous: true }, { role: 'admin', active: true }), false);
});

test('event details use the authenticated backend, not a clip endpoint', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ id: 'event-1', image_url: 'https://example.test/image' }));
  const event = await fetchEvent(user, 'event-1');
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/events/event-1');
  assert.equal(options.method, 'GET');
  assert.equal(options.headers.Authorization, 'Bearer test-token');
  assert.equal(options.cache, 'no-store');
  assert.equal(event.id, 'event-1');
});

test('completion uses existing backend endpoint without a forged identity', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ id: 'event-1', status: 'closed' }));
  assert.equal((await completeEvent(user, 'event-1')).status, 'closed');
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/events/event-1/complete');
  assert.equal(options.method, 'POST');
  assert.equal(options.body, undefined);
  assert.equal(options.headers.Authorization, 'Bearer test-token');
});

test('signed-out, anonymous and invalid IDs never make requests', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const account of [null, { ...user, isAnonymous: true }]) {
    await assert.rejects(fetchEvent(account, 'id'), /Staff sign-in/);
  }
  for (const id of ['', 'a/b', undefined]) await assert.rejects(completeEvent(user, id), /Invalid event ID/);
  assert.equal(fetch.mock.callCount(), 0);
});

test('permission, missing-event and backend errors are actionable', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const [status, message] of [[401, /Sign in again/], [403, /Administrator access/], [404, /no longer available/], [503, /Python backend/]]) {
    fetch.mock.mockImplementation(async () => Response.json({}, { status }));
    await assert.rejects(completeEvent(user, 'id'), message);
  }
  fetch.mock.mockImplementation(async () => new Response('<html/>', { headers: { 'content-type': 'text/html' } }));
  await assert.rejects(fetchEvent(user, 'id'), /Python backend/);
});

test('event IDs are encoded and cancellation reaches fetch', async t => {
  const controller = new AbortController();
  controller.abort();
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({}));
  await fetchEvent(user, 'id ?#', controller.signal);
  assert.equal(fetch.mock.calls[0].arguments[0], '/api/events/id%20%3F%23');
  assert.equal(fetch.mock.calls[0].arguments[1].signal.aborted, true);
});
