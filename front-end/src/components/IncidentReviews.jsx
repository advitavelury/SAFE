import { useEffect, useRef, useState } from 'react';
import { collection, onSnapshot, orderBy, query } from 'firebase/firestore';
import { db, auth, INCIDENTS_COLLECTION } from '../api/firebase.js';
import { submitIncidentReview } from '../api/incidentReview.js';

const labels = { acknowledge: 'Acknowledged', resolve: 'Resolved: confirmed', false_alarm: 'Resolved: false alarm', add_note: 'Note added' };

export default function IncidentReviews({ incident, canUpdate }) {
  const [reviews, setReviews] = useState([]);
  const [loadState, setLoadState] = useState('loading');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const saving = useRef(false);
  useEffect(() => {
    setLoadState('loading');
    setReviews([]);
    return onSnapshot(query(collection(db, INCIDENTS_COLLECTION, incident.id, 'reviews'), orderBy('createdAt', 'asc')),
      { includeMetadataChanges: true }, (snapshot) => {
        setReviews(snapshot.docs.map(d => ({ id: d.id, ...d.data() })));
        setLoadState(snapshot.metadata.fromCache ? 'connecting' : 'ready');
      }, () => setLoadState('error'));
  }, [incident.id, attempt]);

  async function act(action) {
    if (!canUpdate || saving.current) return;
    saving.current = true;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await submitIncidentReview(db, auth.currentUser, incident.id, action, note, INCIDENTS_COLLECTION);
      setNote('');
      setMessage('Response saved.');
    } catch (err) {
      setError(err.code === 'permission-denied'
        ? 'Update denied. Check administrator access and the deployed Firebase rules.'
        : err.code ? 'Unable to save. Check your connection and try again.' : err.message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return <>
    <h3>Response history</h3>
    <ol className="timeline">
      <li><strong>Detected</strong><small>Detector · {new Date(incident.occurredAt).toLocaleString('en-AU')}</small></li>
      {reviews.map(review => <li key={review.id}>
        <strong>{labels[review.action] || review.action}</strong>
        <small>Admin {review.actorId} · {review.createdAt?.toDate ? review.createdAt.toDate().toLocaleString('en-AU') : 'Saving...'}</small>
        {review.note && <p className="note">{review.note}</p>}
      </li>)}
    </ol>
    {incident.notes.map((n, i) => <p className="note" key={i}>{n.text}<small>{n.actor}</small></p>)}
    {loadState === 'error' ? <div role="alert">Unable to load response history. <button className="text-button" onClick={() => retry(n => n + 1)}>Retry</button></div>
      : loadState !== 'ready' && <p role="status">Connecting to response history...</p>}
    {canUpdate ? <>
      <label className="field">Review note<textarea value={note} onChange={e => setNote(e.target.value)} disabled={busy} maxLength={1000}/></label>
      <div className="detail-actions">
        <button className="secondary" disabled={busy || !note.trim()} onClick={() => act('add_note')}>Add note</button>
        {incident.status === 'active' && <button className="primary" disabled={busy} onClick={() => act('acknowledge')}>Acknowledge</button>}
        {incident.status !== 'resolved' && <>
          <button className="secondary" disabled={busy} onClick={() => act('resolve')}>Resolve · confirmed</button>
          <button className="text-button" disabled={busy} onClick={() => act('false_alarm')}>Resolve as false alarm</button>
        </>}
      </div>
      {busy && <p role="status">Saving response...</p>}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </> : <p className="muted">Read-only staff access</p>}
  </>;
}
