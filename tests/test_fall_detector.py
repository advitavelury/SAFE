import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from detection.person import Person
from detection.detectors.fall import DOWN_HOLD_SECONDS, RECOVERY_GRACE_SECONDS, FallDetector

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
        self.assertFalse(
            self.detector.alert_fall_event(
                person=self.person,
                frame_time=100.0,
            )
        )

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
