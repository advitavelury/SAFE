
from fastapi import FastAPI, HTTPException 
from pydantic import BaseModel, Field
from .streamers import FrameStreamer
from .event import event_service, Event
from .detection.detection import Program

class CompleteEventRequest(BaseModel):
    completed_by: str = Field(min_length=1)

def setup_routes(streamer: FrameStreamer, program: Program):
    app = FastAPI()

    @app.get("/video_feed")
    def video_feed():
        return streamer.get_stream()

    @app.get("/events", response_model=list[Event])
    def get_events():
        return event_service.get_events()

    @app.post("/events/{event_id}/complete")
    def complete_event(event_id, body: CompleteEventRequest):
        event = event_service.complete_event(
            event_id = event_id,
            completed_by = body.completed_by
        )

        if event is None:
            raise HTTPException(status_code=404, detail = "Event not found")

        program.enqueue_event_completion(event_id)
        return event

    @app.get("/events/{event_id}", response_model=Event)
    def get_event(event_id: str):
        return event_service.get_event(event_id)

    @app.delete("/events/{event_id}")
    def delete_event(event_id: str):
        event_service.delete_event(event_id)
        return {"message": "Event deleted"}

    return app