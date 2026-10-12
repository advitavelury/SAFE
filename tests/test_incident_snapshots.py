import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from backend.browser_detection import BrowserDetector, BrowserIncidentWriter
from backend.detection.detection_types import DetectionResult
from backend.event_types import AlertLevel, EventType
from backend.incident_snapshots import encode_snapshot, IncidentSnapshotStore, MAX_SNAPSHOT_BYTES


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.random.default_rng(9).integers(0, 255, (120, 160, 3), dtype=np.uint8)
        self.boxes = np.array([[20, 10, 100, 110]])
        self.points = np.zeros((1, 17, 2))
        self.confidence = np.zeros((1, 17))
        self.points[0, [0, 5, 6]] = [[45, 25], [35, 50], [55, 50]]
        self.confidence[0, [0, 5, 6]] = 1
        self.db = Mock()
        self.ref = self.db.collection.return_value.document.return_value
        self.ref.id = 'incident-1'
        self.bucket = Mock(name='bucket')
        self.bucket.name = 'fixture-bucket'
        self.store = IncidentSnapshotStore(self.bucket)
        self.writer = BrowserIncidentWriter(self.db, 'session', snapshot_store=self.store)

    def jpeg(self):
        return encode_snapshot(self.frame, self.boxes, self.points, self.confidence)

    def test_jpeg_blurs_face_hides_background_and_does_not_modify_input(self):
        original = self.frame.copy()
        jpeg = self.jpeg()
        safe = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertLess(len(jpeg), MAX_SNAPSHOT_BYTES)
        self.assertLess(safe[20:35, 37:53].std(), original[20:35, 37:53].std()/2)
        self.assertLess(safe[:, :10].max(), 5)
        np.testing.assert_array_equal(original, self.frame)

    def test_missing_pose_is_masked_instead_of_exposing_original(self):
        self.confidence[:] = 0
        safe = cv2.imdecode(np.frombuffer(self.jpeg(), np.uint8), cv2.IMREAD_COLOR)
        self.assertFalse(safe.any())

    def test_snapshot_dimensions_and_size_are_bounded(self):
        frame = np.full((720, 1280, 3), 100, np.uint8)
        jpeg = encode_snapshot(frame, self.boxes, self.points, self.confidence)
        self.assertEqual(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape, (360, 640, 3))
        with patch('backend.incident_snapshots.cv2.imencode', return_value=(False, None)):
            with self.assertRaises(ValueError):
                self.jpeg()

    def test_red_event_uploads_once_after_metadata_and_links_same_id_and_timestamp(self):
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        prepared = self.writer.prepare(event, None, 10, self.jpeg())
        self.writer.create_event(2, event.event_type, event.alert_level, prepared)
        self.ref.set.assert_called_once()
        self.assertEqual(self.ref.set.call_args.args[0]['snapshot']['status'], 'pending')
        self.bucket.blob.assert_called_once_with('incident-snapshots/incident-1.jpg')
        blob = self.bucket.blob.return_value
        blob.upload_from_string.assert_called_once_with(prepared.snapshot, content_type='image/jpeg',
            if_generation_match=0, timeout=10, retry=None)
        self.assertEqual(blob.cache_control, 'private, no-store')
        blob.make_public.assert_not_called()
        blob.generate_signed_url.assert_not_called()
        self.assertNotIn('firebaseStorageDownloadTokens', blob.metadata)
        state = self.ref.update.call_args.args[0]['snapshot']
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(state['capturedAt'], prepared.timestamp)
        self.assertEqual(state['path'], 'incident-snapshots/incident-1.jpg')
        self.assertTrue(state['redacted'])

    def test_amber_never_uploads_even_with_prepared_image(self):
        event = DetectionResult(EventType.SITTING_DISTRESS, AlertLevel.AMBER)
        prepared = self.writer.prepare(event, None, 10, self.jpeg())
        self.writer.create_event(2, event.event_type, event.alert_level, prepared)
        self.bucket.blob.assert_not_called()
        self.assertNotIn('snapshot', self.ref.set.call_args.args[0])

    def test_upload_failure_leaves_incident_saved_and_marks_snapshot_failed(self):
        self.bucket.blob.return_value.upload_from_string.side_effect = RuntimeError('secret')
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        result = self.writer.create_event(2, event.event_type, event.alert_level,
            self.writer.prepare(event, None, 10, self.jpeg()))
        self.assertEqual(result.id, 'incident-1')
        self.assertEqual(self.ref.update.call_args.args[0]['snapshot']['status'], 'failed')

    def test_metadata_failure_never_uploads_an_orphan_image(self):
        self.ref.set.side_effect = RuntimeError('db unavailable')
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        with self.assertRaises(RuntimeError):
            self.writer.create_event(2, event.event_type, event.alert_level,
                self.writer.prepare(event, None, 10, self.jpeg()))
        self.bucket.blob.assert_not_called()

    def test_status_update_failure_does_not_break_incident_or_retry_upload(self):
        self.ref.update.side_effect = RuntimeError('db unavailable')
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        result = self.writer.create_event(2, event.event_type, event.alert_level,
            self.writer.prepare(event, None, 10, self.jpeg()))
        self.assertEqual(result.id, 'incident-1')
        self.bucket.blob.return_value.upload_from_string.assert_called_once()

    def test_redaction_failure_never_falls_back_to_raw_image(self):
        detector = BrowserDetector.__new__(BrowserDetector)
        detector.recorder = None
        detector.snapshots_enabled = True
        detector.events = self.writer
        event = DetectionResult(EventType.FALL, AlertLevel.RED)
        with patch('backend.browser_detection.encode_snapshot', side_effect=ValueError('bad pose')):
            prepared = detector.prepare_event_frame(self.frame, self.points, self.boxes,
                                                   self.confidence, 0, event, 10)
        self.assertIsNone(prepared.snapshot)
        self.writer.create_event(2, event.event_type, event.alert_level, prepared)
        self.assertEqual(self.ref.set.call_args.args[0]['snapshot']['status'], 'failed')
        self.bucket.blob.assert_not_called()

    def test_disabled_writer_keeps_metadata_only_even_for_red_events(self):
        writer = BrowserIncidentWriter(self.db, 'session')
        writer.create_event(1, EventType.FALL, AlertLevel.RED, self.frame)
        self.assertNotIn('snapshot', self.ref.set.call_args.args[0])
        self.bucket.blob.assert_not_called()

    def test_store_rejects_invalid_ids_and_oversized_payloads(self):
        for incident_id, data in [('../outside', b'image'), ('id', b'x' * (MAX_SNAPSHOT_BYTES + 1)),
                                  ('id', self.frame), ('id', b'')]:
            with self.assertRaises(ValueError):
                self.store.upload(incident_id, data)
        self.bucket.blob.assert_not_called()
