
from fastapi import FastAPI 
from .streamers import FrameStreamer
from .event import event_service

def setup_routes(streamer: FrameStreamer):
    app = FastAPI()

    @app.get("/video_feed")
    def video_feed():
        return streamer.get_stream()

    @app.get("/events")
    def get_events():
        return event_service.get_events()


    @app.get("/events/{event_id}")
    def get_event(event_id: str):
        return event_service.get_event(event_id)


    @app.delete("/events/{event_id}")
    def delete_event(event_id: str):
        event_service.delete_event(event_id)
        return {"message": "Event deleted"}

    return app