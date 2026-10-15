export const DURATION_FIELDS = [
  { key: 'sitting_seconds', label: 'Prolonged sitting threshold' },
  { key: 'isolation_seconds', label: 'Isolation threshold' },
];

export function thresholdPatch(draft, saved) {
  const patch = {};
  for (const { key, label } of DURATION_FIELDS) {
    const value = draft[key];
    const seconds = Number(value);
    if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === ''
        || !Number.isFinite(seconds) || seconds <= 0 || seconds > 604800) {
      throw new Error(`${label} must be greater than 0 and at most 604800 seconds.`);
    }
    if (seconds !== saved[key]) patch[key] = seconds;
  }
  return patch;
}

async function requestSettings(user, patch, signal) {
  if (!user || user.isAnonymous) throw new Error('Administrator sign-in required.');
  const token = await user.getIdToken();
  signal?.throwIfAborted();
  const response = await fetch('/api/admin/detector-settings', {
    method: patch ? 'PATCH' : 'GET', cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, ...(patch ? { 'Content-Type': 'application/json' } : {}) },
    body: patch ? JSON.stringify(patch) : undefined,
    signal: AbortSignal.any([signal, AbortSignal.timeout(15000)].filter(Boolean)),
  });
  if (response.status === 401) throw new Error('Sign in again to access detector settings.');
  if (response.status === 403) throw new Error('Administrator access is required to change detector settings.');
  if (response.status === 422) throw new Error('Invalid thresholds. Check the values in seconds.');
  if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Unable to load or save thresholds. Check that the Python backend is running.');
  }
  const settings = await response.json();
  if (!settings || DURATION_FIELDS.some(({ key }) => typeof settings[key] !== 'number'
      || !Number.isFinite(settings[key]) || settings[key] <= 0 || settings[key] > 604800)) {
    throw new Error('Unexpected detector settings response. Reload thresholds.');
  }
  return settings;
}

export const fetchDetectorSettings = (user, signal) => requestSettings(user, undefined, signal);
export const saveDetectorSettings = (user, draft, saved, signal) =>
  requestSettings(user, thresholdPatch(draft, saved), signal);
