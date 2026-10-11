"""Headless browser-frame adapter for the existing detector; no camera is opened."""
from datetime import datetime, timezone
from threading import Lock
from types import SimpleNamespace
import time
from dataclasses import dataclass

from .detection.detection import Program
from .event_types import EventType, AlertLevel
from .detector_settings import DetectorSettingsService
from .recordings import IncidentRecorder
from .recording_privacy import redact_recording_frame


@dataclass(frozen=True)
class PreparedIncident:
    ref: object
    timestamp: datetime
    recording: bool


INCIDENT_TYPES = {
    EventType.FALL: "fall",
    EventType.SITTING_DISTRESS: "prolonged_sitting",
    EventType.ISOLATION_DISTRESS: "isolation",
    EventType.WANDERING_DISTRESS: "wandering",
}


class BrowserIncidentWriter:
    stores_images = False

    def __init__(self, db, session_id, clip_store=None):
        self.db = db
        self.session_id = session_id
        self.clip_store = clip_store

    def prepare(self, event, recorder, stamp):
        ref = self.db.collection('incidents').document()
        recording = recorder is not None and event.alert_level == AlertLevel.RED
        if recording:
            recorder.trigger(ref.id, stamp)
        return PreparedIncident(ref, datetime.now(timezone.utc), recording)

    def create_event(self, person_id, event_type, alert_level, frame=None):
        # `frame` is prepared incident context, never a raw image in this adapter.
        kind = INCIDENT_TYPES[EventType(event_type)]
        level = AlertLevel(alert_level)
        prepared = frame if isinstance(frame, PreparedIncident) else None
        now = prepared.timestamp if prepared else datetime.now(timezone.utc)
        ref = prepared.ref if prepared else self.db.collection("incidents").document()
        ref.set({"type": kind, "status": "active", "outcome": "unconfirmed",
                 "zoneId": "A", "personId": f"{self.session_id}:{person_id}",
                 "createdAt": now, "updatedAt": now, "source": "browser-camera",
                 "sessionId": self.session_id, "recordingAvailable": False,
                 "alert_level": level.value,
                 "severity": "high" if level == AlertLevel.RED else "medium"}, timeout=5)
        if prepared and prepared.recording:
            def sync_recording(state):
                ref.update({'recordingAvailable': state['status'] == 'ready',
                            'recordingStatus': state['status'], 'recordingStorage': 'local',
                            'recordingRedacted': state.get('redacted', False)}, timeout=5)
            self.clip_store.when_finished(ref.id, sync_recording)
        return SimpleNamespace(id=ref.id, event_type=EventType(event_type), alert_level=level)


class BrowserDetector(Program):
    def __init__(self, session_id, db=None, settings_service=None, clip_store=None):
        if db is None:
            from .firebase_config import production_db
            db = production_db
        self.recorder = IncidentRecorder(clip_store, redact_recording_frame) if clip_store else None
        super().__init__(Lock(), events=BrowserIncidentWriter(db, session_id, clip_store),
                         settings_service=settings_service if settings_service is not None else DetectorSettingsService(db))
        self.fps = 0
        self.previous_time = None

    def infer(self, frame):
        now = time.monotonic()
        self.fps = 1 / max(now - self.previous_time, 0.001) if self.previous_time else 0
        self.previous_time = now
        return self.process_frame(frame, now)

    def observe_recording_frame(self, frame, results, frame_time):
        if getattr(self, 'recorder', None):
            self.recorder.observe(frame, results, frame_time)

    def prepare_event_frame(self, frame, all_kp, boxes, all_conf, index, event, frame_time):
        if getattr(self, 'recorder', None):
            return self.events.prepare(event, self.recorder, frame_time)
        return None

    def close(self):
        try:
            super().close()
        finally:
            if getattr(self, 'recorder', None):
                self.recorder.close()

    def get_cam(self):
        raise RuntimeError("Browser detection accepts uploaded frames, not local camera access.")

    def get_fps(self):
        return self.fps

    def get_frame_time(self):
        return time.monotonic()

    def is_video_mode(self):
        return False
