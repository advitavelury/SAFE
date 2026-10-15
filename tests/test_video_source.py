from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import monotonic, sleep
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient
import numpy as np

from backend.routes import setup_routes
from backend.streamers import FrameStreamer
from backend.video_source import VideoSourceController


class FakeProgram:
    def __init__(self):
        self.cam = Mock()
        self.cam.isOpened.return_value = True
        self.event_executor = Mock()
        self.current_annotated_frame = None
        self.fps = 20
        self.started = Event()
        self.finish = Event()
        self.enqueue_event_completion = Mock()

    def get_cam(self):
        return self.cam

    def run(self, stop, *, preview_window):
        assert preview_window is False
        self.current_annotated_frame = np.ones((4, 4, 3), dtype=np.uint8)
        self.started.set()
        try:
            while not stop.wait(.005) and not self.finish.is_set():
                pass
        finally:
            self.cam.release()
            self.event_executor.shutdown(wait=True)


class SourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / 'fall.mp4'
        self.video.touch()
        self.programs = []
        self.before_create = lambda: None

        def factory(*args):
            self.before_create()
            program = FakeProgram()
            self.programs.append(program)
            return program

        self.factory = Mock(side_effect=factory)
        self.source = VideoSourceController(Lock(), self.video, self.factory)
        self.addCleanup(self.source.close)

    def wait_for(self, predicate):
        deadline = monotonic() + 3
        while not predicate() and monotonic() < deadline:
            sleep(.005)
        self.assertTrue(predicate(), self.source.status())

    def start(self, mode):
        generation = self.source.select(mode)['generation']
        self.wait_for(lambda: self.source.is_current(generation) and self.programs[-1].started.is_set())
        return generation

    def test_idle_startup_does_not_open_camera_or_load_model(self):
        self.assertEqual(self.source.status()['state'], 'idle')
        self.factory.assert_not_called()
        self.assertIsNone(self.source.current_annotated_frame)

    def test_switch_releases_previous_capture_before_constructing_next_program(self):
        generation = self.start('video')
        first = self.programs[0]
        self.before_create = lambda: first.cam.release.assert_called_once()
        self.start('live')
        self.assertFalse(self.source.is_current(generation))
        first.event_executor.shutdown.assert_called_once_with(wait=True)
        self.assertEqual(len(self.programs), 2)

    def test_stop_clears_frames_and_completion_is_forwarded_to_active_program(self):
        generation = self.start('live')
        self.source.enqueue_event_completion('event-1')
        self.programs[0].enqueue_event_completion.assert_called_once_with('event-1')
        self.source.select(None)
        self.assertFalse(self.source.is_current(generation))
        self.assertIsNone(self.source.current_annotated_frame)
        self.wait_for(lambda: self.source.status()['state'] == 'idle')
        self.programs[0].cam.release.assert_called_once()

    def test_video_eof_does_not_loop_and_replay_creates_fresh_tracking_session(self):
        first = self.start('video')
        self.programs[0].finish.set()
        self.wait_for(lambda: self.source.status()['state'] == 'ended')
        self.assertIsNone(self.source.current_annotated_frame)
        self.assertEqual(len(self.programs), 1)
        self.assertGreater(self.start('video'), first)
        self.assertEqual(len(self.programs), 2)

    def test_missing_video_and_unknown_modes_do_not_change_current_source(self):
        self.video.unlink()
        with self.assertRaises(FileNotFoundError):
            self.source.select('video')
        with self.assertRaises(ValueError):
            self.source.select('/private/file.mp4')
        self.assertEqual(self.source.status()['generation'], 0)

    def test_camera_open_failure_releases_capture_and_reports_error(self):
        program = FakeProgram()
        program.cam.isOpened.return_value = False
        self.factory.side_effect = lambda *args: program
        with self.assertLogs('backend.video_source', level='ERROR'):
            self.source.select('live')
            self.wait_for(lambda: self.source.status()['state'] == 'error')
        self.wait_for(lambda: program.cam.release.called)
        program.event_executor.shutdown.assert_called_once_with(wait=True)

    def test_stop_while_loading_never_runs_the_obsolete_program(self):
        loading, release = Event(), Event()
        def block():
            loading.set()
            release.wait(2)
        self.before_create = block
        self.source.select('video')
        self.assertTrue(loading.wait(2))
        self.source.select(None)
        release.set()
        self.wait_for(lambda: self.source.status()['state'] == 'idle')
        self.assertFalse(self.programs[0].started.is_set())
        self.programs[0].cam.release.assert_called_once()


class SourceRouteTests(unittest.TestCase):
    def setUp(self):
        self.auth = Mock()
        self.auth.verify.return_value = SimpleNamespace(uid='operator', role='operator', token='test-token')
        self.source = Mock()
        self.source.status.return_value = {'mode': 'video', 'state': 'running', 'generation': 2}
        self.source.select.return_value = self.source.status.return_value
        self.source.is_current.side_effect = lambda generation: generation == self.source.status()['generation']
        self.streamer = Mock()
        self.streamer.get_stream.return_value = Response(b'frame')
        self.client = TestClient(setup_routes(self.streamer, self.source, authorizer=self.auth,
                                             events=Mock(), source_controller=self.source))
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer test-token'}

    def test_source_routes_require_staff_and_operator_can_switch_and_stop(self):
        for method in ['GET', 'POST', 'DELETE']:
            self.assertEqual(self.client.request(method, '/video_source', json={'mode': 'live'}).status_code, 401)
        self.source.select.assert_not_called()
        for mode in ['live', 'video']:
            self.assertEqual(self.client.post('/video_source', headers=self.headers, json={'mode': mode}).status_code, 202)
            self.source.select.assert_called_with(mode)
        self.assertEqual(self.client.delete('/video_source', headers=self.headers).status_code, 202)
        self.source.select.assert_called_with(None)
        self.auth.verify.side_effect = HTTPException(403, 'Inactive')
        self.assertEqual(self.client.post('/video_source', headers=self.headers, json={'mode': 'live'}).status_code, 403)

    def test_arbitrary_files_and_invalid_modes_are_rejected(self):
        for body in [{'mode': 'live', 'path': '/private/test.mp4'}, {'mode': 'file'}, {}]:
            self.assertEqual(self.client.post('/video_source', headers=self.headers, json=body).status_code, 422)
        self.source.select.assert_not_called()

    def test_stale_streams_are_rejected_and_active_stream_checks_generation(self):
        self.assertEqual(self.client.get('/video_feed?generation=1', headers=self.headers).status_code, 409)
        self.streamer.get_stream.assert_not_called()
        self.assertEqual(self.client.get('/video_feed?generation=2', headers=self.headers).status_code, 200)
        current = self.streamer.get_stream.call_args.kwargs['is_current']
        self.assertTrue(current())
        self.source.status.return_value['generation'] = 3
        self.assertFalse(current())

    def test_original_launcher_keeps_stream_route_and_reports_source_control_unavailable(self):
        with TestClient(setup_routes(self.streamer, Mock(), authorizer=self.auth, events=Mock())) as client:
            self.assertEqual(client.get('/video_source', headers=self.headers).status_code, 503)
            self.assertEqual(client.get('/video_feed', headers=self.headers).status_code, 200)

    def test_stream_stops_without_encoding_frames_from_a_new_source(self):
        streamer = FrameStreamer(Mock(), Lock())
        with patch('backend.streamers.cv2.imencode') as encode:
            self.assertEqual(list(streamer._start_stream(Mock(), is_current=lambda: False)), [])
        encode.assert_not_called()
