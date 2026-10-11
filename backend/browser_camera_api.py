"""Single-session, authenticated webcam ingestion for the laptop demo."""
import io
import os
import time
import uuid
from threading import Lock

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from PIL.JpegImagePlugin import JpegImageFile
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from .staff_auth import StaffAuthorizer

MAX_FRAME_BYTES = 500_000
SESSION_IDLE_SECONDS = 15
PRODUCTION_ORIGIN = "https://safe-dashboard-avelury04-4128.vercel.app"


def decode_frame(data):
    if not data or len(data) > MAX_FRAME_BYTES:
        raise HTTPException(413, "Frame is empty or too large.")
    try:
        with JpegImageFile(io.BytesIO(data)) as image:
            if image.format != "JPEG" or not (1 <= image.width <= 1280 and 1 <= image.height <= 720):
                raise HTTPException(400, "Send a JPEG no larger than 1280 by 720.")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(400, "Invalid JPEG frame.") from None
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "Invalid JPEG frame.")
    return frame


class BrowserSessions:
    def __init__(self, factory, clock=time.monotonic):
        self.factory = factory
        self.clock = clock
        self.lock = Lock()
        self.session = None

    def _expire(self):
        if self.session and self.clock() - self.session["seen"] > SESSION_IDLE_SECONDS:
            self.session = None

    def start(self, uid):
        with self.lock:
            self._expire()
            if self.session:
                raise HTTPException(409, "The demo detector is already in use. Stop the other session or wait for it to expire.")
            session_id = uuid.uuid4().hex
            detector = self.factory(session_id)
            self.session = {"id": session_id, "uid": uid, "detector": detector, "seen": self.clock()}
            return {"id": session_id, "idleTimeoutSeconds": SESSION_IDLE_SECONDS, "recording": False}

    def _owned(self, uid, session_id):
        self._expire()
        if not self.session or self.session["id"] != session_id or self.session["uid"] != uid:
            raise HTTPException(404, "Camera session expired or unavailable. Restart detection.")
        return self.session

    def process(self, uid, session_id, frame):
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, "Detector is busy. Send one frame at a time.")
        try:
            session = self._owned(uid, session_id)
            result = session["detector"].infer(frame)
            session["seen"] = self.clock()
            ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError("Frame encoding failed")
            return encoded.tobytes()
        finally:
            self.lock.release()

    def stop(self, uid, session_id):
        with self.lock:
            self._owned(uid, session_id)
            self.session = None


def create_app(*, authorizer=None, detector_factory=None, origins=None, clock=time.monotonic):
    authorizer = authorizer or StaffAuthorizer()
    if detector_factory is None:
        from .browser_detection import BrowserDetector
        detector_factory = BrowserDetector
    sessions = BrowserSessions(detector_factory, clock)
    allowed = origins if origins is not None else [value.strip() for value in
        os.environ.get("SAFE_WEB_ORIGINS", PRODUCTION_ORIGIN).split(",") if value.strip()]
    if not allowed or "*" in allowed:
        raise ValueError("SAFE_WEB_ORIGINS must list the explicit approved frontend origins.")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=["POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    bearer = HTTPBearer(auto_error=False)

    def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if credentials is None:
            raise HTTPException(401, "Staff sign-in required.")
        staff = authorizer.verify(credentials.credentials)
        if staff.role != "admin":
            raise HTTPException(403, "Only administrators can start or submit monitoring sessions.")
        return staff

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post("/api/browser-camera/sessions")
    def start(staff=Depends(require_admin)):
        try:
            return sessions.start(staff.uid)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Detector could not start. Check the laptop's model and Firebase configuration.") from None

    @app.post("/api/browser-camera/sessions/{session_id}/frames")
    async def frame(session_id: str, request: Request, staff=Depends(require_admin)):
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(415, "Send image/jpeg frames.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_FRAME_BYTES:
                raise HTTPException(413, "Frame is too large.")
        image = await run_in_threadpool(decode_frame, bytes(body))
        try:
            result = await run_in_threadpool(sessions.process, staff.uid, session_id, image)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Detection or incident saving failed. Check the laptop backend.") from None
        return Response(result, media_type="image/jpeg")

    @app.delete("/api/browser-camera/sessions/{session_id}", status_code=204)
    def stop(session_id: str, staff=Depends(require_admin)):
        sessions.stop(staff.uid, session_id)
        return Response(status_code=204)

    return app
