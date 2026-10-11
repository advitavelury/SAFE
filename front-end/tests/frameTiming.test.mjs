import test from 'node:test';
import assert from 'node:assert/strict';
import { nextFrameDelay, frameMetrics } from '../src/api/frameTiming.js';

test('frame pacing caps fast requests without adding a pause after slow requests', () => {
  assert.equal(nextFrameDelay(20), 80);
  assert.equal(nextFrameDelay(100), 0);
  assert.equal(nextFrameDelay(650), 0);
  assert.equal(nextFrameDelay(-1), 100);
});

test('reported detection FPS includes the complete interval between returned frames', () => {
  const first = frameMetrics(null, 500, 0);
  assert.equal(first.fps, 2);
  assert.equal(first.latencyMs, 500);
  const second = frameMetrics(first, 1000, 600);
  assert.equal(second.fps, 2);
  assert.equal(second.latencyMs, 400);
});

test('zero duration samples remain finite', () => {
  const metric = frameMetrics(null, 1, 1);
  assert.ok(Number.isFinite(metric.fps));
  assert.equal(metric.latencyMs, 1);
  assert.equal(metric.fps, 10);
});
