import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from backend.detection.person import Person
from backend.detection.detectors.fall import DOWN_HOLD_SECONDS, RECOVERY_GRACE_SECONDS, FallDetector

class FallDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = FallDetector()
        self.person = Person(id=1)

    def test_first_seen_lying_down_does_not_trigger_fall(self):
        self.detector.manage_person_posture(
            posture="lying down",
            person=self.person,
            frame_time=0.0,
        )
        self.assertIsNone(self.person.down_since)
        self.assertFalse(self.detector.alert_fall_event(self.person, 100.0))
        self.detector.manage_person_posture("lying down", self.person, 100.0)
        self.assertIsNone(self.person.down_since)

    def test_missing_pose_displays_diagnostic_without_creating_a_fall(self):
        self.person.keypoints = {i: None for i in range(17)}
        self.person.box_coords = (0, 0, 100, 200)
        with patch("backend.detection.detectors.fall.draw_label") as label, redirect_stdout(StringIO()):
            event = self.detector.check_detector(SimpleNamespace(frame=Mock(), frame_time=1.0), self.person)
        self.assertIsNone(event)
        self.assertEqual(label.call_args.args[1], "Fall: pose unclear")

    def test_low_frame_rate_standing_directly_to_lying_starts_timer(self):
        self.detector.manage_person_posture("standing", self.person, 0.0)
        self.detector.manage_person_posture("lying down", self.person, 1.0)
        self.assertEqual(self.person.down_since, 1.0)
        self.assertFalse(self.detector.alert_fall_event(self.person, 1.0))
        self.detector.manage_person_posture("lying down", self.person, 2.0)
        self.assertTrue(self.detector.alert_fall_event(self.person, 2.0))

    def test_horizontal_body_is_not_mistaken_for_side_on_sitting(self):
        self.person.keypoints = {i: None for i in range(17)}
        for i, point in {5: (100, 95), 6: (100, 105), 11: (200, 95), 12: (200, 105),
                         13: (300, 95), 14: (300, 105), 15: (400, 95), 16: (400, 105)}.items():
            self.person.keypoints[i] = point
        self.person.box_coords = (80, 75, 420, 125)
        self.person.torso_len = 100
        self.person.torso_angle = 90
        self.person.frame_h = 480
        with redirect_stdout(StringIO()):
            result = self.detector.classify_posture(self.person)
        self.assertEqual(result, "lying down")

    def test_upright_torso_with_horizontal_thighs_is_still_sitting(self):
        self.person.keypoints = {i: None for i in range(17)}
        for i, point in {5: (100, 95), 6: (110, 105), 11: (100, 195), 12: (110, 205),
                         13: (200, 195), 14: (210, 205), 15: (200, 295), 16: (210, 305)}.items():
            self.person.keypoints[i] = point
        self.person.box_coords = (80, 75, 230, 325)
        self.person.torso_len = 100
        self.person.torso_angle = 0
        self.person.frame_h = 480
        with redirect_stdout(StringIO()):
            result = self.detector.classify_posture(self.person)
        self.assertEqual(result, "sitting")

    def test_standing_to_falling_to_lying_down_triggers_after_hold_time(self):
        self.detector.manage_person_posture(
            posture="standing",
            person=self.person,
            frame_time=0.0,
        )
        self.detector.manage_person_posture(
            posture="falling",
            person=self.person,
            frame_time=0.1,
        )
        self.detector.manage_person_posture(
            posture="lying down",
            person=self.person,
            frame_time=0.2,
        )

        self.assertEqual("lying down", self.detector.person_posture[self.person.id])
        self.assertEqual(0.2, self.person.down_since)
        self.assertFalse(
            self.detector.alert_fall_event(
                person=self.person,
                frame_time=0.2 + DOWN_HOLD_SECONDS - 0.01,
            )
        )
        self.assertTrue(
            self.detector.alert_fall_event(
                person=self.person,
                frame_time=0.2 + DOWN_HOLD_SECONDS,
            )
        )

    def test_recovery_grace_clears_fall_after_sustained_upright_posture(self):
        self.detector.manage_person_posture(posture="standing", person=self.person, frame_time=0.0)
        self.detector.manage_person_posture(posture="falling", person=self.person, frame_time=0.1)
        self.detector.manage_person_posture(posture="lying down", person=self.person, frame_time=0.2)

        with redirect_stdout(StringIO()):
            self.detector.manage_person_posture(posture="standing", person=self.person,frame_time=0.3)
        self.assertEqual("lying down", self.detector.person_posture[self.person.id])
        self.assertIsNotNone(self.person.down_since)

        with redirect_stdout(StringIO()):
            self.detector.manage_person_posture(
                posture="standing",
                person=self.person,
                frame_time=0.3 + RECOVERY_GRACE_SECONDS,
            )

        self.assertEqual("standing", self.detector.person_posture[self.person.id])
        self.assertIsNone(self.person.down_since)


if __name__ == "__main__":
    unittest.main()
