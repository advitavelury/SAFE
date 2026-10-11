import unittest
from types import SimpleNamespace
from threading import Lock
from unittest.mock import Mock

import cv2
import numpy as np
import torch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.browser_camera_api import create_app, MAX_FRAME_BYTES, SESSION_IDLE_SECONDS
from backend.browser_detection import BrowserIncidentWriter, BrowserDetector
from backend.event_types import EventType


class FakeAuthorizer:
    def verify(self, token):
        if token not in ("admin", "other-admin", "operator"):
            raise HTTPException(401, "Invalid token")
        return SimpleNamespace(uid=token, role="operator" if token == "operator" else "admin")


class BrowserCameraTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.0
        self.detector = Mock()
        self.detector.infer.side_effect = lambda frame: frame
        self.factory = Mock(return_value=self.detector)
        self.origin = "https://example.test"
        self.client = TestClient(create_app(authorizer=FakeAuthorizer(), detector_factory=self.factory,
            origins=[self.origin], clock=lambda: self.now))
        self.image = cv2.imencode(".jpg", np.zeros((240, 320, 3), dtype=np.uint8))[1].tobytes()

    def headers(self, user="admin"):
        return {"Authorization": f"Bearer {user}", "Origin": self.origin, "Content-Type": "image/jpeg"}

    def start(self, user="admin"):
        return self.client.post("/api/browser-camera/sessions", headers=self.headers(user))

    def test_admin_can_create_process_and_stop_session(self):
        session = self.start().json()["id"]
        response = self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["access-control-allow-origin"], self.origin)
        self.detector.infer.assert_called_once()
        self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}", headers=self.headers()).status_code, 204)
        self.assertEqual(self.start().status_code, 200)

    def test_anonymous_unapproved_and_operator_cannot_submit_frames(self):
        session = self.start().json()["id"]
        for headers, status in [({}, 401), (self.headers("invalid"), 401), (self.headers("operator"), 403)]:
            self.assertEqual(self.client.post("/api/browser-camera/sessions", headers=headers).status_code, status)
            self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=headers).status_code, status)
        self.detector.infer.assert_not_called()

    def test_sessions_are_owned_not_shared_between_administrators(self):
        session = self.start().json()["id"]
        self.assertEqual(self.start("other-admin").status_code, 409)
        self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers("other-admin")).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}", headers=self.headers("other-admin")).status_code, 404)

    def test_expired_sessions_do_not_preserve_tracking_state(self):
        session = self.start().json()["id"]
        self.now += SESSION_IDLE_SECONDS + 1
        self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers()).status_code, 404)
        self.assertNotEqual(self.start().json()["id"], session)
        self.assertEqual(self.factory.call_count, 2)

    def test_reject_oversized_invalid_and_wrong_content_type_frames(self):
        session = self.start().json()["id"]
        url = f"/api/browser-camera/sessions/{session}/frames"
        for body, status in [(b"invalid", 400), (b"x" * (MAX_FRAME_BYTES + 1), 413)]:
            self.assertEqual(self.client.post(url, content=body, headers=self.headers()).status_code, status)
        large = cv2.imencode(".jpg", np.zeros((721, 1281, 3), dtype=np.uint8))[1].tobytes()
        self.assertEqual(self.client.post(url, content=large, headers=self.headers()).status_code, 400)
        self.assertEqual(self.client.post(url, content=self.image, headers={**self.headers(), "Content-Type": "text/plain"}).status_code, 415)
        self.detector.infer.assert_not_called()

    def test_failures_are_explicit_without_exception_details(self):
        session = self.start().json()["id"]
        self.detector.infer.side_effect = RuntimeError("private details")
        response = self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private details", response.text)

    def test_cors_preflight_only_allows_configured_frontend(self):
        for origin, status in [(self.origin, 200), ("https://untrusted.test", 400)]:
            response = self.client.options("/api/browser-camera/sessions", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization,Content-Type"})
            self.assertEqual(response.status_code, status)

    def test_incident_writer_maps_detector_events_without_uploading_images(self):
        db = Mock()
        ref = db.collection.return_value.document.return_value
        ref.id = "incident-1"
        writer = BrowserIncidentWriter(db, "session-1")
        for kind, expected in [(EventType.FALL, "fall"), (EventType.SITTING_DISTRESS, "prolonged_sitting"),
                               (EventType.ISOLATION_DISTRESS, "isolation"), (EventType.WANDERING_DISTRESS, "wandering")]:
            result = writer.create_event(2, kind, self.image)
            self.assertEqual(result.id, "incident-1")
            data = ref.set.call_args.args[0]
            self.assertEqual(data["type"], expected)
            self.assertEqual(data["personId"], "session-1:2")
            self.assertEqual(data["status"], "active")
            self.assertIs(data["recordingAvailable"], False)
            self.assertNotIn("frame", data)
            self.assertNotIn("image_path", data)
        db.collection.assert_called_with("incidents")

    def test_shared_frame_pipeline_runs_all_detectors_and_suppresses_duplicate_track_alerts(self):
        detector = BrowserDetector.__new__(BrowserDetector)
        detector.fps = 10
        detector.frame_lock = Lock()
        detector.persons = {}
        detector.outstanding_events = {}
        detector.bytetrack_yaml_path = "fixture.yaml"
        detector.events = Mock()
        detector.events.create_event.return_value.id = "event-1"
        detector.update_person_properties = Mock()
        detectors = [Mock() for _ in range(4)]
        for item in detectors:
            item.check_detector.return_value = None
        detectors[0].check_detector.return_value = EventType.FALL
        detector.fall_detector, detector.wandering_detector, detector.isolation_detector, detector.sitting_detector = detectors
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        result = SimpleNamespace(
            boxes=SimpleNamespace(id=torch.tensor([1]), xyxy=torch.tensor([[0, 0, 100, 200]])),
            keypoints=SimpleNamespace(xy=torch.zeros((1, 17, 2)), conf=torch.ones((1, 17))),
            plot=lambda **kwargs: frame.copy())
        detector.model = Mock()
        detector.model.track.return_value = [result]
        for now in [1.0, 2.0]:
            self.assertEqual(detector.process_frame(frame, now).shape, frame.shape)
        for item in detectors:
            self.assertEqual(item.check_detector.call_count, 2)
            self.assertEqual(item.check_detector.call_args.kwargs["ctx"].frame_time, 2.0)
        detector.events.create_event.assert_called_once()
        self.assertEqual(detector.persons[1].active_event_id, "event-1")


if __name__ == "__main__":
    unittest.main()
