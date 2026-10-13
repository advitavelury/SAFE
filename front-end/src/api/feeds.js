import { useEffect, useMemo, useState } from "react";
import {
  collection,
  limit,
  onSnapshot,
  orderBy,
  query,
} from "firebase/firestore";
import { DETECTIONS } from "../data/mock.js";
import { usePrefersReducedMotion } from "../hooks/index.js";
import {
  db,
  firebaseConfigured,
  INCIDENTS_COLLECTION,
} from "./firebase.js";

/*
  Incident records come from Firestore; camera detections are still simulated.

  To go live, keep the return shapes identical:

  useIncidentFeed()  -> { incidents: [{ id, type, status, zoneId, ts }], status, retry }
  useDetectionFeed() -> [{ id, conf, state, pose, box: { x, y, w, h } }]   // box in %

  Firestore incident shape:
    incidents/{id} -> {
      type: "fall" | "distress" | "false",
      status: "active" | "resolved",
      zoneId: "A",
      personId: "1",
      note: "Fall detected",
      ts: Firestore Timestamp,
      tsIso: ISO string fallback
    }
*/

function toDate(value, fallback = new Date()) {
  if (!value) return fallback;
  if (typeof value.toDate === "function") return value.toDate();
  if (typeof value === "string" || typeof value === "number") {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? fallback : parsed;
  }
  return fallback;
}

function normaliseIncident(doc) {
  const data = doc.data();
  const fallbackDate = toDate(data.tsIso || data.createdAtIso);

  return {
    id: doc.id,
    type: ["fall", "prolonged_sitting", "isolation", "wandering", "distress", "false"].includes(data.type) ? data.type : "distress",
    status: data.status || "active",
    zoneId: data.zoneId || data.zone_id || "A",
    ts: toDate(data.ts || data.createdAt, fallbackDate),
    note: data.note,
    responder: data.responder,
    outcome: data.outcome,
    updatedAt: data.updatedAt ? toDate(data.updatedAt) : null,
    source: data.source,
    personId: data.personId || data.person_id,
  };
}

export function useIncidentFeed() {
  const [feed, setFeed] = useState({ incidents: [], status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setFeed({ incidents: [], status: "loading" });

    if (!firebaseConfigured || !db) {
      setFeed({ incidents: [], status: "error" });
      return undefined;
    }

    const incidentsQuery = query(
      collection(db, INCIDENTS_COLLECTION),
      orderBy("createdAt", "desc"),
      limit(50)
    );

    const unsubscribe = onSnapshot(incidentsQuery, { includeMetadataChanges: true },
      (snapshot) => {
        if (cancelled) return;
        setFeed(snapshot.metadata.fromCache
          ? { incidents: [], status: "connecting" }
          : { incidents: snapshot.docs.map(normaliseIncident), status: "ready" });
      },
      () => {
        if (!cancelled) setFeed({ incidents: [], status: "error" });
      });

    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [attempt]);

  return { ...feed, retry: () => setAttempt((n) => n + 1) };
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
