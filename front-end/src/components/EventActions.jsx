import { useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { completeEvent } from '../api/events.js';
import { useStaffSession } from '../api/StaffSession.jsx';

export default function EventActions({ event, canUpdate }) {
  const { user } = useStaffSession();
  const [busy, setBusy] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState('');
  const saving = useRef(false);

  async function complete() {
    if (!canUpdate || event.status !== 'open' || saving.current || completed) return;
    saving.current = true;
    setBusy(true);
    setError('');
    try {
      await completeEvent(user, event.id);
      setCompleted(true);
    } catch (err) {
      setError(err instanceof TypeError
        ? 'Unable to complete the event. Check that the Python backend is running.' : err.message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return <section aria-label="Event response">
    <h3>Response</h3>
    {event.status === 'closed' ? <p>Completed{event.completedBy ? ` by ${event.completedBy}` : ''}.</p>
      : canUpdate && event.status === 'open' ? <button type="button" className="primary" disabled={busy || completed} onClick={complete}>
          <Check size={16} aria-hidden="true"/>{busy ? 'Completing...' : completed ? 'Completed' : 'Mark complete'}
        </button>
      : <p className="muted">{canUpdate ? 'Event status unavailable.' : 'Read-only staff access'}</p>}
    {completed && event.status !== 'closed' && <p role="status">Event completed. Waiting for the event list to update.</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
