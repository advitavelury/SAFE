import { useEffect, useMemo, useState } from 'react';
import { onSnapshot } from 'firebase/firestore';
import { DETECTIONS } from '../data/mock.js';
import { usePrefersReducedMotion } from '../hooks/index.js';
import { db, firebaseConfigured } from './firebase.js';
import { toDashboardEvent } from './eventAdapter.js';
import { createEventQuery } from './eventStore.js';

export function useEventFeed() {
  const [feed, setFeed] = useState({ events: [], status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setFeed({ events: [], status: 'loading' });
    if (!firebaseConfigured || !db) {
      setFeed({ events: [], status: 'error' });
      return;
    }
    const unsubscribe = onSnapshot(createEventQuery(db), { includeMetadataChanges: true },
      snapshot => {
        if (cancelled) return;
        setFeed(snapshot.metadata.fromCache
          ? { events: [], status: 'connecting' }
          : { events: snapshot.docs.map(doc => toDashboardEvent(doc.id, doc.data())), status: 'ready' });
      }, error => {
        if (!cancelled) setFeed({ events: [], status: 'error', errorCode: error.code });
      });
    return () => { cancelled = true; unsubscribe(); };
  }, [attempt]);

  return { ...feed, retry: () => setAttempt(n => n + 1) };
}

// Retained only for the unused prototype CameraStage component.
export function useDetectionFeed(zoneId, enabled = true) {
  const base = DETECTIONS[zoneId] || [];
  const [tick, setTick] = useState(0);
  const reduced = usePrefersReducedMotion();
  useEffect(() => {
    if (!enabled || reduced) return;
    const timer = setInterval(() => setTick(value => value + 1), 900);
    return () => clearInterval(timer);
  }, [enabled, reduced]);
  return useMemo(() => base.map((d, i) => {
    const drift = reduced ? 0 : Math.sin((tick + i * 2) * 0.8) * 0.35;
    return { ...d, box: { ...d.box, x: d.box.x + drift, y: d.box.y + drift * 0.4 } };
  }), [base, tick, reduced]);
}
