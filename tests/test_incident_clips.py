from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from incident_clips import IncidentClips, encode_mp4, valid_incident_id
from video_server import create_app


def fake_encode(frames, fps, destination):
    destination.write_bytes(b'0123456789abcdef')


class ClipRecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def recorder(self, **options):
        defaults = dict(pre_seconds=2, post_seconds=2, fps=2, encoder=fake_encode)
        defaults.update(options)
        clips = IncidentClips(self.directory.name, **defaults)
        self.addCleanup(clips.close)
        return clips

    def test_pre_and_post_roll_preserve_elapsed_time_and_survive_restart(self):
        encoder = Mock(side_effect=fake_encode)
        clips = self.recorder(encoder=encoder)
        for t in [0, 1, 2]:
            clips.push(str(t).encode(), now=t)
        clips.trigger('fall-test', event_time=2)
        self.assertEqual(clips.status('fall-test')['status'], 'recording')
        clips.push(b'3', now=3)
        clips.push(b'4', now=4)
        clips.close()
        metadata = clips.status('fall-test')
        self.assertEqual(metadata['status'], 'ready')
        self.assertEqual(metadata['durationSeconds'], 4)
        self.assertEqual(metadata['eventOffsetSeconds'], 2)
        self.assertFalse(metadata['partial'])
        self.assertEqual(encoder.call_args.args[0], [b'0', b'0', b'1', b'1', b'2', b'2', b'3', b'3'])
        restarted = self.recorder()
        self.assertEqual(restarted.status('fall-test')['status'], 'ready')
        self.assertIsNotNone(restarted.clip_path('fall-test'))

    def test_stop_saves_partial_clip_and_clears_previous_session_frames(self):
        clips = self.recorder()
        clips.push(b'old', now=0)
        clips.trigger('first', event_time=0)
        clips.push(b'last', now=0.5)
        clips.finish_session()
        clips.trigger('second', event_time=10)
        clips.close()
        self.assertTrue(clips.status('first')['partial'])
        self.assertEqual(clips.status('second')['status'], 'failed')

    def test_concurrency_is_bounded_and_duplicate_triggers_do_not_replace_clip(self):
        clips = self.recorder(max_pending=1)
        clips.push(b'frame', now=0)
        clips.trigger('one', event_time=0)
        clips.trigger('one', event_time=0.5)
        clips.trigger('two', event_time=0.5)
        self.assertEqual(len(clips.pending), 1)
        self.assertEqual(clips.status('two')['status'], 'failed')
        clips.close()
        self.assertEqual(clips.status('one')['status'], 'ready')

    def test_encoder_failure_is_not_a_ready_clip(self):
        clips = self.recorder(encoder=Mock(side_effect=RuntimeError('encoder unavailable')))
        clips.push(b'frame', now=0)
        clips.trigger('failed', event_time=0)
        clips.close()
        self.assertEqual(clips.status('failed')['status'], 'failed')
        self.assertIsNone(clips.clip_path('failed'))

    def test_disk_limit_does_not_delete_existing_recordings(self):
        existing = Path(self.directory.name) / 'existing.mp4'
        existing.write_bytes(b'x' * 10)
        encoder = Mock(side_effect=fake_encode)
        clips = self.recorder(max_bytes=10, encoder=encoder)
        clips.push(b'frame', now=0)
        clips.trigger('quota', event_time=0)
        clips.close()
        encoder.assert_not_called()
        self.assertEqual(existing.read_bytes(), b'x' * 10)
        self.assertEqual(clips.status('quota')['status'], 'failed')

    def test_missing_file_and_unsafe_ids_cannot_be_played(self):
        clips = self.recorder()
        self.assertEqual(clips.status('old-event')['status'], 'unavailable')
        for value in ['../secret', '/tmp/private', '', 'a' * 181, 'id.mp4']:
            self.assertFalse(valid_incident_id(value))
            with self.assertRaises(ValueError):
                clips.status(value)

    def test_real_encoder_produces_decodable_mp4(self):
        import cv2
        import numpy as np
        frames = []
        for position in range(6):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            cv2.rectangle(frame, (position * 15, 20), (position * 15 + 20, 80), (0, 200, 100), -1)
            ok, jpeg = cv2.imencode('.jpg', frame)
            self.assertTrue(ok)
            frames.append(jpeg.tobytes())
        output = Path(self.directory.name) / 'encoded.mp4'
        encode_mp4(frames, 2, output)
        capture = cv2.VideoCapture(str(output))
        try:
            self.assertTrue(capture.isOpened())
            self.assertAlmostEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT), 6, delta=1)
            self.assertTrue(capture.read()[0])
        finally:
            capture.release()


class ClipAccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clips = IncidentClips(self.directory.name, encoder=fake_encode)
        self.clips.push(b'frame', now=0)
        self.clips.trigger('event-1', event_time=0)
        self.clips.close()
        self.allowed = True
        self.client = create_app(Mock(), authorize=lambda token: self.allowed and token == 'staff', clips=self.clips).test_client()
        self.headers = {'Authorization': 'Bearer staff'}

    def test_authentication_and_revocation_apply_to_metadata_and_bytes(self):
        for url in ['/api/incidents/event-1/clip', '/api/incidents/event-1/clip/file']:
            self.assertEqual(self.client.get(url).status_code, 401)
            with self.client.get(url, headers=self.headers) as response:
                self.assertEqual(response.status_code, 200)
        self.allowed = False
        for url in ['/api/incidents/event-1/clip', '/api/incidents/event-1/clip/file']:
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, 403)

    def test_range_requests_and_missing_clips(self):
        response = self.client.get('/api/incidents/event-1/clip/file', headers={**self.headers, 'Range': 'bytes=0-3'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b'0123')
        self.assertEqual(response.mimetype, 'video/mp4')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response.close()
        self.assertEqual(self.client.get('/api/incidents/old-event/clip/file', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/incidents/id.mp4/clip', headers=self.headers).status_code, 400)
