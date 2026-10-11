"""Single-session, authenticated webcam ingestion for the laptop demo."""
import io
import os
import time
import uuid
from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from PIL.JpegImagePlugin import JpegImageFile
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, StrictBool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from .staff_auth import StaffAuthorizer
from .frame_authorizer import FrameAuthorizer
from .detector_settings import (DetectorSettingsService, DetectorSettings,
                               DetectorSettingsPatch, SettingsUnavailable)
from .recordings import ClipStore, valid_id

MAX_FRAME_BYTES = 500_000
SESSION_IDLE_SECONDS = 15
PRODUCTION_ORIGIN = "https://safe-dashboard-avelury04-4128.vercel.app"


class StartSession(BaseModel):
    recordRedEvents: StrictBool = False


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
    def __init__(self, factory, clock=time.monotonic, recording_factory=None):
        self.factory = factory
        self.clock = clock
        self.lock = Lock()
        self.session = None
        self.recording_factory = recording_factory

    def expire(self):
        with self.lock:
            self._expire()

    def _expire(self):
        if self.session and self.clock() - self.session["seen"] > SESSION_IDLE_SECONDS:
            self._close()

    def _close(self):
        session, self.session = self.session, None
        if session:
            session['detector'].close()

    def close(self):
        with self.lock:
            self._close()

    def start(self, uid, record=False):
        with self.lock:
            self._expire()
            if self.session:
                raise HTTPException(409, "The demo detector is already in use. Stop the other session or wait for it to expire.")
            session_id = uuid.uuid4().hex
            if record and self.recording_factory is None:
                raise HTTPException(409, "Recording is not enabled on this laptop.")
            detector = (self.recording_factory if record else self.factory)(session_id)
            self.session = {"id": session_id, "uid": uid, "detector": detector, "seen": self.clock()}
            return {"id": session_id, "idleTimeoutSeconds": SESSION_IDLE_SECONDS, "recording": record}

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
            self._close()


def create_app(*, authorizer=None, detector_factory=None, origins=None, clock=time.monotonic,
               settings_service=None, clip_store=None, recording_factory=None):
    authorizer = authorizer or StaffAuthorizer()
    frame_authorizer = FrameAuthorizer(authorizer, clock=clock)
    settings_service = settings_service if settings_service is not None else DetectorSettingsService()
    if clip_store is None and os.environ.get('SAFE_RECORDINGS_ENABLED') == 'true':
        clip_store = ClipStore(os.environ.get('SAFE_RECORDINGS_DIR',
                              str(Path(__file__).resolve().parent / 'recordings')))
    if detector_factory is None:
        from .browser_detection import BrowserDetector
        detector_factory = lambda session_id: BrowserDetector(session_id, settings_service=settings_service)
        if clip_store is not None:
            recording_factory = lambda session_id: BrowserDetector(session_id,
                settings_service=settings_service, clip_store=clip_store)
    sessions = BrowserSessions(detector_factory, clock, recording_factory)
    allowed = origins if origins is not None else [value.strip() for value in
        os.environ.get("SAFE_WEB_ORIGINS", PRODUCTION_ORIGIN).split(",") if value.strip()]
    if not allowed or "*" in allowed:
        raise ValueError("SAFE_WEB_ORIGINS must list the explicit approved frontend origins.")
    @asynccontextmanager
    async def lifespan(app):
        async def expire_idle():
            ticks = 0
            while True:
                await asyncio.sleep(2)
                try:
                    await run_in_threadpool(sessions.expire)
                    ticks += 1
                    if clip_store is not None and ticks % 30 == 0:
                        await run_in_threadpool(clip_store.prune)
                except Exception:
                    # A failed save must not leave idle capture state alive.
                    logging.getLogger(__name__).warning('Idle recording session closed with a save failure.')
        expiry = asyncio.create_task(expire_idle())
        try:
            yield
        finally:
            expiry.cancel()
            try:
                await expiry
            except asyncio.CancelledError:
                pass
            try:
                await run_in_threadpool(sessions.close)
            finally:
                if clip_store is not None:
                    await run_in_threadpool(clip_store.close)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=["GET", "PATCH", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials, verifier):
        if credentials is None:
            raise HTTPException(401, "Staff sign-in required.")
        staff = verifier.verify(credentials.credentials)
        if staff.role not in ("admin", "operator"):
            raise HTTPException(403, "Approved staff access is required.")
        return staff

    def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        staff = authorize(credentials, authorizer)
        if staff.role != "admin":
            raise HTTPException(403, "Administrator access is required.")
        return staff

    def require_frame_staff(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        return authorize(credentials, frame_authorizer)

    def require_staff(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        return authorize(credentials, authorizer)

    def checked_clip_id(incident_id):
        if not valid_id(incident_id):
            raise HTTPException(400, 'Invalid incident ID.')

    @app.get('/api/incidents/{incident_id}/clip')
    def clip_info(incident_id: str, staff=Depends(require_admin)):
        checked_clip_id(incident_id)
        if clip_store is None:
            return {'status': 'unavailable', 'message': 'Local recording is not enabled on this laptop.'}
        try:
            return clip_store.info(incident_id)
        except (OSError, ValueError):
            raise HTTPException(404, 'Recording unavailable.') from None

    @app.get('/api/incidents/{incident_id}/clip/file')
    def clip_file(incident_id: str, staff=Depends(require_admin)):
        checked_clip_id(incident_id)
        try:
            path = clip_store.file(incident_id) if clip_store else None
        except (OSError, ValueError):
            path = None
        if path is None:
            raise HTTPException(404, 'Recording unavailable.')
        return FileResponse(path, media_type='video/mp4', filename=f'{incident_id}.mp4',
                            content_disposition_type='inline')

    @app.get("/admin/detector-settings", response_model=DetectorSettings)
    def get_settings(staff=Depends(require_admin)):
        try:
            return settings_service.get()
        except SettingsUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.patch("/admin/detector-settings", response_model=DetectorSettings)
    def update_settings(body: DetectorSettingsPatch, staff=Depends(require_admin)):
        try:
            return settings_service.update(body, updated_by=staff.uid)
        except SettingsUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post("/api/browser-camera/sessions")
    def start(body: StartSession | None = None, staff=Depends(require_staff)):
        try:
            return sessions.start(staff.uid, body.recordRedEvents if body else False)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Detector could not start. Check the laptop's model and Firebase configuration.") from None

    @app.post("/api/browser-camera/sessions/{session_id}/frames")
    async def frame(session_id: str, request: Request, staff=Depends(require_frame_staff)):
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
    def stop(session_id: str, staff=Depends(require_staff)):
        try:
            sessions.stop(staff.uid, session_id)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Incident saving failed while stopping detection.") from None
        return Response(status_code=204)

    return app
