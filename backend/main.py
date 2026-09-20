from pathlib import Path
import os
from os.path import join 
from threading import Thread, Lock, Event
import uvicorn

from detection.detection import VideoMode
from detection.detection import CameraMode
from streamers import FrameStreamer
from routes import setup_routes


# This code only runs if you execute the file directly
if __name__ == "__main__": 
    video_mode = False
    frame_lock = Lock()
    stop_event = Event()
    if video_mode:
        script_dir = Path(__file__).parent
        video_footage_path = join(script_dir, "..", "..", "my test footage", "Sitting straight.mp4")
        #video_footage_path = join(script_dir, "detection", "distress detection", "sitting testing footage", "Test_4.avi")  # Replace the last argument in the join method with a different file name to test a different video.
        if not os.path.isfile(video_footage_path):
            raise Exception(f"Testing video footage file path {video_footage_path} is incorrect.")
        detector = VideoMode(frame_lock=frame_lock, filepath=video_footage_path)
    else:
        detector = CameraMode(frame_lock=frame_lock)

    detection_thread = Thread(
        target=detector.run,
        args=(stop_event,), 
        daemon=True 
    )
    detection_thread.start()

    streamer = FrameStreamer(program=detector, frame_lock=frame_lock)

    app = setup_routes(streamer=streamer)
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        stop_event.set()
        detection_thread.join()
