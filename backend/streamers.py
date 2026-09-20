from detection.detection import Program
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import cv2
from time import sleep
from threading import Lock

class FrameStreamer():
    def __init__(self, program: Program, frame_lock:Lock):
        self.program = program
        self.frame_lock = frame_lock

    def _start_stream(self):

        while True:
            with self.frame_lock:
                current_frame = self.program.current_annotated_frame
                fps = self.program.fps
            if current_frame is None: 
                sleep(1) # wait for a second.
                continue
            wait_time = 1/fps if (fps is not None and fps != 0) else 0.5
            success, encoded_image = cv2.imencode(".jpg", current_frame)

            if not success:
                continue

            img_in_bytes = encoded_image.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + img_in_bytes
                + b"\r\n"
            )
            sleep(wait_time)

    def get_stream(self):
        return StreamingResponse(self._start_stream(),
                                media_type="multipart/x-mixed-replace;boundary=frame",
                                )


