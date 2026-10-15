import { useEffect, useState } from 'react';
import { ImageOff, RefreshCw } from 'lucide-react';
import { fetchEvent } from '../api/events.js';
import { useStaffSession } from '../api/StaffSession.jsx';

export default function EventSnapshot({ event }) {
  const { user } = useStaffSession();
  const [state, setState] = useState({ status: 'loading' });
  const [attempt, retry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    setState({ status: 'loading' });
    if (!event.imagePath) {
      setState({ status: 'unavailable', message: 'No snapshot was saved for this event.' });
      return () => { disposed = true; controller.abort(); };
    }
    fetchEvent(user, event.id, controller.signal).then(record => {
      if (disposed) return;
      const url = new URL(record.image_url);
      if (url.protocol !== 'https:') throw new Error('Snapshot URL is unavailable.');
      setState({ status: 'ready', url: url.href });
    }).catch(error => {
      if (!disposed) setState({ status: 'error', message: error instanceof TypeError
        ? 'Unable to load the snapshot. Check that the Python backend is running.' : error.message });
    });
    return () => { disposed = true; controller.abort(); };
  }, [event.id, event.imagePath, user, attempt]);

  return <section className="event-snapshot" aria-label="Event snapshot">
    <h3>Event snapshot</h3>
    <div className="snapshot-stage">
      {state.status === 'ready'
        ? <img src={state.url} alt={`Saved snapshot for event ${event.id}`} referrerPolicy="no-referrer"
            onError={() => setState({ status: 'error', message: 'Snapshot unavailable or expired. Retry to refresh it.' })}/>
        : <div className="snapshot-message" role={state.status === 'error' ? 'alert' : 'status'}>
            <ImageOff size={22}/><p>{state.message || 'Loading snapshot...'}</p>
          </div>}
    </div>
    {state.status === 'error' && <button type="button" className="text-button" onClick={() => retry(n => n + 1)}>
      <RefreshCw size={15}/>Retry
    </button>}
  </section>;
}
