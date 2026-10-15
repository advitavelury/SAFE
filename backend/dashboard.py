"""Run the existing detector with source selection from the local dashboard."""
import os
from pathlib import Path
from threading import Lock

import uvicorn

from .detector_settings import DetectorSettingsService
from .routes import setup_routes
from .streamers import FrameStreamer
from .video_source import VideoSourceController


def main():
    frame_lock = Lock()
    settings = DetectorSettingsService()
    video_path = Path(__file__).parent / "detection" / "fall footage" / "Final_pitch_2.mp4"

    def create_program(mode, path, lock):
        from .detection.detection import CameraMode, VideoMode
        program = (CameraMode(lock, camera_index=int(os.environ.get("SAFE_CAMERA_INDEX", "0")))
                   if mode == "live" else VideoMode(lock, str(path)))
        try:
            # Keep the API's settings service attached to every new source session.
            program.settings_service = settings
            program.apply_settings(settings.get())
            return program
        except Exception:
            program.get_cam().release()
            program.event_executor.shutdown(wait=True)
            raise

    sources = VideoSourceController(frame_lock, video_path, create_program)
    streamer = FrameStreamer(sources, frame_lock)
    app = setup_routes(streamer, sources, settings=settings, source_controller=sources)
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        sources.close()


if __name__ == "__main__":
    main()
