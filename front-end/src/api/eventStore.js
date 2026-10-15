import { collection, limit, orderBy, query } from 'firebase/firestore';

// Keep the read contract aligned with backend/event.py, not the retired incident schema.
export const EVENTS_COLLECTION = 'events';

export function createEventQuery(db) {
  return query(collection(db, EVENTS_COLLECTION), orderBy('timestamp', 'desc'), limit(50));
}
