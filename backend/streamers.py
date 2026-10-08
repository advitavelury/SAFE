from fastapi.responses import StreamingResponse
import cv2
from time import monotonic, sleep
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .detection.detection import Program

class FrameStreamer():
    def __init__(self, program: "Program", frame_lock:Lock):
        self.program = program
        self.frame_lock = frame_lock

    def _start_stream(self, check_access):
        next_check = 0
        while True:
            if monotonic() >= next_check:
                try:
                    check_access()
                except Exception:
                    # Headers have already been sent; end the stream on revocation.
                    return
                next_check = monotonic() + 5
            with self.frame_lock:
                current_frame = self.program.current_annotated_frame
                fps = self.program.fps
            if current_frame is None: 
                sleep(1) # wait for a second.
                continue
            wait_time = min(1 / fps, 1) if (fps is not None and fps > 0) else 0.5
            success, encoded_image = cv2.imencode(".jpg", current_frame)

            if not success:
                sleep(wait_time)
                continue

            img_in_bytes = encoded_image.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + img_in_bytes
                + b"\r\n"
            )
            sleep(wait_time)

    def get_stream(self, check_access):
        return StreamingResponse(self._start_stream(check_access),
                                media_type="multipart/x-mixed-replace;boundary=frame",
                                headers={"Cache-Control": "no-store"},
                                )

