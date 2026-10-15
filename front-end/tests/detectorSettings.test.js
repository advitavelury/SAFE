import test from 'node:test';
import assert from 'node:assert/strict';
import { thresholdPatch, fetchDetectorSettings, saveDetectorSettings } from '../src/api/detectorSettings.js';

const user = { getIdToken: async () => 'test-token' };
const saved = { sitting_seconds: 7200, isolation_seconds: 3600, sitting_warning_fraction: .5 };

test('30 seconds is sent unchanged and untouched settings are excluded', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ ...saved, sitting_seconds: 30 }));
  const result = await saveDetectorSettings(user, { ...saved, sitting_seconds: '30' }, saved);
  assert.equal(result.sitting_seconds, 30);
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, '/api/admin/detector-settings');
  assert.equal(options.method, 'PATCH');
  assert.equal(options.headers.Authorization, 'Bearer test-token');
  assert.deepEqual(JSON.parse(options.body), { sitting_seconds: 30 });
});

test('both duration fields use seconds without converting minutes', () => {
  assert.deepEqual(thresholdPatch({ sitting_seconds: 30, isolation_seconds: '45' }, saved),
    { sitting_seconds: 30, isolation_seconds: 45 });
  assert.deepEqual(thresholdPatch({ ...saved, sitting_seconds: '7200' }, saved), {});
});

test('blank, zero, negative, nonfinite and excessive durations cannot be saved', () => {
  for (const value of ['', ' ', 0, -1, null, undefined, Infinity, NaN, 'abc', 604801]) {
    assert.throws(() => thresholdPatch({ ...saved, sitting_seconds: value }, saved), /seconds/);
  }
});

test('load uses the backend snapshot rather than local browser defaults', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(saved));
  assert.deepEqual(await fetchDetectorSettings(user), saved);
  assert.equal(fetch.mock.calls[0].arguments[1].method, 'GET');
  assert.equal(fetch.mock.calls[0].arguments[1].cache, 'no-store');
});

test('signed-out, anonymous and cancelled requests cannot access settings', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(fetchDetectorSettings(null), /sign-in/);
  await assert.rejects(fetchDetectorSettings({ ...user, isAnonymous: true }), /sign-in/);
  await assert.rejects(fetchDetectorSettings(user, AbortSignal.abort()), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

test('permission, validation, backend and malformed-response errors are not success', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  for (const [status, message] of [[401, /Sign in again/], [403, /Administrator access/], [422, /Invalid thresholds/], [503, /Python backend/]]) {
    fetch.mock.mockImplementation(async () => new Response('', { status }));
    await assert.rejects(fetchDetectorSettings(user), message);
  }
  fetch.mock.mockImplementation(async () => Response.json({ sitting_seconds: '30' }));
  await assert.rejects(fetchDetectorSettings(user), /Unexpected/);
});
