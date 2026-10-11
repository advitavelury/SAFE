import unittest
import time
from types import SimpleNamespace
from threading import Lock
from queue import Queue
from concurrent.futures import Future
from unittest.mock import Mock

import cv2
import numpy as np
import torch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.browser_camera_api import create_app, MAX_FRAME_BYTES, SESSION_IDLE_SECONDS
from backend.browser_detection import BrowserIncidentWriter, BrowserDetector
from backend.event_types import EventType, AlertLevel
from backend.detection.detection_types import DetectionResult


class FakeAuthorizer:
    def verify(self, token):
        if token == "inactive":
            raise HTTPException(403, "Staff access not approved")
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
        self.detector.close.assert_called_once()
        self.assertEqual(self.start().status_code, 200)

    def test_operator_can_create_process_and_stop_own_session(self):
        response = self.start("operator")
        self.assertEqual(response.status_code, 200)
        session = response.json()["id"]
        response = self.client.post(f"/api/browser-camera/sessions/{session}/frames",
            content=self.image, headers=self.headers("operator"))
        self.assertEqual(response.status_code, 200)
        self.detector.infer.assert_called_once()
        self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}",
            headers=self.headers("operator")).status_code, 204)
        self.detector.close.assert_called_once()

    def test_operator_cannot_read_or_change_admin_settings(self):
        path = "/admin/detector-settings"
        self.assertEqual(self.client.get(path, headers=self.headers("operator")).status_code, 403)
        self.assertEqual(self.client.patch(path, json={"sitting_seconds": 15.0},
            headers={"Authorization": "Bearer operator"}).status_code, 403)

    def test_frame_cache_does_not_skip_fresh_start_or_stop_checks(self):
        authorizer = Mock()
        authorizer.verify.return_value = SimpleNamespace(uid="admin", role="admin", expires_at=time.time() + 3600)
        client = TestClient(create_app(authorizer=authorizer, detector_factory=self.factory,
            origins=[self.origin], clock=lambda: self.now))
        session = client.post("/api/browser-camera/sessions", headers=self.headers()).json()["id"]
        url = f"/api/browser-camera/sessions/{session}/frames"
        for _ in range(4):
            self.assertEqual(client.post(url, content=self.image, headers=self.headers()).status_code, 200)
        self.assertEqual(authorizer.verify.call_count, 2)
        self.assertEqual(client.delete(f"/api/browser-camera/sessions/{session}", headers=self.headers()).status_code, 204)
        self.assertEqual(authorizer.verify.call_count, 3)
        self.assertEqual(client.post(url, content=self.image, headers=self.headers()).status_code, 404)

    def test_frame_cache_rechecks_approval_after_one_second(self):
        authorizer = Mock()
        authorizer.verify.return_value = SimpleNamespace(uid="admin", role="admin", expires_at=time.time() + 3600)
        client = TestClient(create_app(authorizer=authorizer, detector_factory=self.factory,
            origins=[self.origin], clock=lambda: self.now))
        session = client.post("/api/browser-camera/sessions", headers=self.headers()).json()["id"]
        url = f"/api/browser-camera/sessions/{session}/frames"
        self.assertEqual(client.post(url, content=self.image, headers=self.headers()).status_code, 200)
        authorizer.verify.side_effect = HTTPException(403, "Staff access not approved")
        self.now += 1.0
        self.assertEqual(client.post(url, content=self.image, headers=self.headers()).status_code, 403)
        self.assertEqual(self.detector.infer.call_count, 1)

    def test_anonymous_and_unapproved_staff_cannot_control_sessions(self):
        session = self.start().json()["id"]
        for headers, status in [({}, 401), (self.headers("invalid"), 401), (self.headers("inactive"), 403)]:
            self.assertEqual(self.client.post("/api/browser-camera/sessions", headers=headers).status_code, status)
            self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=headers).status_code, status)
            self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}", headers=headers).status_code, status)
        self.detector.infer.assert_not_called()

    def test_sessions_are_owned_not_shared_between_staff(self):
        session = self.start().json()["id"]
        for other in ("other-admin", "operator"):
            self.assertEqual(self.start(other).status_code, 409)
            self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers(other)).status_code, 404)
            self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}", headers=self.headers(other)).status_code, 404)

    def test_admin_cannot_take_over_operator_session(self):
        session = self.start("operator").json()["id"]
        self.assertEqual(self.start("admin").status_code, 409)
        self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames",
            content=self.image, headers=self.headers("admin")).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/browser-camera/sessions/{session}",
            headers=self.headers("admin")).status_code, 404)

    def test_expired_sessions_do_not_preserve_tracking_state(self):
        session = self.start().json()["id"]
        self.now += SESSION_IDLE_SECONDS + 1
        self.assertEqual(self.client.post(f"/api/browser-camera/sessions/{session}/frames", content=self.image, headers=self.headers()).status_code, 404)
        self.assertNotEqual(self.start().json()["id"], session)
        self.detector.close.assert_called_once()
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
            result = writer.create_event(2, kind, AlertLevel.RED, self.image)
            self.assertEqual(result.id, "incident-1")
            data = ref.set.call_args.args[0]
            self.assertEqual(data["type"], expected)
            self.assertEqual(data["personId"], "session-1:2")
            self.assertEqual(data["status"], "active")
            self.assertEqual(data["alert_level"], "red")
            self.assertEqual(data["severity"], "high")
            self.assertEqual(result.event_type, kind)
            self.assertIs(data["recordingAvailable"], False)
            self.assertNotIn("frame", data)
            self.assertNotIn("image_path", data)
        db.collection.assert_called_with("incidents")
        writer.create_event(2, EventType.SITTING_DISTRESS, AlertLevel.AMBER)
        self.assertEqual(ref.set.call_args.args[0]['severity'], 'medium')

class SharedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.detector = detector = BrowserDetector.__new__(BrowserDetector)
        detector.fps = 10
        detector.frame_lock = Lock()
        detector.persons = {}
        detector.outstanding_events = {}
        detector.completion_queue = Queue()
        detector.pending_events = {}
        detector.pending_results = {}
        detector.deferred_events = {}
        detector.settings_service = Mock()
        detector.settings_service.take_pending_update.return_value = None
        detector.bytetrack_yaml_path = "fixture.yaml"
        detector.events = Mock(stores_images=False)
        detector.event_executor = Mock()
        self.jobs = []
        def submit(fn, **kwargs):
            future = Future()
            self.jobs.append((future, kwargs))
            return future
        detector.event_executor.submit.side_effect = submit
        detector.update_person_properties = Mock()
        self.detectors = [Mock() for _ in range(4)]
        for item in self.detectors:
            item.check_detector.return_value = None
        detector.fall_detector, detector.wandering_detector, detector.isolation_detector, detector.sitting_detector = self.detectors
        self.frame = np.zeros((240, 320, 3), dtype=np.uint8)
        result = SimpleNamespace(
            boxes=SimpleNamespace(id=torch.tensor([1]), xyxy=torch.tensor([[0, 0, 100, 200]])),
            keypoints=SimpleNamespace(xy=torch.zeros((1, 17, 2)), conf=torch.ones((1, 17))),
            plot=lambda **kwargs: self.frame.copy())
        detector.model = Mock()
        detector.model.track.return_value = [result]

    def tick(self, now=1.0):
        self.assertEqual(self.detector.process_frame(self.frame, now).shape, self.frame.shape)

    def finish(self, index, event_id):
        future, job = self.jobs[index]
        future.set_result(SimpleNamespace(id=event_id, event_type=job['event_type'], alert_level=job['alert_level']))
        self.detector.process_pending_events()

    def test_all_detectors_run_and_pending_and_active_alerts_are_deduplicated(self):
        self.detectors[0].check_detector.return_value = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.tick()
        self.tick(2.0)
        self.assertEqual(len(self.jobs), 1)
        for item in self.detectors:
            self.assertEqual(item.check_detector.call_count, 2)
        self.finish(0, 'fall-1')
        self.tick()
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(self.detector.persons[1].active_event_id['id'], 'fall-1')
        self.assertIsNone(self.jobs[0][1]['frame'])

    def test_amber_to_red_escalation_and_completion_only_clears_matching_event(self):
        self.detectors[3].check_detector.return_value = DetectionResult(EventType.SITTING_DISTRESS, AlertLevel.AMBER)
        self.tick()
        self.finish(0, 'amber-1')
        self.detectors[3].check_detector.return_value = DetectionResult(EventType.SITTING_DISTRESS, AlertLevel.RED)
        self.tick()
        self.finish(1, 'red-1')
        self.detector.enqueue_event_completion('amber-1')
        self.detector.process_event_completions()
        self.assertEqual(self.detector.persons[1].active_event_id['id'], 'red-1')
        self.detector.enqueue_event_completion('red-1')
        self.detector.process_event_completions()
        self.assertIsNone(self.detector.persons[1].active_event_id)

    def test_fall_escalates_after_existing_red_distress(self):
        self.detectors[2].check_detector.return_value = DetectionResult(EventType.ISOLATION_DISTRESS, AlertLevel.RED)
        self.tick()
        self.finish(0, 'isolation-1')
        self.detectors[0].check_detector.return_value = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.tick()
        self.finish(1, 'fall-1')
        self.assertEqual(self.detector.persons[1].active_event_type, EventType.FALL)

    def test_brief_fall_is_retained_while_amber_write_is_pending(self):
        self.detectors[1].check_detector.return_value = DetectionResult(EventType.WANDERING_DISTRESS, AlertLevel.AMBER)
        self.tick()
        self.detectors[0].check_detector.return_value = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.tick()
        self.detectors[0].check_detector.return_value = None
        self.tick()
        self.assertEqual(len(self.jobs), 1)
        self.finish(0, 'amber-1')
        self.assertEqual(len(self.jobs), 2)
        self.assertEqual(self.jobs[1][1]['event_type'], EventType.FALL)
        self.finish(1, 'fall-1')
        self.tick()
        self.assertEqual(len(self.jobs), 2)

    def test_async_write_failure_is_reported(self):
        self.detectors[0].check_detector.return_value = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.tick()
        self.jobs[0][0].set_exception(RuntimeError('private details'))
        with self.assertRaisesRegex(RuntimeError, '^Incident saving failed$'):
            self.tick()

    def test_red_distress_takes_priority_over_amber_movement(self):
        self.detectors[1].check_detector.return_value = DetectionResult(EventType.WANDERING_DISTRESS, AlertLevel.AMBER)
        self.detectors[2].check_detector.return_value = DetectionResult(EventType.ISOLATION_DISTRESS, AlertLevel.RED)
        self.tick()
        self.assertEqual(self.jobs[0][1]['event_type'], EventType.ISOLATION_DISTRESS)

    def test_close_flushes_a_deferred_fall(self):
        self.detectors[1].check_detector.return_value = DetectionResult(EventType.WANDERING_DISTRESS, AlertLevel.AMBER)
        self.tick()
        self.detectors[0].check_detector.return_value = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.tick()
        self.jobs[0][0].set_result(SimpleNamespace(id='amber', event_type=EventType.WANDERING_DISTRESS, alert_level=AlertLevel.AMBER))
        self.detector.close()
        self.detector.event_executor.shutdown.assert_called_once_with(wait=True)
        self.assertEqual(self.detector.events.create_event.call_args.kwargs['event_type'], EventType.FALL)


if __name__ == "__main__":
    unittest.main()
