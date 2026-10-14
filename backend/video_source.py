"""Serial lifecycle management around the team's existing detector programs."""
import logging
from pathlib import Path
from threading import Condition, Event, Thread


class VideoSourceController:
    def __init__(self, frame_lock, video_path, factory):
        self.frame_lock = frame_lock
        self.video_path = Path(video_path)
        self._factory = factory
        self._condition = Condition()
        self._generation = 0
        self._mode = None
        self._state = "idle"
        self._message = "Select a source to start detection."
        self._program = None
        self._program_generation = -1
        self._active_stop = None
        self._closed = False
        self._worker = Thread(target=self._run, name="safe-video-source", daemon=True)
        self._worker.start()

    def status(self):
        with self._condition:
            return {"mode": self._mode, "state": self._state,
                    "generation": self._generation, "message": self._message,
                    "videoName": "fall.mp4"}

    def select(self, mode):
        if mode not in ("live", "video", None):
            raise ValueError("Unsupported video source.")
        if mode == "video" and not self.video_path.is_file():
            raise FileNotFoundError("The bundled fall video is missing.")
        with self._condition:
            if self._closed:
                raise RuntimeError("Video source controller is closed.")
            if self._active_stop:
                self._active_stop.set()
            self._generation += 1
            self._mode = mode
            self._state = "switching" if self._program is not None else "starting"
            self._message = "Stopping the previous source..." if self._program is not None else "Starting detection..."
            self._condition.notify_all()
            return self.status()

    def is_current(self, generation):
        with self._condition:
            return (not self._closed and self._generation == generation
                    and self._program_generation == generation and self._state == "running")

    @property
    def current_annotated_frame(self):
        with self._condition:
            if not self.is_current(self._generation):
                return None
            return self._program.current_annotated_frame

    @property
    def fps(self):
        with self._condition:
            return getattr(self._program, "fps", 0) or 15

    def enqueue_event_completion(self, event_id):
        with self._condition:
            if self._program is not None:
                self._program.enqueue_event_completion(event_id)

    def _run(self):
        processed_generation = 0
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._generation != processed_generation)
                if self._closed:
                    return
                generation = processed_generation = self._generation
                mode = self._mode
                if mode is None:
                    self._state, self._message = "idle", "Detection stopped."
                    continue
                stop = self._active_stop = Event()
                self._state, self._message = "starting", "Loading detector..."
            program = None
            ran = False
            try:
                program = self._factory(mode, self.video_path, self.frame_lock)
                if not program.get_cam().isOpened():
                    raise RuntimeError("Video source could not be opened.")
                with self._condition:
                    if self._closed or generation != self._generation:
                        continue
                    self._program = program
                    self._program_generation = generation
                    self._state, self._message = "running", "Waiting for detection frames..."
                ran = True
                program.run(stop, preview_window=False)
                with self._condition:
                    if generation == self._generation and not self._closed:
                        if mode == "video" and program.current_annotated_frame is not None:
                            self._state, self._message = "ended", "Video finished. Replay to run detection again."
                        else:
                            self._state, self._message = "error", "No more frames. Check the camera or video source."
            except Exception:
                logging.getLogger(__name__).exception("Detection source failed")
                with self._condition:
                    if generation == self._generation and not self._closed:
                        self._state = "error"
                        self._message = ("Camera unavailable. Check the backend terminal and camera permissions."
                                         if mode == "live" else "Unable to run the video. Check the backend terminal.")
            finally:
                if program is not None and not ran:
                    program.get_cam().release()
                    program.event_executor.shutdown(wait=True)
                with self._condition:
                    if self._program is program:
                        self._program = None
                    self._active_stop = None

    def close(self):
        with self._condition:
            self._closed = True
            if self._active_stop:
                self._active_stop.set()
            self._condition.notify_all()
        self._worker.join(timeout=10)
