import { useEffect, useMemo, useState } from "react";
import { DETECTIONS, INCIDENTS } from "../data/mock.js";
import { usePrefersReducedMotion } from "../hooks/index.js";

/*
  This file is the seam between the UI and the backend.
  Nothing else in src/ knows where data comes from.

  To go live, keep the return shapes identical:

  useIncidentFeed()  -> [{ id, type, status, zoneId, ts: Date, note?, responder? }]
  useDetectionFeed() -> [{ id, conf, state, pose, box: { x, y, w, h } }]   // box in %

  Suggested real implementation:
    const ws = new WebSocket(import.meta.env.VITE_SAFE_WS_URL)
    ws.onmessage = (e) => setDetections(JSON.parse(e.data).detections)
*/

export function useIncidentFeed() {
  return INCIDENTS;
}

export function useDetectionFeed(zoneId, enabled = true) {
  const base = DETECTIONS[zoneId] || [];
  const [tick, setTick] = useState(0);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (!enabled || reduced) return;
    const t = setInterval(() => setTick((v) => v + 1), 900);
    return () => clearInterval(t);
  }, [enabled, reduced]);

  return useMemo(
    () =>
      base.map((d, i) => {
        const drift = reduced ? 0 : Math.sin((tick + i * 2) * 0.8) * 0.35;
        return { ...d, box: { ...d.box, x: d.box.x + drift, y: d.box.y + drift * 0.4 } };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [zoneId, tick, reduced]
  );
}
