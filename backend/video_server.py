"""Local authenticated camera frames for the SAFE React dashboard."""
import argparse
import atexit
import os
from pathlib import Path
import sys
import threading
import time

from flask import Flask, Response, jsonify, request, send_file
from firebase_admin import auth

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detection.firebase_events import get_firestore_client, load_backend_env
from incident_clips import IncidentClips, valid_incident_id


class CameraFeed:
    def __init__(self, source=0, zone_id="A", clips=None):
        self.source = source
        self.zone_id = zone_id
        self.clips = clips
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.jpeg = None
        self.frame_time = 0
        self.last_viewed = 0
        self.state = "idle"
        self.message = "Camera is off."

    def status(self):
        with self.lock:
            return {"state": self.state, "message": self.message,
                    "zoneId": self.zone_id,
                    "source": "camera" if isinstance(self.source, int) else "video"}

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.jpeg = None
            self.state, self.message = "starting", "Starting camera..."
            self.last_viewed = time.monotonic()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.jpeg = None
            self.state, self.message = "idle", "Camera is off."

    def frame(self):
        with self.lock:
            self.last_viewed = time.monotonic()
            if self.state != "running" or time.monotonic() - self.frame_time > 5:
                return None
            return self.jpeg

    def _accept_frame(self, frame):
        import cv2
        if self.stop_event.is_set():
            return
        if time.monotonic() - self.last_viewed > 20:
            self.stop()
            return
        if frame.shape[1] > 960:
            height = round(frame.shape[0] * 960 / frame.shape[1])
            frame = cv2.resize(frame, (960, height))
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            jpeg = encoded.tobytes()
            if self.clips:
                self.clips.push(jpeg)
            with self.lock:
                if not self.stop_event.is_set():
                    self.jpeg = jpeg
                    self.frame_time = time.monotonic()
                    self.state, self.message = "running", "Camera connected."

    def _run(self):
        detector = None
        try:
            from detection.detection import CameraMode, VideoMode
            frame_lock = threading.Lock()
            detector = (CameraMode(frame_lock=frame_lock, camera_index=self.source)
                        if isinstance(self.source, int)
                        else VideoMode(frame_lock=frame_lock, filepath=str(self.source)))
            if not detector.get_cam().isOpened():
                raise RuntimeError("Camera could not be opened. Check camera permissions or the selected video source.")
            if self.clips:
                detector.event_publisher.on_incident = self.clips.trigger
            detector.run(frame_callback=self._accept_frame, stop_event=self.stop_event, display=False)
            with self.lock:
                if not self.stop_event.is_set():
                    self.state = "ended" if not isinstance(self.source, int) else "error"
                    self.message = "Video ended." if self.state == "ended" else "Camera disconnected."
                    self.jpeg = None
        except Exception:
            # Keep paths, credentials and transport details out of browser errors.
            with self.lock:
                if not self.stop_event.is_set():
                    self.state, self.message = "error", "Camera processing failed. Check the backend terminal and camera permissions."
                    self.jpeg = None
            import traceback
            traceback.print_exc()
        finally:
            if detector is not None:
                detector.get_cam().release()
            if self.clips:
                self.clips.finish_session()


class StaffAuthorizer:
    def __init__(self):
        self.profiles = {}
        self.lock = threading.Lock()

    def __call__(self, token):
        db = get_firestore_client()
        if db is None:
            raise RuntimeError("Firebase unavailable")
        claims = auth.verify_id_token(token)
        if claims.get("firebase", {}).get("sign_in_provider") == "anonymous":
            return False
        uid = claims["uid"]
        with self.lock:
            cached = self.profiles.get(uid)
        if cached is None or cached[0] < time.monotonic():
            snapshot = db.collection("users").document(uid).get(timeout=5)
            profile = snapshot.to_dict() if snapshot.exists else {}
            allowed = profile.get("role") if profile.get("active") is True and profile.get("role") in ("admin", "operator") else False
            with self.lock:
                # Re-check staff approval at least every ten seconds.
                self.profiles = {k: v for k, v in self.profiles.items() if v[0] > time.monotonic()}
                self.profiles[uid] = (time.monotonic() + 10, allowed)
            return allowed
        return cached[1]


def create_app(camera, authorize=None, clips=None):
    app = Flask(__name__)
    authorize = authorize or StaffAuthorizer()

    @app.before_request
    def require_staff():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or not header[7:].strip():
            return jsonify(error="Staff sign-in required."), 401
        try:
            role = authorize(header[7:])
            if not role:
                return jsonify(error="Staff access not approved."), 403
            if request.method != "GET" and role != "admin":
                return jsonify(error="Administrator access required."), 403
        except (auth.InvalidIdTokenError, ValueError):
            return jsonify(error="Sign in again to access the camera."), 401
        except Exception:
            return jsonify(error="Unable to verify camera access."), 503

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/camera/status")
    def status():
        return jsonify(camera.status())

    @app.post("/api/camera/start")
    def start():
        camera.start()
        return jsonify(camera.status())

    @app.post("/api/camera/stop")
    def stop():
        camera.stop()
        return jsonify(camera.status())

    @app.get("/api/camera/frame")
    def frame():
        jpeg = camera.frame()
        if jpeg is None:
            return jsonify(camera.status()), 503
        return Response(jpeg, mimetype="image/jpeg")

    @app.get("/api/incidents/<incident_id>/clip")
    def clip_status(incident_id):
        if not valid_incident_id(incident_id):
            return jsonify(error="Invalid incident ID."), 400
        if clips is None:
            return jsonify(status="unavailable", message="Recording is not enabled on this server.")
        return jsonify(clips.status(incident_id))

    @app.get("/api/incidents/<incident_id>/clip/file")
    def clip_file(incident_id):
        if not valid_incident_id(incident_id):
            return jsonify(error="Invalid incident ID."), 400
        path = clips.clip_path(incident_id) if clips else None
        if path is None:
            return jsonify(error="Recording is not available."), 404
        return send_file(path, mimetype="video/mp4", conditional=True, etag=False)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--camera", type=int, default=0)
    source.add_argument("--video", type=Path)
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    if args.video and not args.video.is_file():
        parser.error("Video file does not exist.")
    load_backend_env()
    clips = IncidentClips(Path(__file__).resolve().parent / "recordings")
    camera = CameraFeed(source=args.video or args.camera, zone_id=os.getenv("SAFE_ZONE_ID", "A"), clips=clips)
    atexit.register(clips.close)
    atexit.register(camera.stop)
    create_app(camera, clips=clips).run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
