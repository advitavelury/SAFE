import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from detection.person import Person
from detection.detectors.sitting import (
    SittingDetector, SITTING_BREAK_SECONDS, BOX_COLOR_ALERT, BOX_COLOR_WARNING,
)


class DistressSittingTests(unittest.TestCase):
    def setUp(self):
        self.person = Person(id=1)
        self.detector = SittingDetector(timedelta(seconds=10))

    def test_prolonged_sitting_alerts_after_hold_time(self):
        self.detector.manage_person_posture("sitting", self.person, 10.0)
        self.assertFalse(self.detector.alert_sitting_event(self.person, 19.9))
        self.assertTrue(self.detector.alert_sitting_event(self.person, 20.0))

    def test_sitting_timer_survives_short_non_sitting_noise(self):
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0 + SITTING_BREAK_SECONDS / 2)
        self.detector.manage_person_posture("sitting", self.person, 2.0)
        self.assertEqual(0.0, self.person.sitting_since)

    def test_sitting_timer_resets_after_enough_non_sitting_observations(self):
        self.person.manage_person_posture("sitting", video_time=0.0)

        for time_value in range(1, distress.SITTING_BREAK_OBSERVATIONS + 1):
            self.person.manage_person_posture("standing", video_time=float(time_value))

        self.assertIsNone(self.person.sitting_since)
        self.assertEqual(0.0, self.person.seconds_seated(video_time=99.0))

    def test_acknowledge_clears_open_alert_latches(self):
        self.person.alerted = True

        self.assertEqual(distress.BOX_COLOUR_FALL_ALERT, self.person.box_colour())

        self.person.acknowledge()

        self.assertFalse(self.person.alerted)
        self.assertEqual(distress.BOX_COLOUR_NORMAL, self.person.box_colour())


class DistressPacingTests(unittest.TestCase):
    @unittest.skip("No testable pacing module exists yet; unusual-hours movement is not pacing.")
    def test_pacing_alerts_after_repeated_direction_changes(self):
        pass
