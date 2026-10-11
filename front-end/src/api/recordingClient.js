import { mediaOrigin, mediaUrl } from './deploymentConfig.js';

export function recordingOrigin(env) {
  const detector = env.VITE_BROWSER_DETECTOR_ORIGIN?.trim();
  return mediaOrigin(detector || env.VITE_MEDIA_API_ORIGIN || '', env.DEV);
}

export function createRecordingRequest({ getUser, origin, fetchImpl = fetch }) {
  return async (incidentId, file, signal) => {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(incidentId)) throw new Error('Invalid incident ID.');
    const user = getUser();
    if (!user) throw new Error('Staff sign-in required.');
    const token = await user.getIdToken();
    const response = await fetchImpl(mediaUrl(origin, `/api/incidents/${incidentId}/clip${file ? '/file' : ''}`), {
      headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', redirect: 'error', credentials: 'omit',
      signal: AbortSignal.any([signal, AbortSignal.timeout(file ? 30000 : 5000)].filter(Boolean)),
    });
    if (response.status === 401 || response.status === 403) {
      throw new Error(file
        ? 'Recording access denied. An approved administrator account is required.'
        : 'Recording details access denied. Approved staff access is required.');
    }
    if (response.status === 404) throw new Error('This recording is no longer available on the camera server.');
    if (!response.ok) throw new Error('Unable to load recording. Check the camera service.');
    if (file && !response.headers.get('content-type')?.startsWith('video/mp4')) {
      throw new Error('The camera server did not return a video recording.');
    }
    return response;
  };
}
