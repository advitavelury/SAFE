from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient
from firebase_admin import auth
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.routes import setup_routes
from backend.staff_auth import StaffAuthorizer
from backend.streamers import FrameStreamer


class StaffAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.snapshot = self.db.collection.return_value.document.return_value.get.return_value
        self.snapshot.exists = True
        self.snapshot.to_dict.return_value = {"active": True, "role": "operator"}
        self.verify = Mock(return_value={"uid": "staff-uid", "firebase": {"sign_in_provider": "password"}})
        self.authorizer = StaffAuthorizer(self.db, self.verify)

    def test_verified_token_and_server_profile_supply_identity(self):
        staff = self.authorizer.verify("private-token")
        self.assertEqual((staff.uid, staff.role), ("staff-uid", "operator"))
        self.verify.assert_called_once_with("private-token", check_revoked=True)
        self.db.collection.assert_called_once_with("users")
        self.db.collection.return_value.document.assert_called_once_with("staff-uid")
        self.db.collection.return_value.document.return_value.get.assert_called_once_with(timeout=5)
        self.assertNotIn("private-token", repr(staff))

    def test_unapproved_missing_disabled_and_unsupported_profiles_denied(self):
        for profile in [{}, {"active": False, "role": "admin"}, {"active": "true", "role": "admin"},
                        {"active": True, "role": "staff"}, {"active": True, "role": "owner"}]:
            self.snapshot.to_dict.return_value = profile
            with self.subTest(profile=profile), self.assertRaises(HTTPException) as error:
                self.authorizer.verify("token")
            self.assertEqual(error.exception.status_code, 403)
        self.snapshot.exists = False
        with self.assertRaises(HTTPException) as error:
            self.authorizer.verify("token")
        self.assertEqual(error.exception.status_code, 403)

    def test_anonymous_account_cannot_use_an_approved_profile(self):
        self.verify.return_value["firebase"]["sign_in_provider"] = "anonymous"
        with self.assertRaises(HTTPException) as error:
            self.authorizer.verify("token")
        self.assertEqual(error.exception.status_code, 403)
        self.db.collection.assert_not_called()

    def test_invalid_expired_revoked_and_disabled_tokens_are_401(self):
        failures = [ValueError("invalid"), auth.InvalidIdTokenError("invalid"),
                    auth.ExpiredIdTokenError("expired", None), auth.RevokedIdTokenError("revoked"),
                    auth.UserDisabledError("disabled")]
        for failure in failures:
            self.verify.side_effect = failure
            with self.subTest(failure=type(failure).__name__), self.assertRaises(HTTPException) as error:
                self.authorizer.verify("token")
            self.assertEqual(error.exception.status_code, 401)
        self.db.collection.assert_not_called()

    def test_token_or_profile_service_failure_is_503(self):
        self.verify.side_effect = RuntimeError("private credential path")
        with self.assertRaises(HTTPException) as error:
            self.authorizer.verify("token")
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("private", error.exception.detail)
        self.verify.side_effect = None
        self.db.collection.return_value.document.return_value.get.side_effect = RuntimeError("offline")
        with self.assertRaises(HTTPException) as error:
            self.authorizer.verify("token")
        self.assertEqual(error.exception.status_code, 503)

    def test_role_demotion_and_deactivation_take_effect_next_request(self):
        self.snapshot.to_dict.return_value = {"active": True, "role": "admin"}
        self.assertEqual(self.authorizer.verify("token").role, "admin")
        self.snapshot.to_dict.return_value = {"active": True, "role": "operator"}
        self.assertEqual(self.authorizer.verify("token").role, "operator")
        self.snapshot.to_dict.return_value = {"active": False, "role": "operator"}
        with self.assertRaises(HTTPException) as error:
            self.authorizer.verify("token")
        self.assertEqual(error.exception.status_code, 403)


class RouteAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"active": True, "role": "operator"}
        db = Mock()
        db.collection.return_value.document.return_value.get.return_value.to_dict.side_effect = lambda: self.profile
        self.authorizer = StaffAuthorizer(db, Mock(return_value={"uid": "real-admin", "firebase": {"sign_in_provider": "password"}}))
        self.events = Mock()
        self.event = {"id": "event-1", "person_id": 1, "event_type": "fall",
                      "timestamp": datetime.now(timezone.utc), "image_path": "events/event-1.jpeg"}
        self.events.get_event.return_value = self.event
        self.events.get_events.return_value = [self.event]
        self.events.complete_event.return_value = self.event
        self.events.delete_event.return_value = True
        self.program = Mock()
        self.streamer = Mock()
        self.streamer.get_stream.return_value = Response(b"jpeg", media_type="image/jpeg")
        self.client = TestClient(setup_routes(self.streamer, self.program, events=self.events, authorizer=self.authorizer))
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer test-token"}

    def test_all_data_routes_require_bearer_token(self):
        for method, url in [("GET", "/auth/me"), ("GET", "/events"), ("GET", "/events/event-1"),
                            ("GET", "/video_feed"), ("POST", "/events/event-1/complete"), ("DELETE", "/events/event-1")]:
            with self.subTest(url=url, method=method):
                response = self.client.request(method, url)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.events.get_events.assert_not_called()
        self.events.complete_event.assert_not_called()
        self.events.delete_event.assert_not_called()
        self.streamer.get_stream.assert_not_called()

    def test_query_tokens_and_basic_auth_are_not_accepted(self):
        self.assertEqual(self.client.get("/video_feed?token=test-token").status_code, 401)
        self.assertEqual(self.client.get("/events", headers={"Authorization": "Basic abc"}).status_code, 401)

    def test_operator_can_read_all_routes_but_cannot_complete_or_delete(self):
        for url in ["/auth/me", "/events", "/events/event-1", "/video_feed"]:
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, 200)
        for method, url in [("POST", "/events/event-1/complete"), ("DELETE", "/events/event-1")]:
            self.assertEqual(self.client.request(method, url, headers=self.headers).status_code, 403)
        self.events.complete_event.assert_not_called()
        self.events.delete_event.assert_not_called()
        self.program.enqueue_event_completion.assert_not_called()

    def test_admin_completion_uses_token_uid_not_forged_body(self):
        self.profile["role"] = "admin"
        response = self.client.post("/events/event-1/complete", headers=self.headers,
                                    json={"completed_by": "someone-else"})
        self.assertEqual(response.status_code, 200)
        self.events.complete_event.assert_called_once_with(event_id="event-1", completed_by="real-admin")
        self.program.enqueue_event_completion.assert_called_once_with("event-1")

    def test_completion_body_is_optional_and_admin_can_delete(self):
        self.profile["role"] = "admin"
        self.assertEqual(self.client.post("/events/event-1/complete", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.delete("/events/event-1", headers=self.headers).status_code, 200)
        self.events.delete_event.assert_called_once_with("event-1")

    def test_missing_events_return_404_without_notifying_detector(self):
        self.profile["role"] = "admin"
        self.events.get_event.return_value = None
        self.events.complete_event.return_value = None
        self.events.delete_event.return_value = False
        for method, url in [("GET", "/events/event-1"), ("POST", "/events/event-1/complete"), ("DELETE", "/events/event-1")]:
            self.assertEqual(self.client.request(method, url, headers=self.headers).status_code, 404)
        self.program.enqueue_event_completion.assert_not_called()

    def test_active_stream_recheck_uses_same_token_and_current_profile(self):
        self.client.get("/video_feed", headers=self.headers)
        check_access = self.streamer.get_stream.call_args.kwargs["check_access"]
        self.profile["active"] = False
        with self.assertRaises(HTTPException) as error:
            check_access()
        self.assertEqual(error.exception.status_code, 403)


class StreamAccessTests(unittest.TestCase):
    def test_revocation_stops_stream_before_next_frame(self):
        program = Mock(current_annotated_frame=np.zeros((2, 2, 3), dtype=np.uint8), fps=20)
        streamer = FrameStreamer(program, threading.Lock())
        check = Mock(side_effect=[None, HTTPException(403, "Revoked")])
        with patch("backend.streamers.monotonic", side_effect=[0, 0, 6]), patch("backend.streamers.sleep"):
            frames = list(streamer._start_stream(check))
        self.assertEqual(len(frames), 1)
        self.assertIn(b"Content-Type: image/jpeg", frames[0])
        self.assertEqual(check.call_count, 2)

    def test_auth_failure_does_not_encode_any_frames(self):
        streamer = FrameStreamer(Mock(), threading.Lock())
        with patch("backend.streamers.cv2.imencode") as encode:
            self.assertEqual(list(streamer._start_stream(Mock(side_effect=RuntimeError("offline")))), [])
        encode.assert_not_called()
