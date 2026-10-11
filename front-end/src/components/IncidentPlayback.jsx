import { useEffect, useRef, useState } from 'react';
import { Play, RefreshCw, VideoOff, Crosshair } from 'lucide-react';
import { recordingRequest, recordingServiceEnabled } from '../api/recordings.js';
import { useStaffSession } from '../api/StaffSession.jsx';
import { canReviewRecordings, isApprovedStaff } from '../api/staffAccess.js';

export default function IncidentPlayback({ incidentId }) {
  const session = useStaffSession();
  const canRead = session?.status === 'ready' && isApprovedStaff(session.user, session.profile);
  const canReview = session?.status === 'ready' && canReviewRecordings(session.user, session.profile);
  const uid = session?.user?.uid;
  const [state, setState] = useState({ status: 'loading' });
  const [url, setUrl] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const video = useRef(null);

  useEffect(() => {
    if (!canRead) {
      setUrl(null);
      setState({ status: 'restricted' });
      return;
    }
    if (!recordingServiceEnabled) {
      setUrl(null);
      setState({ status: 'unavailable', message: 'Recordings are not connected to this deployment.' });
      return;
    }
    const controller = new AbortController();
    let timer, objectUrl;
    let disposed = false;
    setState({ status: 'loading' });
    setUrl(null);

    async function load() {
      try {
        const response = await recordingRequest(incidentId, false, controller.signal);
        const info = await response.json();
        if (disposed) return;
        setState(info);
        if (info.status === 'ready' && canReview) {
          setState({ ...info, status: 'loading', message: 'Loading recording...' });
          const media = await recordingRequest(incidentId, true, controller.signal);
          const blob = await media.blob();
          if (disposed) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
          setState(info);
        } else if (['recording', 'processing'].includes(info.status)) {
          timer = setTimeout(load, 1500);
        }
      } catch (error) {
        if (!disposed) setState({ status: 'error', message: error.message });
      }
    }
    load();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [incidentId, attempt, canRead, canReview, uid]);

  if (!canRead) return <section className="incident-playback" aria-label="Incident recording">
    <h3>Incident recording</h3>
    <p role="note">Approved staff sign-in is required to view recording details.</p>
  </section>;

  const pending = ['loading', 'recording', 'processing'].includes(state.status);
  return <section className="incident-playback" aria-label="Incident recording">
    <h3>Incident recording</h3>
    {!canReview && <p role="note">Incident videos are available to administrators only.</p>}
    <div className={canReview ? 'playback-stage' : undefined}>
      {canReview && url && state.status === 'ready'
        ? <video ref={video} key={url} src={url} controls playsInline preload="metadata"
            aria-label="Incident video playback"
            onError={() => setState({ status: 'error', message: 'This recording could not be played.' })} />
        : <div className={canReview ? 'playback-message' : undefined} role={pending ? 'status' : 'note'}>
            {canReview && (pending ? <Play size={22} /> : <VideoOff size={22} />)}
            <p>{state.message || (state.status === 'ready' ? 'Recording ready.' : 'Loading recording...')}</p>
          </div>}
    </div>
    <div className="playback-actions">
      {state.status === 'ready' && <>
        <small>{Math.round(state.durationSeconds)}s · No audio{state.redacted ? ' · Redacted' : ''}{state.partial ? ' · Partial clip' : ''}</small>
        {canReview && <button type="button" className="text-button" title="Jump to alert" onClick={() => {
          if (video.current) video.current.currentTime = state.eventOffsetSeconds || 0;
        }}><Crosshair size={16} />Alert</button>}
      </>}
      {recordingServiceEnabled && !pending && state.status !== 'ready' && <button type="button" className="text-button"
        onClick={() => setAttempt(n => n + 1)}><RefreshCw size={15} />Retry</button>}
    </div>
  </section>;
}
