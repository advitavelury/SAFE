from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .event_types import Event
from .staff_auth import StaffAuthorizer
from .detector_settings import (
    DetectorSettings, DetectorSettingsPatch, SettingsUnavailable,
)


class CompleteEventRequest(BaseModel):
    # Accepted for older clients, but never trusted as the acting staff member.
    completed_by: str | None = Field(default=None, min_length=1)


def setup_routes(streamer, program, *, authorizer=None, events=None, settings=None):
    authorizer = authorizer or StaffAuthorizer()
    if events is None:
        from .event import event_service
        events = event_service
    bearer = HTTPBearer(auto_error=False)

    def require_staff(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if credentials is None:
            raise HTTPException(401, "Staff sign-in required.",
                                headers={"WWW-Authenticate": "Bearer"})
        return authorizer.verify(credentials.credentials)

    def require_admin(staff=Depends(require_staff)):
        if staff.role != "admin":
            raise HTTPException(403, "Administrator access required.")
        return staff

    app = FastAPI(dependencies=[Depends(require_staff)])

    def detector_settings_service():
        # The API and detectors must use the same service instance.
        return settings if settings is not None else program.settings_service

    @app.get("/admin/detector-settings", response_model=DetectorSettings)
    def get_detector_settings(staff=Depends(require_admin)):
        try:
            return detector_settings_service().get()
        except SettingsUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.patch("/admin/detector-settings", response_model=DetectorSettings)
    def update_detector_settings(body: DetectorSettingsPatch, staff=Depends(require_admin)):
        try:
            return detector_settings_service().update(body, updated_by=staff.uid)
        except SettingsUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.exception_handler(HTTPException)
    async def api_error(request, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code,
                            headers=exc.headers)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/auth/me")
    def current_staff(staff=Depends(require_staff)):
        return {"uid": staff.uid, "role": staff.role}

    @app.get("/video_feed")
    def video_feed(staff=Depends(require_staff)):
        return streamer.get_stream(check_access=lambda: authorizer.verify(staff.token))

    @app.get("/events", response_model=list[Event])
    def get_events():
        return events.get_events()

    @app.post("/events/{event_id}/complete")
    def complete_event(event_id: str, body: CompleteEventRequest | None = None,
                       staff=Depends(require_admin)):
        event = events.complete_event(event_id=event_id, completed_by=staff.uid)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        program.enqueue_event_completion(event_id)
        return event

    @app.get("/events/{event_id}", response_model=Event)
    def get_event(event_id: str):
        event = events.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.delete("/events/{event_id}")
    def delete_event(event_id: str, staff=Depends(require_admin)):
        deleted = events.delete_event(event_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Event not found")
        program.enqueue_event_completion(event_id)
        return {"message": "Event deleted"}

    return app
