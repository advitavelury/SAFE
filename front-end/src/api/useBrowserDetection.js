import { useEffect, useRef, useState } from 'react';
import { useStaffSession } from './StaffSession.jsx';
import { canEditIncidents } from './staffAccess.js';
import { mediaOrigin, mediaUrl } from './deploymentConfig.js';
import { frameMetrics, nextFrameDelay } from './frameTiming.js';

const configuredOrigin = import.meta.env.VITE_BROWSER_DETECTOR_ORIGIN;
const origin = configuredOrigin ? mediaOrigin(configuredOrigin, import.meta.env.DEV) : null;
export const browserDetectorEnabled = origin !== null;

async function request(user, path, options = {}) {
  let token;
  try { token = await user.getIdToken(); }
  catch { throw new Error('Sign in again to use detection.'); }
  const response = await fetch(mediaUrl(origin, `/api/browser-camera/${path}`), {
    ...options, redirect: 'error', credentials: 'omit', cache: 'no-store',
    signal: AbortSignal.any([options.signal, AbortSignal.timeout(20000)].filter(Boolean)),
    headers: { Authorization: `Bearer ${token}`, ...options.headers },
  });
  if (!response.ok) {
    const messages = { 401: 'Sign in again to use detection.', 403: 'Administrator access is required.',
      404: 'Detection session expired. Start detection again.',
      409: 'The detector is in use, or recording is not enabled on this laptop.',
      429: 'The laptop detector is busy. Try again.',
      503: 'Detection or saving is unavailable. Check the laptop backend.' };
    throw new Error(messages[response.status] || 'The detector could not process this frame.');
  }
  return response;
}

export function useBrowserDetection(videoRef, stream, recordRedEvents = false) {
  const session = useStaffSession();
  const user = session?.user;
  const canControl = session?.status === 'ready' && canEditIncidents(user, session?.profile);
  const [requested, setRequested] = useState(false);
  const [state, setState] = useState({ status: 'idle', message: '' });
  const [image, setImage] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const imageUrl = useRef(null);

  useEffect(() => {
    if (!stream || !canControl || !browserDetectorEnabled) {
      setRequested(false);
      return;
    }
    if (!requested) return;
    const abort = new AbortController();
    let disposed = false;
    let sessionId;
    let timer;
    let previousMetrics = null;
    let recording = false;
    setMetrics(null);
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    const clearImage = () => {
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
      imageUrl.current = null;
      setImage(null);
    };
    const closeSession = () => {
      if (sessionId) {
        const id = sessionId;
        sessionId = null;
        request(user, `sessions/${id}`, { method: 'DELETE', keepalive: true }).catch(() => {});
      }
    };
    async function frame() {
      if (disposed) return;
      const startedAt = performance.now();
      try {
        const video = videoRef.current;
        if (!video || video.readyState < 2 || !video.videoWidth) {
          timer = setTimeout(frame, 100);
          return;
        }
        const scale = Math.min(640 / video.videoWidth, 480 / video.videoHeight, 1);
        const width = Math.max(1, Math.round(video.videoWidth * scale));
        const height = Math.max(1, Math.round(video.videoHeight * scale));
        if (canvas.width !== width) canvas.width = width;
        if (canvas.height !== height) canvas.height = height;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.75));
        if (disposed) return;
        if (!blob) throw new Error('Unable to read the webcam frame.');
        const response = await request(user, `sessions/${sessionId}/frames`, {
          method: 'POST', body: blob, headers: { 'Content-Type': 'image/jpeg' }, signal: abort.signal,
        });
        if (!response.headers.get('content-type')?.startsWith('image/jpeg')) {
          throw new Error('The detector returned an invalid frame.');
        }
        const result = await response.blob();
        if (disposed) return;
        clearImage();
        imageUrl.current = URL.createObjectURL(result);
        setImage(imageUrl.current);
        previousMetrics = frameMetrics(previousMetrics, performance.now(), startedAt);
        setMetrics(previousMetrics);
        setState({ status: 'running', recording, message: recording
          ? 'Detection active. Red-event clips are redacted and saved on the demo laptop.'
          : 'Detection active. Incident metadata is saved to Firebase. No clips recorded.' });
        // Backpressure: never queue webcam frames while an inference request is running.
        timer = setTimeout(frame, nextFrameDelay(performance.now() - startedAt));
      } catch (error) {
        if (disposed) return;
        clearImage();
        setState({ status: 'error', message: error.name === 'TypeError' || error.name === 'TimeoutError'
          ? 'Laptop detector unreachable. Check the backend and HTTPS connection.' : error.message });
        setRequested(false);
      }
    }
    setState({ status: 'connecting', message: 'Connecting to laptop detector...' });
    request(user, 'sessions', { method: 'POST', signal: abort.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ recordRedEvents }) }).then(r => r.json()).then(data => {
      if (!/^[a-f0-9]{32}$/.test(data.id)) throw new Error('Invalid detector session.');
      sessionId = data.id;
      recording = data.recording === true;
      if (recordRedEvents && !recording) throw new Error('This backend did not enable recording. Update the laptop backend.');
      if (disposed) closeSession();
      else frame();
    }).catch(error => {
      if (disposed) return;
      setState({ status: 'error', message: ['TypeError', 'TimeoutError'].includes(error.name)
        ? 'Laptop detector unreachable. Check the backend and HTTPS connection.' : error.message });
      setRequested(false);
    });
    return () => {
      disposed = true;
      abort.abort();
      clearTimeout(timer);
      clearImage();
      setMetrics(null);
      closeSession();
    };
  }, [requested, stream, canControl, user, videoRef, recordRedEvents]);

  return { ...state, image, metrics, requested, canControl, enabled: browserDetectorEnabled,
    start: () => { if (stream && canControl && browserDetectorEnabled) setRequested(true); },
    stop: () => { setRequested(false); setState({ status: 'idle', message: 'Detection stopped.' }); },
  };
}
