import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
import torch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.browser_camera_api import create_app, BrowserSessions, SESSION_IDLE_SECONDS
from backend.browser_detection import BrowserIncidentWriter
from backend.detection.detection_types import DetectionResult
from backend.event_types import EventType, AlertLevel
from backend.recording_privacy import redact_recording_frame
from backend.recordings import ClipStore, IncidentRecorder, RETENTION_SECONDS


def pose_results(boxes, points=None, confidence=None):
    count = len(boxes)
    return [SimpleNamespace(boxes=SimpleNamespace(xyxy=torch.tensor(boxes)),
        keypoints=SimpleNamespace(xy=torch.tensor(points if points is not None else np.zeros((count, 17, 2))),
                                 conf=torch.tensor(confidence if confidence is not None else np.zeros((count, 17)))))]


def fake_encoder(path, samples, start, end):
    path.write_bytes(b'fixture-video')
    return end-start


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.random.default_rng(8).integers(0, 255, (120, 160, 3), dtype=np.uint8)

    def test_unknown_or_missing_face_hides_people_and_background(self):
        self.assertFalse(redact_recording_frame(self.frame, []).any())
        self.assertFalse(redact_recording_frame(self.frame, pose_results([[10, 10, 150, 115]])).any())

    def test_all_faces_redacted_and_overlap_cannot_restore_them(self):
        points = np.zeros((2, 17, 2))
        confidence = np.zeros((2, 17))
        for i, x in enumerate((45, 80)):
            points[i, 0] = [x, 25]
            points[i, 5] = [x-10, 50]
            points[i, 6] = [x+10, 50]
            confidence[i, [0, 5, 6]] = 1
        results = pose_results([[20, 10, 100, 110], [55, 5, 140, 115]], points, confidence)
        original = self.frame.copy()
        safe = redact_recording_frame(self.frame, results)
        for x in (45, 80):
            self.assertLess(safe[20:35, x-8:x+8].std(), original[20:35, x-8:x+8].std()/2)
        self.assertFalse(safe[:, :15].any())
        np.testing.assert_array_equal(self.frame, original)

    def test_uncertain_overlapping_person_is_concealed_last(self):
        points = np.zeros((2, 17, 2))
        confidence = np.zeros((2, 17))
        points[0, [0, 5, 6]] = [[45, 25], [35, 50], [55, 50]]
        confidence[0, [0, 5, 6]] = 1
        safe = redact_recording_frame(self.frame, pose_results(
            [[20, 10, 100, 110], [55, 5, 140, 115]], points, confidence))
        self.assertFalse(safe[5:115, 55:140].any())


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ClipStore(self.directory.name, encoder=fake_encoder)
        self.addCleanup(self.store.close)
        self.frame = np.full((120, 160, 3), 200, np.uint8)
        self.recorder = IncidentRecorder(self.store, lambda frame, results: np.zeros_like(frame))

    def feed(self, values):
        for stamp in values:
            self.recorder.observe(self.frame, [], stamp)

    def test_only_redacted_frames_are_buffered_and_encoded_with_pre_and_post(self):
        self.feed(np.arange(0, 3.21, .21))
        for _, data in self.recorder.buffer:
            decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            self.assertFalse(decoded.any())
        self.recorder.trigger('red-1', 3.2)
        self.feed(np.arange(3.4, 8.5, .21))
        self.store.close()
        info = self.store.info('red-1')
        self.assertEqual(info['status'], 'ready')
        self.assertTrue(info['redacted'])
        self.assertFalse(info['audio'])
        self.assertGreater(info['eventOffsetSeconds'], 2)
        self.assertLessEqual(info['durationSeconds'], 8.2)
        self.assertTrue(self.store.file('red-1').is_file())
        self.assertEqual(set(p.suffix for p in Path(self.directory.name).iterdir()), {'.mp4', '.json'})
        if os.name == 'posix':
            self.assertEqual(self.store.file('red-1').stat().st_mode & 0o777, 0o600)

    def test_stop_flushes_partial_clip_and_clears_buffer(self):
        self.feed([0, .3, .6])
        self.recorder.trigger('red-2', .6)
        self.recorder.close()
        self.store.close()
        self.assertTrue(self.store.info('red-2')['partial'])
        self.assertFalse(self.recorder.buffer)

    def test_privacy_failure_does_not_buffer_original_frame(self):
        self.recorder.redact = Mock(side_effect=ValueError('bad landmarks'))
        with self.assertRaises(ValueError):
            self.feed([1])
        self.assertFalse(self.recorder.buffer)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_amber_creates_no_recording_and_red_metadata_keeps_same_incident_id(self):
        db = Mock()
        ref = db.collection.return_value.document.return_value
        ref.id = 'red-3'
        writer = BrowserIncidentWriter(db, 'session', self.store)
        recorder = Mock()
        amber = DetectionResult(EventType.SITTING_DISTRESS, AlertLevel.AMBER)
        writer.prepare(amber, recorder, 1)
        recorder.trigger.assert_not_called()
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        self.feed([0, .3])
        prepared = writer.prepare(event, self.recorder, .3)
        result = writer.create_event(1, event.event_type, event.alert_level, prepared)
        self.assertEqual(result.id, 'red-3')
        self.recorder.close()
        self.store.close()
        self.assertTrue(ref.update.call_args.args[0]['recordingAvailable'])
        self.assertTrue(ref.update.call_args.args[0]['recordingRedacted'])

    def test_capacity_and_expiry_are_bounded(self):
        for i in range(4):
            self.assertTrue(self.store.begin(f'red-{i}'))
        self.assertFalse(self.store.begin('red-5'))
        self.assertEqual(self.store.info('red-5')['status'], 'error')
        path = Path(self.directory.name) / 'old.mp4'
        path.write_bytes(b'old')
        (Path(self.directory.name) / 'old.json').write_text('{}')
        old = self.store.clock() - RETENTION_SECONDS - 5
        os.utime(path, (old, old))
        self.store.prune()
        self.assertFalse(path.exists())

    def test_encoder_failure_exposes_no_file_or_internal_error(self):
        self.store.encoder = Mock(side_effect=RuntimeError('private path'))
        self.feed([0, .3])
        self.recorder.trigger('bad', .3)
        self.recorder.close()
        self.store.close()
        self.assertEqual(self.store.info('bad')['status'], 'error')
        self.assertNotIn('private', json.dumps(self.store.info('bad')))
        self.assertIsNone(self.store.file('bad'))
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_saved_metadata_is_read_after_restart(self):
        self.feed([0, .3])
        self.recorder.trigger('restart', .3)
        self.recorder.close()
        self.store.close()
        reopened = ClipStore(self.directory.name, encoder=fake_encoder)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.info('restart')['status'], 'ready')

    def test_disk_limit_removes_oldest_completed_clip(self):
        root = Path(self.directory.name)
        for index in (1, 2):
            path = root / f'clip-{index}.mp4'
            path.write_bytes(b'12345678')
            (root / f'clip-{index}.json').write_text('{}')
            os.utime(path, (self.store.clock()-10+index, self.store.clock()-10+index))
        with patch('backend.recordings.MAX_DISK_BYTES', 10):
            self.store.prune()
        self.assertFalse((root / 'clip-1.mp4').exists())
        self.assertTrue((root / 'clip-2.mp4').exists())

    def test_metadata_sync_failure_does_not_break_saved_clip(self):
        self.feed([0, .3])
        self.recorder.trigger('sync', .3)
        self.recorder.close()
        self.store.close()
        self.store.when_finished('sync', Mock(side_effect=RuntimeError('offline')))
        self.assertEqual(self.store.info('sync')['status'], 'ready')

    def test_real_encoder_produces_decodable_redacted_h264_without_raw_files(self):
        from backend.recordings import encode_clip
        self.store.encoder = encode_clip
        self.feed([0, .3, .6])
        self.recorder.trigger('actual-codec', .6)
        self.feed([.9, 1.2])
        self.recorder.close()
        self.store.close()
        self.assertEqual(self.store.info('actual-codec')['status'], 'ready')
        video = cv2.VideoCapture(str(self.store.file('actual-codec')))
        decoded = 0
        try:
            while True:
                ok, frame = video.read()
                if not ok:
                    break
                self.assertFalse(frame.any(), 'Only the black redacted fixture may be encoded')
                self.assertEqual(frame.shape, (360, 640, 3))
                decoded += 1
        finally:
            video.release()
        self.assertGreater(decoded, 3)


class PlaybackAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ClipStore(self.directory.name, encoder=fake_encoder)
        self.addCleanup(self.store.close)
        self.authorizer = Mock()
        def verify(token):
            if token not in ('admin', 'operator'):
                raise HTTPException(401, 'Sign-in required')
            return SimpleNamespace(uid=token, role=token)
        self.authorizer.verify.side_effect = verify
        self.factory = Mock()
        self.recording_factory = Mock()
        self.client = TestClient(create_app(authorizer=self.authorizer, detector_factory=self.factory,
            clip_store=self.store, recording_factory=self.recording_factory))
        self.addCleanup(self.client.close)

    def headers(self, role):
        return {'Authorization': 'Bearer ' + role}

    def test_recording_requires_explicit_staff_opt_in(self):
        url = '/api/browser-camera/sessions'
        for role in ('admin', 'operator'):
            self.recording_factory.reset_mock()
            response = self.client.post(url, headers=self.headers(role))
            self.assertFalse(response.json()['recording'])
            self.recording_factory.assert_not_called()
            self.client.delete(url+'/'+response.json()['id'], headers=self.headers(role))
            response = self.client.post(url, json={'recordRedEvents': True}, headers=self.headers(role))
            self.assertTrue(response.json()['recording'])
            self.recording_factory.assert_called_once()
            self.client.delete(url+'/'+response.json()['id'], headers=self.headers(role))

    def test_staff_can_read_clip_metadata_but_only_admin_can_read_video(self):
        recorder = IncidentRecorder(self.store, lambda frame, results: np.zeros_like(frame))
        recorder.observe(np.zeros((120, 160, 3), np.uint8), [], 0)
        recorder.trigger('incident-1', 0)
        recorder.close()
        self.store.close()
        base = '/api/incidents/incident-1/clip'
        admin_info = self.client.get(base, headers=self.headers('admin'))
        staff_info = self.client.get(base, headers=self.headers('operator'))
        self.assertEqual(staff_info.status_code, 200)
        self.assertEqual(staff_info.json(), admin_info.json())
        self.assertEqual(staff_info.json()['status'], 'ready')
        self.assertEqual(staff_info.headers['cache-control'], 'no-store')
        response = self.client.get(base+'/file', headers=self.headers('admin'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'video/mp4')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(base+'/file', headers=self.headers('operator')).status_code, 403)
        self.assertEqual(self.client.get(base+'/file', headers={**self.headers('operator'),
            'Range': 'bytes=0-15'}).status_code, 403)
        self.assertEqual(self.client.get(base).status_code, 401)
        self.assertEqual(self.client.get(base+'/file?token=admin').status_code, 401)
        self.authorizer.verify.side_effect = HTTPException(403, 'Revoked')
        self.assertEqual(self.client.get(base, headers=self.headers('admin')).status_code, 403)
        self.assertEqual(self.client.get(base+'/file', headers=self.headers('admin')).status_code, 403)

    def test_playback_rechecks_admin_role_on_every_request(self):
        base = '/api/incidents/incident-1/clip'
        self.assertEqual(self.client.get(base, headers=self.headers('admin')).status_code, 200)
        self.authorizer.verify.side_effect = lambda token: SimpleNamespace(uid='admin', role='operator')
        self.assertEqual(self.client.get(base, headers=self.headers('admin')).status_code, 200)
        self.assertEqual(self.client.get(base+'/file', headers=self.headers('admin')).status_code, 403)

    def test_operator_can_read_disabled_status_but_not_video(self):
        with TestClient(create_app(authorizer=self.authorizer, detector_factory=self.factory)) as client:
            info = client.get('/api/incidents/missing/clip', headers=self.headers('operator'))
            self.assertEqual(info.status_code, 200)
            self.assertEqual(info.json()['status'], 'unavailable')
            self.assertEqual(client.get('/api/incidents/missing/clip/file',
                headers=self.headers('operator')).status_code, 403)

    def test_paths_and_symlinks_cannot_escape_private_directory(self):
        for value in ('../secret', '/tmp/secret', 'bad.id'):
            with self.assertRaises(ValueError):
                self.store.info(value)
        (Path(self.directory.name) / 'symlink.json').symlink_to('/etc/hosts')
        response = self.client.get('/api/incidents/symlink/clip', headers=self.headers('admin'))
        self.assertEqual(response.status_code, 404)

    def test_idle_expiry_finalizes_session_without_another_frame(self):
        now = [0]
        detector = Mock()
        sessions = BrowserSessions(Mock(return_value=detector), clock=lambda: now[0])
        sessions.start('admin')
        now[0] = SESSION_IDLE_SECONDS + 1
        sessions.expire()
        detector.close.assert_called_once()
        self.assertIsNone(sessions.session)

    def test_disabled_recording_is_rejected_instead_of_silently_ignored(self):
        with TestClient(create_app(authorizer=self.authorizer, detector_factory=self.factory)) as client:
            response = client.post('/api/browser-camera/sessions', json={'recordRedEvents': True},
                                   headers=self.headers('admin'))
            self.assertEqual(response.status_code, 409)
            self.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
