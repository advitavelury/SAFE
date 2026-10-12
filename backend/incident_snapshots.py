"""Bounded, redacted JPEG snapshots in private Firebase Storage objects."""
import cv2

from .recording_privacy import redact_pose_frame
from .recordings import valid_id

MAX_SNAPSHOT_BYTES = 160_000


def encode_snapshot(frame, boxes, points, confidence):
    def array(value):
        return value.cpu().numpy() if hasattr(value, 'cpu') else value

    safe = redact_pose_frame(frame, array(boxes), array(points), array(confidence))
    height, width = safe.shape[:2]
    scale = min(1, 640 / width, 360 / height)
    if scale < 1:
        safe = cv2.resize(safe, (max(1, round(width * scale)), max(1, round(height * scale))),
                          interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode('.jpg', safe, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok or encoded.nbytes > MAX_SNAPSHOT_BYTES:
        raise ValueError('Snapshot encoding failed or exceeded the size limit.')
    return encoded.tobytes()


class IncidentSnapshotStore:
    def __init__(self, bucket):
        self.bucket = bucket

    def upload(self, incident_id, jpeg):
        if not valid_id(incident_id) or not isinstance(jpeg, bytes) or not 0 < len(jpeg) <= MAX_SNAPSHOT_BYTES:
            raise ValueError('Invalid snapshot.')
        path = f'incident-snapshots/{incident_id}.jpg'
        blob = self.bucket.blob(path)
        blob.cache_control = 'private, no-store'
        blob.metadata = {'incidentId': incident_id, 'redacted': 'true'}
        # No public ACL, signed URL or Firebase download token. Do not overwrite an existing snapshot.
        blob.upload_from_string(jpeg, content_type='image/jpeg', if_generation_match=0,
                                timeout=10, retry=None)
        return {'status': 'ready', 'path': path, 'bucket': self.bucket.name,
                'redacted': True, 'contentType': 'image/jpeg', 'bytes': len(jpeg)}
