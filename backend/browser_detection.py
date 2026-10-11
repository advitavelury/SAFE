"""Headless browser-frame adapter for the existing detector; no camera is opened."""
from datetime import datetime, timezone
from threading import Lock
from types import SimpleNamespace
import time

from .detection.detection import Program
from .event_types import EventType, AlertLevel
from .detector_settings import DetectorSettingsService


INCIDENT_TYPES = {
    EventType.FALL: "fall",
    EventType.SITTING_DISTRESS: "prolonged_sitting",
    EventType.ISOLATION_DISTRESS: "isolation",
    EventType.WANDERING_DISTRESS: "wandering",
}


class BrowserIncidentWriter:
    stores_images = False

    def __init__(self, db, session_id):
        self.db = db
        self.session_id = session_id

    def create_event(self, person_id, event_type, alert_level, frame=None):
        # Browser sessions save metadata only, never raw frames or face images.
        kind = INCIDENT_TYPES[EventType(event_type)]
        level = AlertLevel(alert_level)
        now = datetime.now(timezone.utc)
        ref = self.db.collection("incidents").document()
        ref.set({"type": kind, "status": "active", "outcome": "unconfirmed",
                 "zoneId": "A", "personId": f"{self.session_id}:{person_id}",
                 "createdAt": now, "updatedAt": now, "source": "browser-camera",
                 "sessionId": self.session_id, "recordingAvailable": False,
                 "alert_level": level.value,
                 "severity": "high" if level == AlertLevel.RED else "medium"}, timeout=5)
        return SimpleNamespace(id=ref.id, event_type=EventType(event_type), alert_level=level)


class BrowserDetector(Program):
    def __init__(self, session_id, db=None, settings_service=None):
        if db is None:
            from .firebase_config import production_db
            db = production_db
        super().__init__(Lock(), events=BrowserIncidentWriter(db, session_id),
                         settings_service=settings_service if settings_service is not None else DetectorSettingsService(db))
        self.fps = 0
        self.previous_time = None

    def infer(self, frame):
        now = time.monotonic()
        self.fps = 1 / max(now - self.previous_time, 0.001) if self.previous_time else 0
        self.previous_time = now
        return self.process_frame(frame, now)

    def get_cam(self):
        raise RuntimeError("Browser detection accepts uploaded frames, not local camera access.")

    def get_fps(self):
        return self.fps

    def get_frame_time(self):
        return time.monotonic()

    def is_video_mode(self):
        return False
