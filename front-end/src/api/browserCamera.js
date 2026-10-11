export const INITIAL_CAMERA_STATE = {
  status: 'idle', stream: null, devices: [], deviceId: '', message: 'Camera is off.',
};

export function cameraErrorMessage(error) {
  switch (error?.name) {
    case 'NotAllowedError':
    case 'SecurityError': return 'Camera permission was blocked. Allow camera access in your browser and try again.';
    case 'NotFoundError': return 'No camera was found. Connect a webcam and try again.';
    case 'NotReadableError':
    case 'AbortError': return 'The camera could not start. Close other apps using it and try again.';
    case 'OverconstrainedError': return 'The selected camera is unavailable. Select another camera and try again.';
    default: return 'Unable to start the camera. Check browser and device permissions, then try again.';
  }
}

export function createBrowserCamera({ mediaDevices, secureContext, onChange }) {
  let state = { ...INITIAL_CAMERA_STATE };
  let generation = 0;
  let disposed = false;
  let activeStream = null;
  let removeEndedListener;
  const emit = patch => {
    state = { ...state, ...patch };
    if (!disposed) onChange(state);
  };
  const release = () => {
    removeEndedListener?.();
    removeEndedListener = undefined;
    activeStream?.getTracks().forEach(track => track.stop());
    activeStream = null;
  };
  const stop = (message = 'Camera is off.') => {
    generation++;
    release();
    emit({ status: 'idle', stream: null, message });
  };
  const refreshDevices = async () => {
    const current = generation;
    if (!activeStream || disposed || !mediaDevices?.enumerateDevices) return;
    try {
      const devices = await mediaDevices.enumerateDevices();
      if (!disposed && current === generation && activeStream) {
        emit({ devices: devices.filter(device => device.kind === 'videoinput' && device.deviceId) });
      }
    } catch { /* A live preview can continue even if device enumeration is blocked. */ }
  };

  const start = async (deviceId = '') => {
    if (disposed) return;
    const current = ++generation;
    release();
    if (!secureContext || !mediaDevices?.getUserMedia) {
      emit({ status: 'error', stream: null, message: !secureContext
        ? 'Camera access requires HTTPS or localhost.' : 'Camera access is not supported in this browser.' });
      return;
    }
    emit({ status: 'requesting', stream: null, deviceId, message: 'Waiting for camera permission...' });
    try {
      const stream = await mediaDevices.getUserMedia({ audio: false, video: {
        width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 15, max: 24 },
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      } });
      // Permission prompts cannot be cancelled; release late streams after stop or navigation.
      if (disposed || current !== generation) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      activeStream = stream;
      const track = stream.getVideoTracks()[0];
      if (!track || track.readyState === 'ended') throw new Error('Camera ended');
      const ended = () => {
        if (current === generation && !disposed) stop('Camera disconnected. Reconnect it and try again.');
      };
      track.addEventListener('ended', ended);
      removeEndedListener = () => track.removeEventListener('ended', ended);
      emit({ status: 'live', stream, deviceId: track.getSettings?.().deviceId || deviceId,
        message: 'Local preview only. Detection and recording are off.' });
      await refreshDevices();
    } catch (error) {
      if (disposed || current !== generation) return;
      release();
      emit({ status: 'error', stream: null, message: cameraErrorMessage(error) });
    }
  };
  mediaDevices?.addEventListener?.('devicechange', refreshDevices);
  return {
    start, stop,
    dispose() {
      disposed = true;
      generation++;
      release();
      mediaDevices?.removeEventListener?.('devicechange', refreshDevices);
    },
  };
}
