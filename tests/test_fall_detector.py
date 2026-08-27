import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETECTION_DIR = PROJECT_ROOT / "backend" / "detection"
sys.path.insert(0, str(DETECTION_DIR))

# The fall detector imports cv2 for drawing in the live demo. These unit tests
# only exercise the state logic, so a tiny stub keeps the tests lightweight.
sys.modules.setdefault(
    "cv2",
    types.SimpleNamespace(
        FONT_HERSHEY_SIMPLEX=0,
        LINE_AA=0,
        putText=lambda *args, **kwargs: None,
    ),
)

from person import Person
from detectors.fall import DOWN_HOLD_SECONDS, RECOVERY_GRACE_SECONDS, FallDetector


class FallDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = FallDetector()
        self.person = Person(id=1)
        self.person_id = 1

    def test_first_seen_lying_down_does_not_trigger_fall(self):
        self.detector.manage_person_posture(
            "lying down",
            person=self.person,
            person_id=self.person_id,
            video_time=0.0,
        )

        self.assertIsNone(self.person.down_since)
        self.assertFalse(
            self.detector.alert_fall_event(
                person_id=self.person_id,
                person=self.person,
                video_time=100.0,
            )
        )

    def test_standing_to_falling_to_lying_down_triggers_after_hold_time(self):
        self.detector.manage_person_posture(
            "standing",
            person=self.person,
            person_id=self.person_id,
            video_time=0.0,
        )
        self.detector.manage_person_posture(
            "falling",
            person=self.person,
            person_id=self.person_id,
            video_time=0.1,
        )
        self.detector.manage_person_posture(
            "lying down",
            person=self.person,
            person_id=self.person_id,
            video_time=0.2,
        )

        self.assertEqual("lying down", self.detector.person_posture[self.person_id])
        self.assertEqual(0.2, self.person.down_since)
        self.assertFalse(
            self.detector.alert_fall_event(
                person_id=self.person_id,
                person=self.person,
                video_time=0.2 + DOWN_HOLD_SECONDS - 0.01,
            )
        )
        self.assertTrue(
            self.detector.alert_fall_event(
                person_id=self.person_id,
                person=self.person,
                video_time=0.2 + DOWN_HOLD_SECONDS,
            )
        )

    def test_recovery_grace_clears_fall_after_sustained_upright_posture(self):
        self.detector.manage_person_posture("standing", self.person, self.person_id, video_time=0.0)
        self.detector.manage_person_posture("falling", self.person, self.person_id, video_time=0.1)
        self.detector.manage_person_posture("lying down", self.person, self.person_id, video_time=0.2)

        with redirect_stdout(StringIO()):
            self.detector.manage_person_posture("standing", self.person, self.person_id, video_time=0.3)
        self.assertEqual("lying down", self.detector.person_posture[self.person_id])
        self.assertIsNotNone(self.person.down_since)

        with redirect_stdout(StringIO()):
            self.detector.manage_person_posture(
                "standing",
                self.person,
                self.person_id,
                video_time=0.3 + RECOVERY_GRACE_SECONDS,
            )

        self.assertEqual("standing", self.detector.person_posture[self.person_id])
        self.assertIsNone(self.person.down_since)


if __name__ == "__main__":
    unittest.main()
