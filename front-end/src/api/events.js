async function eventRequest(user, eventId, { complete = false, signal } = {}) {
  if (!user || user.isAnonymous) throw new Error('Staff sign-in required.');
  if (typeof eventId !== 'string' || !eventId || eventId.includes('/')) {
    throw new Error('Invalid event ID.');
  }
  const token = await user.getIdToken();
  const response = await fetch(`/api/events/${encodeURIComponent(eventId)}${complete ? '/complete' : ''}`, {
    method: complete ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(15000)].filter(Boolean)),
  });
  if (response.status === 401) throw new Error('Sign in again to access events.');
  if (response.status === 403) throw new Error(complete
    ? 'Administrator access is required to complete events.' : 'Staff access is not approved.');
  if (response.status === 404) throw new Error('This event is no longer available.');
  if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Unable to reach the event service. Check that the Python backend is running.');
  }
  return response.json();
}

export function fetchEvent(user, eventId, signal) {
  return eventRequest(user, eventId, { signal });
}

export function completeEvent(user, eventId, signal) {
  // Identity and permissions are checked by the backend; never submit completed_by.
  return eventRequest(user, eventId, { complete: true, signal });
}
