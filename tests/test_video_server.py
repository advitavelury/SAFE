import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from video_server import CameraFeed, create_app


class FakeCamera:
    def __init__(self):
        self.state = "idle"
        self.starts = 0
        self.jpeg = None

    def status(self):
        return {"state": self.state, "zoneId": "A", "source": "camera"}

    def start(self):
        self.starts += 1
        self.state = "running"

    def stop(self):
        self.state = "idle"
        self.jpeg = None

    def frame(self):
        return self.jpeg


class CameraApiTests(unittest.TestCase):
    def setUp(self):
        self.camera = FakeCamera()
        self.allowed = True
        self.role = "admin"
        self.app = create_app(self.camera, authorize=lambda token: self.role if self.allowed and token == "test-token" else False)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def test_signed_out_requests_cannot_read_or_start_camera(self):
        for method, url in [("get", "status"), ("get", "frame"), ("post", "start"), ("post", "stop")]:
            response = getattr(self.client, method)(f"/api/camera/{url}")
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.camera.starts, 0)

    def test_unapproved_and_revoked_users_are_denied(self):
        self.assertEqual(self.client.get("/api/camera/status", headers=self.headers).status_code, 200)
        self.allowed = False
        self.assertEqual(self.client.get("/api/camera/frame", headers=self.headers).status_code, 403)
        self.assertEqual(self.client.post("/api/camera/start", headers=self.headers).status_code, 403)
        self.assertEqual(self.camera.starts, 0)

    def test_start_stop_and_frame_delivery(self):
        self.client.post("/api/camera/start", headers=self.headers)
        self.camera.jpeg = b"test-jpeg-bytes"
        response = self.client.get("/api/camera/frame", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.data, self.camera.jpeg)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.client.post("/api/camera/stop", headers=self.headers)
        self.assertEqual(self.client.get("/api/camera/frame", headers=self.headers).status_code, 503)

    def test_verification_failure_denies_access(self):
        def unavailable(token):
            raise RuntimeError("offline")
        client = create_app(self.camera, authorize=unavailable).test_client()
        self.assertEqual(client.post("/api/camera/start", headers=self.headers).status_code, 503)
        self.assertEqual(self.camera.starts, 0)

    def test_operator_can_view_but_cannot_start_or_stop_camera(self):
        self.role = "operator"
        self.camera.state = "running"
        self.camera.jpeg = b"test-jpeg"
        self.assertEqual(self.client.get("/api/camera/status", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/camera/frame", headers=self.headers).status_code, 200)
        for action in ("start", "stop"):
            self.assertEqual(self.client.post(f"/api/camera/{action}", headers=self.headers).status_code, 403)
        self.assertEqual(self.camera.starts, 0)
        self.assertEqual(self.camera.state, "running")

    def test_admin_demotion_removes_camera_control(self):
        self.assertEqual(self.client.post("/api/camera/start", headers=self.headers).status_code, 200)
        self.role = "operator"
        self.assertEqual(self.client.post("/api/camera/stop", headers=self.headers).status_code, 403)

    def test_stale_frames_and_stopped_feed_are_not_served(self):
        camera = CameraFeed()
        camera.state = "running"
        camera.jpeg = b"stale"
        camera.frame_time = 0
        self.assertIsNone(camera.frame())
        camera.stop()
        self.assertIsNone(camera.frame())


if __name__ == "__main__":
    unittest.main()
