import { collection, doc, runTransaction, serverTimestamp } from 'firebase/firestore';
import { canEditIncidents } from './staffAccess.js';

export function reviewTransition(incident, action, rawNote = '') {
  if (typeof rawNote !== 'string' || rawNote.length > 1000) {
    throw new Error('Review notes must be at most 1,000 characters.');
  }
  const note = rawNote.trim();
  const status = incident.status;
  const outcome = incident.outcome || (incident.type === 'false' ? 'false_alarm' : 'unconfirmed');
  if (!['active', 'acknowledged', 'resolved'].includes(status)) {
    throw new Error('This incident has an unsupported status.');
  }
  if (action === 'add_note' && note) return { status, outcome, note };
  if (action === 'acknowledge' && status === 'active') {
    return { status: 'acknowledged', outcome, note };
  }
  if (['resolve', 'false_alarm'].includes(action) && status !== 'resolved') {
    return { status: 'resolved', outcome: action === 'resolve' ? 'confirmed' : 'false_alarm', note };
  }
  throw new Error('This action is no longer available. Refresh the incident and try again.');
}

// Read the latest incident inside the transaction so concurrent reviews cannot
// overwrite a resolution. The matching immutable review is committed atomically.
export async function submitIncidentReview(db, user, incidentId, action, note, collectionName = 'incidents') {
  if (!user || user.isAnonymous) throw new Error('Administrator sign-in required.');
  const incidentRef = doc(db, collectionName, incidentId);
  const reviewRef = doc(collection(incidentRef, 'reviews'));
  await runTransaction(db, async (transaction) => {
    const profile = await transaction.get(doc(db, 'users', user.uid));
    if (!canEditIncidents(user, profile.data())) throw new Error('Administrator access required.');
    const incident = await transaction.get(incidentRef);
    if (!incident.exists()) throw new Error('This incident no longer exists.');
    const result = reviewTransition(incident.data(), action, note);
    transaction.update(incidentRef, {
      status: result.status, outcome: result.outcome, responder: user.uid,
      updatedAt: serverTimestamp(), lastReviewId: reviewRef.id,
    });
    transaction.set(reviewRef, {
      action, note: result.note, actorId: user.uid, createdAt: serverTimestamp(),
      status: result.status, outcome: result.outcome,
    });
  });
}
