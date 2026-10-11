export const FRAME_INTERVAL_MS = 100;

export function nextFrameDelay(elapsedMs) {
  return Math.max(0, FRAME_INTERVAL_MS - Math.max(0, elapsedMs));
}

export function frameMetrics(previous, completedAt, startedAt) {
  const latencyMs = Math.max(1, completedAt - startedAt);
  const interval = previous ? Math.max(1, completedAt - previous.completedAt) : Math.max(FRAME_INTERVAL_MS, latencyMs);
  const sample = 1000 / interval;
  return { completedAt, latencyMs: Math.round(latencyMs),
    fps: previous ? previous.fps * 0.7 + sample * 0.3 : sample };
}
