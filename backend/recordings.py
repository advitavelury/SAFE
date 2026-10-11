"""Bounded, local-only incident clips containing already-redacted frames."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock, BoundedSemaphore
import json
import math
import os
import re
import subprocess
import time
import logging

import cv2
import numpy as np

FPS = 5
PRE_SECONDS = 3
POST_SECONDS = 5
SIZE = (640, 360)
RETENTION_SECONDS = 24 * 3600
MAX_DISK_BYTES = 250 * 1024 * 1024
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def valid_id(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def encode_clip(path, samples, start, end):
    import imageio_ffmpeg
    count = max(1, math.ceil((end - start) * FPS))
    decoded = [(stamp, cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR))
               for stamp, data in samples]
    if any(frame is None for _, frame in decoded):
        raise RuntimeError('Invalid redacted frame')
    frames = []
    index = 0
    for i in range(count):
        stamp = start + i / FPS
        while index + 1 < len(decoded) and decoded[index + 1][0] <= stamp:
            index += 1
        sample_time, frame = decoded[index]
        # Missing video is black, never a misleading long freeze-frame.
        frames.append((frame if 0 <= stamp - sample_time <= 0.75 else
                       np.zeros((SIZE[1], SIZE[0], 3), np.uint8)).tobytes())
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y',
               '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', '640x360', '-r', str(FPS),
               '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
               '-f', 'mp4', str(path)]
    subprocess.run(command, input=b''.join(frames), stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=45, check=True)
    return count / FPS


class ClipStore:
    def __init__(self, directory, *, encoder=encode_clip, clock=time.time):
        self.root = Path(directory).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.encoder, self.clock = encoder, clock
        self.lock = RLock()
        self.states = {}
        self.callbacks = {}
        self.slots = BoundedSemaphore(4)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.jobs = []
        self.prune()

    def _path(self, incident_id, suffix):
        if not valid_id(incident_id):
            raise ValueError('Invalid incident ID')
        path = self.root / (incident_id + suffix)
        if path.is_symlink():
            raise ValueError('Invalid recording path')
        return path

    def begin(self, incident_id):
        with self.lock:
            self.prune()
            if (not valid_id(incident_id) or incident_id in self.states
                    or self._path(incident_id, '.json').exists()):
                return False
            if not self.slots.acquire(blocking=False):
                self.states[incident_id] = {'status': 'error', 'message': 'Recording capacity reached.'}
                return False
            self.states[incident_id] = {'status': 'recording', 'message': 'Capturing redacted incident footage.'}
            return True

    def when_finished(self, incident_id, callback):
        with self.lock:
            state = self.info(incident_id)
            if state['status'] in ('recording', 'processing'):
                self.callbacks[incident_id] = callback
                return
        self._notify(callback, state)

    @staticmethod
    def _notify(callback, state):
        try:
            callback(state)
        except Exception:
            logging.getLogger(__name__).warning('Recording metadata sync failed; local playback remains available.')

    def finish(self, incident_id, samples, trigger, end, partial):
        with self.lock:
            self.states[incident_id] = {'status': 'processing', 'message': 'Preparing redacted recording.'}
            self.jobs = [job for job in self.jobs if not job.done()]
            self.jobs.append(self.executor.submit(self._encode, incident_id, tuple(samples), trigger, end, partial))

    def _encode(self, incident_id, samples, trigger, end, partial):
        temporary = self._path(incident_id, '.tmp')
        final = self._path(incident_id, '.mp4')
        metadata = self._path(incident_id, '.json')
        try:
            if not samples:
                raise RuntimeError('No redacted frames')
            # Create the output with private permissions before handing it to FFmpeg.
            with temporary.open('xb'):
                temporary.chmod(0o600)
            start = samples[0][0]
            duration = self.encoder(temporary, samples, start, max(end, start + 1/FPS))
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError('Empty recording')
            state = {'status': 'ready', 'durationSeconds': duration,
                     'eventOffsetSeconds': min(max(0, trigger-start), max(0, duration-1/FPS)), 'partial': bool(partial),
                     'redacted': True, 'audio': False, 'createdAt': self.clock(),
                     'privacyMode': 'hidden-background-face-blur-person-mask-fallback'}
            with self.lock:
                temporary.replace(final)
                with metadata.open('x') as file:
                    metadata.chmod(0o600)
                    json.dump(state, file)
                self.states[incident_id] = state
                self.prune()
        except Exception:
            logging.getLogger(__name__).warning('Local recording encoding failed; no clip exposed.')
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            with self.lock:
                self.states[incident_id] = {'status': 'error', 'message': 'Recording could not be saved.'}
        finally:
            self.slots.release()
        with self.lock:
            callback = self.callbacks.pop(incident_id, None)
            state = self.info(incident_id)
        if callback:
            self._notify(callback, state)

    def info(self, incident_id):
        with self.lock:
            self.prune()
            path = self._path(incident_id, '.json')
            if incident_id in self.states:
                if self.states[incident_id]['status'] == 'ready' and not self._path(incident_id, '.mp4').is_file():
                    return {'status': 'unavailable', 'message': 'The local recording was removed.'}
                return dict(self.states[incident_id])
            if path.is_file():
                try:
                    return json.loads(path.read_text())
                except (ValueError, OSError):
                    pass
            return {'status': 'unavailable', 'message': 'No local recording is available for this incident.'}

    def file(self, incident_id):
        with self.lock:
            if self.info(incident_id)['status'] != 'ready':
                return None
            path = self._path(incident_id, '.mp4')
            return path if path.is_file() else None

    def prune(self):
        with self.lock:
            files = sorted((p for p in self.root.glob('*.mp4') if not p.is_symlink()),
                           key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in files)
            for path in files:
                if self.clock() - path.stat().st_mtime > RETENTION_SECONDS or total > MAX_DISK_BYTES:
                    total -= path.stat().st_size
                    path.unlink(missing_ok=True)
                    self._path(path.stem, '.json').unlink(missing_ok=True)
                    self.states.pop(path.stem, None)
            # Bound in-memory error/availability entries as well as video data.
            if len(self.states) > 1000:
                for key in list(self.states):
                    if self.states[key]['status'] not in ('recording', 'processing'):
                        del self.states[key]
                    if len(self.states) <= 500:
                        break

    def close(self):
        self.executor.shutdown(wait=True)


class IncidentRecorder:
    def __init__(self, store, redact):
        self.store, self.redact = store, redact
        self.buffer = deque(maxlen=PRE_SECONDS * FPS + 1)
        self.active = {}
        self.last_time = None

    def observe(self, frame, results, stamp):
        if self.last_time is not None and stamp - self.last_time < 1/FPS:
            return
        safe = self.redact(frame, results)
        # Letterbox instead of distorting body geometry in portrait webcams.
        h, w = safe.shape[:2]
        scale = min(SIZE[0]/w, SIZE[1]/h)
        resized = cv2.resize(safe, (max(1, round(w*scale)), max(1, round(h*scale))))
        canvas = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
        y, x = (SIZE[1]-resized.shape[0])//2, (SIZE[0]-resized.shape[1])//2
        canvas[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
        ok, encoded = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError('Redacted frame could not be buffered')
        sample = (stamp, encoded.tobytes())
        self.buffer.append(sample)
        self.last_time = stamp
        while self.buffer and stamp - self.buffer[0][0] > PRE_SECONDS:
            self.buffer.popleft()
        for incident_id, clip in list(self.active.items()):
            if stamp <= clip['trigger'] + POST_SECONDS:
                clip['samples'].append(sample)
            if stamp >= clip['trigger'] + POST_SECONDS:
                self._finish(incident_id, partial=False)

    def trigger(self, incident_id, stamp):
        if self.store.begin(incident_id):
            self.active[incident_id] = {'samples': list(self.buffer), 'trigger': stamp}

    def _finish(self, incident_id, partial):
        clip = self.active.pop(incident_id)
        samples, trigger = clip['samples'], clip['trigger']
        end = min((samples[-1][0] + 1/FPS) if samples else trigger, trigger + POST_SECONDS)
        gaps = any(b[0]-a[0] > 0.75 for a, b in zip(samples, samples[1:]))
        short_lead = not samples or trigger - samples[0][0] < PRE_SECONDS - 1/FPS
        self.store.finish(incident_id, samples, trigger, end, partial or gaps or short_lead)

    def close(self):
        for incident_id in list(self.active):
            self._finish(incident_id, partial=True)
        self.buffer.clear()
