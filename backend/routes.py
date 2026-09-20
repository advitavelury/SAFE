
from streamers import FrameStreamer
from fastapi import FastAPI 

def setup_routes(streamer: FrameStreamer):
    app = FastAPI()
    
    @app.get("/video_feed")
    def video_feed():
        return streamer.get_stream()

    return app