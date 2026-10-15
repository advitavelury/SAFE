async function sourceRequest(user, method, mode, signal) {
  if (!user || user.isAnonymous) throw new Error('Staff sign-in required.');
  const token = await user.getIdToken();
  signal?.throwIfAborted();
  const response = await fetch('/api/video-source', {
    method, cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
    body: method === 'POST' ? JSON.stringify({ mode }) : undefined,
    signal: AbortSignal.any([signal, AbortSignal.timeout(15000)].filter(Boolean)),
  });
  if (response.status === 401) throw new Error('Sign in again to control detection.');
  if (response.status === 403) throw new Error('An active staff account is required.');
  if (!response.ok) {
    throw new Error('Source control unavailable. Run python -m backend.dashboard on this computer.');
  }
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Source control unavailable. Run python -m backend.dashboard on this computer.');
  }
  const data = await response.json();
  if (!Number.isInteger(data.generation) || data.generation < 0
      || !['idle', 'starting', 'switching', 'running', 'ended', 'error'].includes(data.state)
      || ![null, 'live', 'video'].includes(data.mode)) {
    throw new Error('Unexpected video source status. Restart the Python backend.');
  }
  return data;
}

export const getVideoSource = (user, signal) => sourceRequest(user, 'GET', undefined, signal);
export const stopVideoSource = (user, signal) => sourceRequest(user, 'DELETE', undefined, signal);
export function selectVideoSource(user, mode, signal) {
  if (!['live', 'video'].includes(mode)) return Promise.reject(new Error('Unsupported video source.'));
  return sourceRequest(user, 'POST', mode, signal);
}
