import { useEffect, useId, useRef, useState } from 'react';
import { Camera, CameraOff, ScanLine, Square } from 'lucide-react';
import { useStaffSession } from '../api/StaffSession.jsx';
import { isApprovedStaff } from '../api/staffAccess.js';
import { createBrowserCamera, INITIAL_CAMERA_STATE } from '../api/browserCamera.js';
import { useBrowserDetection } from '../api/useBrowserDetection.js';
import './browserCamera.css';

export default function BrowserCameraStage() {
  const session = useStaffSession();
  const approved = session?.status === 'ready' && isApprovedStaff(session.user, session.profile);
  const uid = session?.user?.uid;
  const [state, setState] = useState(INITIAL_CAMERA_STATE);
  const controller = useRef(null);
  const video = useRef(null);
  const detection = useBrowserDetection(video, state.stream);
  const selectId = useId();
  const statusId = useId();

  useEffect(() => {
    setState(INITIAL_CAMERA_STATE);
    if (!approved) return;
    const camera = createBrowserCamera({ mediaDevices: navigator.mediaDevices,
      secureContext: window.isSecureContext, onChange: setState });
    controller.current = camera;
    const pause = () => camera.stop('Camera paused.');
    const visibility = () => { if (document.hidden) pause(); };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', pause);
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('pagehide', pause);
      camera.dispose();
      controller.current = null;
    };
  }, [approved, uid]);

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    element.srcObject = state.stream;
    return () => { element.srcObject = null; };
  }, [state.stream]);

  const live = state.status === 'live';
  const pending = state.status === 'requesting';
  return <div className="browser-camera">
    <div className="browser-camera-viewport">
      <video ref={video} autoPlay playsInline muted aria-label="Your webcam preview" hidden={!live}
        onError={() => controller.current?.stop('Video preview stopped. Reconnect your camera.')} />
      {live && detection.image && <img className="browser-camera-overlay" src={detection.image} alt="Latest processed camera frame"/>}
      {!live && <div className="browser-camera-placeholder"><CameraOff size={30}/><span>{pending ? 'Connecting webcam' : 'Webcam preview'}</span></div>}
      <span className="browser-camera-label">{live ? detection.requested && detection.status === 'running' ? 'Detection active' : 'Preview only' : 'Camera off'}</span>
    </div>
    <div className="browser-camera-toolbar">
      <div className="browser-camera-select">
        <label htmlFor={selectId}>Camera</label>
        <select id={selectId} value={state.deviceId} disabled={!approved || pending || !state.devices.length}
          onChange={event => controller.current?.start(event.target.value)}>
          {!state.devices.some(device => device.deviceId === state.deviceId) && <option value={state.deviceId}>Default camera</option>}
          {state.devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}
        </select>
      </div>
      {live || pending
        ? <button type="button" className="browser-camera-stop" onClick={() => controller.current?.stop()} title="Stop webcam" aria-label="Stop webcam"><Square size={18}/></button>
        : <button type="button" className="browser-camera-connect" disabled={!approved} aria-describedby={statusId}
          onClick={() => controller.current?.start(state.deviceId)}><Camera size={18}/>Connect webcam</button>}
    </div>
    <p id={statusId} className="browser-camera-status" role={state.status === 'error' ? 'alert' : 'status'}>
      {approved ? live && detection.requested ? 'Webcam connected.' : state.message : 'An approved staff sign-in is required.'}
    </p>
    <div className="browser-camera-privacy"><span>{detection.requested ? 'Frames sent to demo laptop' : 'On this device only'}</span><span>No video recording</span></div>
    {live && <div className="browser-detection-controls">
      {detection.enabled && detection.canControl ? <>
        <p className="browser-camera-status">{detection.requested ? 'Live frames are being transmitted.' : 'Starting detection sends video frames to the demo laptop and saves incident metadata to Firebase.'}</p>
        <button type="button" onClick={detection.requested ? detection.stop : detection.start}>
          {detection.requested ? <Square size={16}/> : <ScanLine size={16}/>}{detection.requested ? 'Stop detection' : 'Start detection'}
        </button>
      </> : <p className="browser-camera-status">{detection.enabled ? 'Only administrators can start detection.' : 'Laptop detector not connected.'}</p>}
      {detection.message && <p className="browser-camera-status" role={detection.status === 'error' ? 'alert' : 'status'}>{detection.message}</p>}
    </div>}
  </div>;
}
