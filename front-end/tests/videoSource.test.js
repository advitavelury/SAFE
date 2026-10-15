import test from 'node:test';
import assert from 'node:assert/strict';
import { getVideoSource, selectVideoSource, stopVideoSource } from '../src/api/videoSource.js';
import { streamVideoFeed } from '../src/api/videoFeed.js';

const user = { getIdToken: async () => 'test-token' };
const status = { mode: 'video', state: 'running', generation: 3 };

test('source status, selection and stop use authenticated requests without tokens in URLs', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(status));
  assert.deepEqual(await getVideoSource(user), status);
  await selectVideoSource(user, 'video');
  await selectVideoSource(user, 'live');
  await stopVideoSource(user);
  assert.deepEqual(fetch.mock.calls.map(c => c.arguments[1].method), ['GET', 'POST', 'POST', 'DELETE']);
  for (const call of fetch.mock.calls) {
    assert.equal(call.arguments[0], '/api/video-source');
    assert.equal(call.arguments[1].headers.Authorization, 'Bearer test-token');
    assert.equal(call.arguments[1].cache, 'no-store');
  }
  assert.equal(fetch.mock.calls[1].arguments[1].body, '{"mode":"video"}');
});

test('signed-out, anonymous, invalid mode and aborted calls cannot select a source', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(selectVideoSource(null, 'live'), /Staff sign-in/);
  await assert.rejects(selectVideoSource({ ...user, isAnonymous: true }, 'live'), /Staff sign-in/);
  await assert.rejects(selectVideoSource(user, '/private/video.mp4'), /Unsupported/);
  await assert.rejects(getVideoSource(user, AbortSignal.abort()), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

test('auth failures and original launcher produce actionable errors', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const [code, message] of [[401, /Sign in again/], [403, /active staff/], [503, /backend.dashboard/]]) {
    fetch.mock.mockImplementation(async () => new Response('', { status: code }));
    await assert.rejects(getVideoSource(user), message);
  }
  fetch.mock.mockImplementation(async () => new Response('<html>'));
  await assert.rejects(getVideoSource(user), /backend.dashboard/);
});

test('malformed source status is rejected instead of starting an unscoped stream', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const change of [{ generation: -1 }, { generation: '3' }, { mode: 'file' }, { state: 'unknown' }]) {
    fetch.mock.mockImplementation(async () => Response.json({ ...status, ...change }));
    await assert.rejects(getVideoSource(user), /Unexpected video source/);
  }
});

test('stream is scoped to selected generation and reports stale sessions', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 409 }));
  await assert.rejects(streamVideoFeed(user, { generation: 3 }), /source changed/);
  assert.equal(fetch.mock.calls[0].arguments[0], '/api/video-feed?generation=3');
  for (const generation of [-1, '3', 1.5]) {
    await assert.rejects(streamVideoFeed(user, { generation }), /generation/);
  }
  assert.equal(fetch.mock.callCount(), 1);
});
