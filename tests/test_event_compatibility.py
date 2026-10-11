import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np

from backend.event_types import Event, AlertLevel
from backend.detection.anonymise_frame import anonymise_event


class EventCompatibilityTests(unittest.TestCase):
    def test_old_events_can_be_read_without_inventing_a_level(self):
        fields = dict(id='old-event', person_id=1, event_type='fall',
                      timestamp=datetime.now(timezone.utc), image_path='events/old.jpeg')
        self.assertIsNone(Event(**fields).alert_level)
        self.assertEqual(Event(**fields, alert_level='red').alert_level, AlertLevel.RED)

    def test_snapshot_blurs_target_and_overlapping_people_before_cropping(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        boxes = np.array([[10, 10, 60, 80], [40, 20, 90, 90], [80, 0, 100, 10]])
        with patch('backend.detection.anonymise_frame.blur_person') as blur:
            result = anonymise_event(frame, np.zeros((3, 17, 2)), boxes,
                                     np.zeros((3, 17)), 0)
        self.assertEqual(blur.call_count, 2)
        self.assertEqual(result.shape, (70, 50, 3))

    def test_missing_face_landmarks_blur_the_entire_person(self):
        frame = np.random.default_rng(42).integers(0, 256, (100, 100, 3), dtype=np.uint8)
        original = frame.copy()
        result = anonymise_event(frame, np.zeros((1, 17, 2)), np.array([[10, 10, 80, 90]]),
                                 np.zeros((1, 17)), 0)
        self.assertLess(result.std(), original[10:90, 10:80].std() / 2)
        np.testing.assert_array_equal(frame[:10], original[:10])


if __name__ == '__main__':
    unittest.main()
