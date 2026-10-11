import test from 'node:test';
import assert from 'node:assert/strict';
import { createBrowserCamera, cameraErrorMessage } from '../src/api/browserCamera.js';

function stream(id = 'camera-1') {
  const track = new EventTarget();
  track.readyState = 'live';
  track.stop = () => { track.readyState = 'ended'; };
  track.getSettings = () => ({ deviceId: id });
  return { getTracks: () => [track], getVideoTracks: () => [track], track };
}
function setup(getUserMedia) {
  const states = [];
  const mediaDevices = new EventTarget();
  mediaDevices.getUserMedia = getUserMedia;
  mediaDevices.enumerateDevices = async () => [
    { kind: 'videoinput', deviceId: 'camera-1', label: 'Webcam' },
    { kind: 'audioinput', deviceId: 'mic-1', label: 'Microphone' },
  ];
  const camera = createBrowserCamera({ mediaDevices, secureContext: true, onChange: s => states.push(s) });
  return { camera, states, mediaDevices };
}

test('webcam starts only on request, uses video without audio and lists only cameras', async () => {
  const video = stream();
  let calls = 0;
  const { camera, states } = setup(async constraints => {
    calls++;
    assert.equal(constraints.audio, false);
    assert.deepEqual(constraints.video.deviceId, { exact: 'camera-1' });
    return video;
  });
  assert.equal(calls, 0);
  await camera.start('camera-1');
  assert.equal(states.at(-1).status, 'live');
  assert.equal(states.at(-1).devices.length, 1);
  camera.stop();
  assert.equal(video.track.readyState, 'ended');
  assert.equal(states.at(-1).stream, null);
  camera.dispose();
});

test('stop releases a stream arriving after a pending permission prompt', async () => {
  let resolve;
  const { camera, states } = setup(() => new Promise(r => { resolve = r; }));
  const pending = camera.start();
  camera.stop();
  const video = stream();
  resolve(video);
  await pending;
  assert.equal(video.track.readyState, 'ended');
  assert.equal(states.at(-1).status, 'idle');
  camera.dispose();
});

test('unmount releases pending streams without publishing later state', async () => {
  let resolve;
  const { camera, states } = setup(() => new Promise(r => { resolve = r; }));
  const pending = camera.start();
  camera.dispose();
  const count = states.length;
  const video = stream();
  resolve(video);
  await pending;
  assert.equal(video.track.readyState, 'ended');
  assert.equal(states.length, count);
});

test('switching camera stops old tracks and ignores superseded requests', async () => {
  const a = stream('a');
  const b = stream('b');
  const { camera, states } = setup(async c => c.video.deviceId.exact === 'a' ? a : b);
  await camera.start('a');
  await camera.start('b');
  assert.equal(a.track.readyState, 'ended');
  assert.equal(states.at(-1).deviceId, 'b');
  camera.dispose();
  assert.equal(b.track.readyState, 'ended');
});

test('camera disconnect clears the preview and releases tracks', async () => {
  const video = stream();
  const { camera, states } = setup(async () => video);
  await camera.start();
  video.track.dispatchEvent(new Event('ended'));
  assert.equal(states.at(-1).status, 'idle');
  assert.match(states.at(-1).message, /disconnected/);
  assert.equal(video.track.readyState, 'ended');
  camera.dispose();
});

test('permission rejection is recoverable and never exposes raw error details', async () => {
  const { camera, states } = setup(async () => { throw { name: 'NotAllowedError', message: 'private details' }; });
  await camera.start();
  assert.equal(states.at(-1).status, 'error');
  assert.match(states.at(-1).message, /permission/);
  assert.doesNotMatch(states.at(-1).message, /private details/);
  camera.dispose();
});

test('unsupported and insecure contexts never request camera permission', async () => {
  const states = [];
  let calls = 0;
  const camera = createBrowserCamera({ secureContext: false,
    mediaDevices: { getUserMedia: () => { calls++; } }, onChange: s => states.push(s) });
  await camera.start();
  assert.equal(calls, 0);
  assert.match(states.at(-1).message, /HTTPS/);
  camera.dispose();
  assert.match(cameraErrorMessage({ name: 'NotFoundError' }), /No camera/);
  assert.match(cameraErrorMessage({ name: 'NotReadableError' }), /other apps/);
  assert.match(cameraErrorMessage({ name: 'OverconstrainedError' }), /unavailable/);
});
