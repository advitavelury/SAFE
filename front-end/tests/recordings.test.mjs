import test from 'node:test';
import assert from 'node:assert/strict';
import { createRecordingRequest, recordingOrigin } from '../src/api/recordingClient.js';

test('playback uses the browser detector, falling back to the legacy media origin', () => {
  assert.equal(recordingOrigin({ VITE_BROWSER_DETECTOR_ORIGIN: 'https://detector.test', VITE_MEDIA_API_ORIGIN: 'https://legacy.test' }), 'https://detector.test');
  assert.equal(recordingOrigin({ VITE_MEDIA_API_ORIGIN: 'https://legacy.test' }), 'https://legacy.test');
  assert.equal(recordingOrigin({}), null);
  assert.throws(() => recordingOrigin({ VITE_BROWSER_DETECTOR_ORIGIN: 'http://unsafe.test' }));
});

test('clip requests use fresh bearer auth without query tokens, cookies or caching', async () => {
  let calls = 0;
  const request = createRecordingRequest({ origin: 'https://detector.test',
    getUser: () => ({ getIdToken: async () => `token-${++calls}` }),
    fetchImpl: async (url, options) => {
      assert.equal(url, 'https://detector.test/api/incidents/incident-1/clip/file');
      assert.equal(options.headers.Authorization, `Bearer token-${calls}`);
      assert.equal(options.cache, 'no-store');
      assert.equal(options.credentials, 'omit');
      assert.equal(options.redirect, 'error');
      return new Response('video', { headers: { 'Content-Type': 'video/mp4' } });
    } });
  await request('incident-1', true);
  await request('incident-1', true);
  assert.equal(calls, 2);
  await assert.rejects(request('../secret', true), /Invalid incident ID/);
});

test('unapproved users and non-video responses never become playable blobs', async () => {
  const request = response => createRecordingRequest({ origin: 'https://detector.test',
    getUser: () => ({ getIdToken: async () => 'token' }), fetchImpl: async () => response });
  await assert.rejects(request(new Response('', { status: 403 }))('id', true), /administrator account is required/);
  await assert.rejects(request(new Response('<html>', { headers: { 'Content-Type': 'text/html' } }))('id', true), /did not return a video/);
  await assert.rejects(createRecordingRequest({ getUser: () => null, origin: null })('id', true), /sign-in required/);
});
