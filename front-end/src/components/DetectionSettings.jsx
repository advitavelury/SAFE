import { useEffect, useRef, useState } from 'react';
import { SlidersHorizontal, RefreshCw, Save, Undo2 } from 'lucide-react';
import { useStaffSession } from '../api/StaffSession.jsx';
import { DURATION_FIELDS, fetchDetectorSettings, saveDetectorSettings } from '../api/detectorSettings.js';

export default function DetectionSettings({ canUpdate }) {
  const { user } = useStaffSession() ?? {};
  const request = useRef(null);
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setSaved(null);
    setDraft({});
    setError('');
    setMessage('');
    if (!canUpdate) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    fetchDetectorSettings(user, controller.signal).then(settings => {
      if (controller.signal.aborted) return;
      setSaved(settings);
      setDraft(settings);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof TypeError ? 'Cannot reach the Python backend.' : failure.message);
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [user, canUpdate, attempt]);

  async function save(event) {
    event.preventDefault();
    if (!canUpdate || busy || !saved) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const settings = await saveDetectorSettings(user, draft, saved, controller.signal);
      if (controller.signal.aborted) return;
      setSaved(settings);
      setDraft(settings);
      setMessage('Thresholds saved.');
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof TypeError ? 'Cannot reach the Python backend. Changes were not confirmed.' : failure.message);
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  const dirty = saved && DURATION_FIELDS.some(({ key }) => String(draft[key]) !== String(saved[key]));
  return <section className="surface settings-card" aria-label="Detection thresholds">
    <div className="section-heading"><h2><SlidersHorizontal size={20}/> Detection thresholds</h2>
      {canUpdate && <button type="button" className="text-button" title="Reload thresholds" aria-label="Reload thresholds"
        disabled={busy} onClick={() => setAttempt(n => n + 1)}><RefreshCw size={18}/></button>}
    </div>
    {!canUpdate ? <p>Administrator access required for detector settings.</p> : <form onSubmit={save}>
      <fieldset disabled={busy || !saved} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        {DURATION_FIELDS.map(({ key, label }) => <label className="field" key={key} htmlFor={key}>{label}
          <div className="unit-input"><input id={key} type="number" min="0.001" max="604800" step="any" required
            value={draft[key] ?? ''} onChange={event => { setDraft({ ...draft, [key]: event.target.value }); setMessage(''); }}/>
            <span>seconds</span></div>
        </label>)}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="secondary flex items-center gap-2" disabled={!dirty}
            onClick={() => { setDraft(saved); setMessage('Unsaved changes discarded.'); setError(''); }}><Undo2 size={16}/> Discard</button>
          <button type="submit" className="primary flex items-center gap-2" disabled={!dirty}><Save size={16}/> Save thresholds</button>
        </div>
      </fieldset>
      {error && <p role="alert">{error}</p>}
      <p role="status">{busy ? 'Connecting to detector settings...' : message}</p>
    </form>}
  </section>;
}
