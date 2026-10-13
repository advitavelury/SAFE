import { auth } from './firebase.js';

export async function recordingRequest(incidentId, file, signal) {
  if (!auth?.currentUser) throw new Error('Staff sign-in required.');
  const token = await auth.currentUser.getIdToken();
  const response = await fetch(`/api/incidents/${encodeURIComponent(incidentId)}/clip${file ? '/file' : ''}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(file ? 30000 : 5000)].filter(Boolean)),
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error('Recording access denied. Sign in with an approved staff account.');
  }
  if (response.status === 404) throw new Error('This recording is no longer available on the camera server.');
  if (!response.ok) throw new Error('Unable to load recording. Check the local camera server.');
  return response;
}
