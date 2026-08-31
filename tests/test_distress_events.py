import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISTRESS_FILE = PROJECT_ROOT / "backend" / "detection" / "distress detection" / "yolo_detection.py"


class DummyYOLO:
    def __init__(self, *args, **kwargs):
        pass


# The distress script imports OpenCV and Ultralytics for the demo loop. These
# tests only need the Person state machine, so stubs avoid loading camera/model
# dependencies during unit testing.
sys.modules.setdefault(
    "cv2",
    types.SimpleNamespace(
        FONT_HERSHEY_SIMPLEX=0,
        LINE_AA=0,
        CAP_PROP_FPS=5,
        VideoCapture=lambda *args, **kwargs: None,
        waitKey=lambda *args, **kwargs: -1,
        imshow=lambda *args, **kwargs: None,
        destroyAllWindows=lambda *args, **kwargs: None,
        putText=lambda *args, **kwargs: None,
        rectangle=lambda *args, **kwargs: None,
    ),
)

ultralytics_stub = types.ModuleType("ultralytics")
ultralytics_stub.YOLO = DummyYOLO
sys.modules.setdefault("ultralytics", ultralytics_stub)
sys.modules.setdefault("numpy", types.SimpleNamespace())

spec = importlib.util.spec_from_file_location("distress_yolo_detection", DISTRESS_FILE)
distress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distress)


class DistressSittingTests(unittest.TestCase):
    def setUp(self):
        self.person = distress.Person(id=1)

    def test_prolonged_sitting_alerts_after_hold_time(self):
        self.person.manage_person_posture("sitting", video_time=10.0)

        self.assertFalse(self.person.alert_prolonged_sitting(video_time=12.9))
        self.assertTrue(
            self.person.alert_prolonged_sitting(
                video_time=10.0 + distress.SITTING_HOLD_SECONDS
            )
        )
        self.assertEqual(
            distress.SITTING_HOLD_SECONDS,
            self.person.seconds_seated(video_time=10.0 + distress.SITTING_HOLD_SECONDS),
        )

    def test_sitting_timer_survives_short_non_sitting_noise(self):
        self.person.manage_person_posture("sitting", video_time=0.0)

        for time_value in range(1, distress.SITTING_BREAK_OBSERVATIONS):
            self.person.manage_person_posture("standing", video_time=float(time_value))

        self.assertEqual(0.0, self.person.sitting_since)
        self.assertFalse(self.person.sitting_alerted)

    def test_sitting_timer_resets_after_enough_non_sitting_observations(self):
        self.person.manage_person_posture("sitting", video_time=0.0)

        for time_value in range(1, distress.SITTING_BREAK_OBSERVATIONS + 1):
            self.person.manage_person_posture("standing", video_time=float(time_value))

        self.assertIsNone(self.person.sitting_since)
        self.assertEqual(0.0, self.person.seconds_seated(video_time=99.0))

    def test_acknowledge_clears_open_alert_latches(self):
        self.person.alerted = True
        self.person.sitting_alerted = True

        self.assertEqual(distress.BOX_COLOUR_FALL_ALERT, self.person.box_colour())

        self.person.acknowledge()

        self.assertFalse(self.person.alerted)
        self.assertFalse(self.person.sitting_alerted)
        self.assertEqual(distress.BOX_COLOUR_NORMAL, self.person.box_colour())


class DistressPacingTests(unittest.TestCase):
    @unittest.skip("Pacing detector is planned, but no testable pacing module exists yet.")
    def test_pacing_alerts_after_repeated_direction_changes(self):
        pass


if __name__ == "__main__":
    unittest.main()
