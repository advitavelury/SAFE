"""Bounded, local-only incident clips from annotated JPEG camera frames."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time


def valid_incident_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value) is not None


def encode_mp4(frames, fps, destination):
    from imageio_ffmpeg import get_ffmpeg_exe
    subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "image2pipe", "-framerate", str(fps), "-vcodec", "mjpeg", "-i", "pipe:0",
         "-an", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
         "-preset", "ultrafast", "-crf", "26", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-fs", "20000000", str(destination)],
        input=b"".join(frames), capture_output=True, check=True, timeout=45,
    )


class IncidentClips:
    def __init__(self, directory, pre_seconds=5, post_seconds=10, fps=5,
                 max_bytes=1_000_000_000, max_pending=4, encoder=encode_mp4):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pre_seconds, self.post_seconds, self.fps = pre_seconds, post_seconds, fps
        self.max_bytes = max_bytes
        self.encoder = encoder
        self.buffer = deque(maxlen=math.ceil(pre_seconds * fps) + 2)
        self.pending = {}
        self.states = {}
        self.last_sample = -math.inf
        self.closed = False
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(max_pending)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="incident-clips")

    def _path(self, incident_id, extension):
        if not valid_incident_id(incident_id):
            raise ValueError("Invalid incident ID")
        return self.directory / (hashlib.sha256(incident_id.encode()).hexdigest() + extension)

    def _save_status(self, incident_id, data):
        path = self._path(incident_id, ".json")
        temporary = self._path(incident_id, ".json.tmp")
        temporary.write_text(json.dumps(data))
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def status(self, incident_id):
        path = self._path(incident_id, ".json")
        with self.lock:
            current = self.states.get(incident_id)
            if current:
                return dict(current)
        try:
            if path.is_symlink():
                raise ValueError("Invalid recording metadata")
            data = json.loads(path.read_text())
            if data.get("status") == "ready":
                clip = self._path(incident_id, ".mp4")
                if clip.is_file() and not clip.is_symlink():
                    return data
            elif data.get("status") == "failed":
                return data
        except (OSError, ValueError):
            pass
        return {"status": "unavailable", "message": "No recording is available on this server for this incident."}

    def clip_path(self, incident_id):
        if self.status(incident_id)["status"] != "ready":
            return None
        return self._path(incident_id, ".mp4")

    def trigger(self, incident_id, event_time=None):
        if not valid_incident_id(incident_id):
            return
        now = time.monotonic() if event_time is None else event_time
        with self.lock:
            if self.closed or incident_id in self.states or self._path(incident_id, ".json").exists():
                return
            if not self.slots.acquire(blocking=False):
                self._save_status(incident_id, {"status": "failed", "message": "Recorder busy; no clip was saved."})
                return
            self.pending[incident_id] = {
                "event": now, "end": now + self.post_seconds,
                "frames": [(t, jpeg) for t, jpeg in self.buffer if t >= now - self.pre_seconds],
            }
            self.states[incident_id] = {"status": "recording", "message": "Recording incident..."}

    def push(self, jpeg, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.closed or now - self.last_sample < 1 / self.fps - 1e-6:
                return
            self.last_sample = now
            self.buffer.append((now, jpeg))
            while self.buffer and self.buffer[0][0] < now - self.pre_seconds:
                self.buffer.popleft()
            for incident_id, clip in list(self.pending.items()):
                if now <= clip["end"]:
                    clip["frames"].append((now, jpeg))
                if now >= clip["end"]:
                    self._submit(incident_id, clip, clip["end"], partial=False)

    def _submit(self, incident_id, clip, end, partial):
        del self.pending[incident_id]
        self.states[incident_id] = {"status": "processing", "message": "Preparing playback..."}
        self.executor.submit(self._finish, incident_id, clip, end, partial)

    def finish_session(self):
        """Save the available portion when a camera stops; never reuse old frames."""
        with self.lock:
            for incident_id, clip in list(self.pending.items()):
                end = clip["frames"][-1][0] + 1 / self.fps if clip["frames"] else clip["event"]
                self._submit(incident_id, clip, min(end, clip["end"]), partial=True)
            self.buffer.clear()
            self.last_sample = -math.inf

    def _finish(self, incident_id, clip, end, partial):
        temporary = self._path(incident_id, ".pending.mp4")
        destination = self._path(incident_id, ".mp4")
        try:
            samples = clip["frames"]
            if not samples:
                raise ValueError("No frames")
            # Resample by elapsed time: slow inference must not speed up playback.
            start = samples[0][0]
            count = max(1, math.ceil((end - start) * self.fps - 1e-6))
            frames, index = [], 0
            for n in range(count):
                timestamp = start + n / self.fps
                while index + 1 < len(samples) and samples[index + 1][0] <= timestamp:
                    index += 1
                frames.append(samples[index][1])
            used = sum(p.stat().st_size for p in self.directory.glob("*.mp4") if not p.is_symlink())
            if used >= self.max_bytes:
                raise OSError("Recording storage is full")
            self.encoder(frames, self.fps, temporary)
            size = temporary.stat().st_size
            if not 0 < size < 20_000_000 or used + size > self.max_bytes:
                raise OSError("Recording size limit exceeded")
            os.chmod(temporary, 0o600)
            temporary.replace(destination)
            duration = count / self.fps
            self._save_status(incident_id, {
                "status": "ready", "storage": "local", "durationSeconds": duration,
                "eventOffsetSeconds": max(0, min(clip["event"] - start, max(0, duration - 1 / self.fps))),
                "partial": partial, "hasAudio": False,
                "recordedAt": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            self._save_status(incident_id, {"status": "failed", "message": "Recording could not be saved. Check the local camera server and available disk space."})
            print(f"[clips] {incident_id}: recording failed ({type(exc).__name__})")
        finally:
            temporary.unlink(missing_ok=True)
            with self.lock:
                self.states.pop(incident_id, None)
            self.slots.release()

    def close(self):
        with self.lock:
            self.closed = True
        self.finish_session()
        self.executor.shutdown(wait=True)
