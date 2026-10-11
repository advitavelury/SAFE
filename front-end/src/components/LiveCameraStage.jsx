import { useState } from 'react';
import { mediaServiceEnabled } from '../api/mediaService.js';
import BrowserCameraStage from './BrowserCameraStage.jsx';
import MediaCameraStage from './MediaCameraStage.jsx';

export default function LiveCameraStage({ zoneId, className = '' }) {
  const [source, setSource] = useState('webcam');
  return <div className={className}>
    {mediaServiceEnabled && <div className="camera-source-selector" role="group" aria-label="Camera source">
      <button type="button" aria-pressed={source === 'webcam'} onClick={() => setSource('webcam')}>This device</button>
      <button type="button" aria-pressed={source === 'service'} onClick={() => setSource('service')}>Facility feed</button>
    </div>}
    {source === 'service' && mediaServiceEnabled
      ? <MediaCameraStage zoneId={zoneId} className="aspect-video w-full"/>
      : <BrowserCameraStage key={zoneId}/>}
  </div>;
}
