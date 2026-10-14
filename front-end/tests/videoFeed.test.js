import test from 'node:test';
import assert from 'node:assert/strict';
import { streamVideoFeed } from '../src/api/videoFeed.js';

const user = { isAnonymous: false, getIdToken: async () => 'TEST-token' };
const encoder = new TextEncoder();
const part = (data, type = 'image/jpeg') => `--frame\r\nContent-Type: ${type}\r\n\r\n${data}\r\n`;
function response(chunks, { open = false, onCancel = () => {} } = {}) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      if (!open) controller.close();
    },
    cancel: onCancel,
  }), { headers: { 'Content-Type': 'multipart/x-mixed-replace; boundary="frame"' } });
}

test('handles every-byte fragmentation in the existing backend format without Content-Length', async t => {
  const bytes = encoder.encode(part('first') + part('second') + '--frame\r\n');
  const fetch = t.mock.method(globalThis, 'fetch', async () => response([...bytes].map(b => Uint8Array.of(b))));
  const frames = [];
  await assert.rejects(streamVideoFeed(user, { onFrame: async blob => frames.push(await blob.text()) }), /feed ended/);
  assert.deepEqual(frames, ['first', 'second']);
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/video-feed');
  assert.equal(options.headers.Authorization, 'Bearer TEST-token');
  assert.equal(options.cache, 'no-store');
  assert.equal(options.signal.aborted, true);
});

test('coalesced frames display the newest complete frame rather than queueing old frames', async t => {
  t.mock.method(globalThis, 'fetch', async () => response([encoder.encode(part('old') + part('new') + '--frame\r\n')]));
  const frames = [];
  await assert.rejects(streamVideoFeed(user, { onFrame: async b => frames.push(await b.text()) }), /feed ended/);
  assert.deepEqual(frames, ['new']);
});

test('continuous feeds are not limited to 1000 parts or the default total upload size', async t => {
  const bytes = encoder.encode(Array.from({ length: 1050 }, () => part('x'.repeat(45000))).join('') + '--frame\r\n');
  t.mock.method(globalThis, 'fetch', async () => response([bytes]));
  let size = 0;
  await assert.rejects(streamVideoFeed(user, { onFrame: b => { size = b.size; } }), /feed ended/);
  assert.equal(size, 45000);
});

test('signed-out and anonymous users never send a request', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const account of [null, { ...user, isAnonymous: true }]) {
    await assert.rejects(streamVideoFeed(account), /Staff sign-in/);
  }
  assert.equal(fetch.mock.callCount(), 0);
});

test('an aborted connection does not send a token or emit frames', async t => {
  const controller = new AbortController();
  controller.abort();
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(streamVideoFeed(user, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

test('disconnect cancels a stalled reader and releases its lock', async t => {
  let cancelled = 0;
  const result = response([], { open: true, onCancel: () => cancelled++ });
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async () => { setTimeout(() => controller.abort(), 10); return result; });
  await assert.rejects(streamVideoFeed(user, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(cancelled, 1);
  assert.equal(result.body.locked, false);
});

test('no complete frames triggers an idle timeout and closes the reader', async t => {
  let cancelled = false;
  t.mock.method(globalThis, 'fetch', async () => response([encoder.encode(part('incomplete'))], {
    open: true, onCancel: () => { cancelled = true; },
  }));
  await assert.rejects(streamVideoFeed(user, { idleMs: 15 }), /No video frames received/);
  assert.equal(cancelled, true);
});

test('unauthorised, denied, offline and wrong-route responses fail clearly', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const [status, message] of [[401, /Sign in again/], [403, /active staff/], [502, /Start the Python backend/]]) {
    fetch.mock.mockImplementation(async () => new Response('', { status }));
    await assert.rejects(streamVideoFeed(user), message);
  }
  for (const type of ['text/html', 'multipart/x-mixed-replace']) {
    fetch.mock.mockImplementation(async () => new Response('', { headers: { 'Content-Type': type } }));
    await assert.rejects(streamVideoFeed(user), /Unexpected video response/);
  }
});

test('non-JPEG parts and oversized frames are rejected and cancelled', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  let cancelled = 0;
  for (const [body, message] of [
    [part('not a JPEG', 'text/plain') + '--frame\r\n', /Unexpected video frame format/],
    [part('x'.repeat(4 * 1024 * 1024 + 1)) + '--frame\r\n', /size exceeds/],
  ]) {
    fetch.mock.mockImplementation(async () => response([encoder.encode(body)], { open: true, onCancel: () => cancelled++ }));
    await assert.rejects(streamVideoFeed(user), message);
  }
  assert.equal(cancelled, 2);
});

test('disconnect during display does not emit another frame', async t => {
  let frames = 0;
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async () => response([
    encoder.encode(part('first') + '--frame\r\n'),
    encoder.encode('Content-Type: image/jpeg\r\n\r\nsecond\r\n--frame\r\n'),
  ]));
  await assert.rejects(streamVideoFeed(user, { signal: controller.signal, onFrame: () => { frames++; controller.abort(); } }), { name: 'AbortError' });
  assert.equal(frames, 1);
});

test('a display decoding failure closes the stream', async t => {
  let cancelled = false;
  t.mock.method(globalThis, 'fetch', async () => response([encoder.encode(part('invalid JPEG') + '--frame\r\n')], {
    open: true, onCancel: () => { cancelled = true; },
  }));
  await assert.rejects(streamVideoFeed(user, { onFrame: () => { throw new Error('Decode failed'); } }), /Decode failed/);
  assert.equal(cancelled, true);
});

test('a stalled token refresh times out without starting a stream', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(streamVideoFeed({ ...user, getIdToken: () => new Promise(() => {}) }, { idleMs: 15 }), /No video frames received/);
  assert.equal(fetch.mock.callCount(), 0);
});
