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
        self.assertIsNone(self.person.non_sitting_since)

    def test_sitting_timer_and_latch_reset_after_sustained_non_sitting(self):
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.person.sitting_alerted = True
        self.detector.manage_person_posture("not sitting", self.person, 11.0)
        self.detector.manage_person_posture("not sitting", self.person, 11.0 + SITTING_BREAK_SECONDS)
        self.assertIsNone(self.person.sitting_since)
        self.assertFalse(self.person.sitting_alerted)
        self.assertFalse(self.detector.alert_sitting_event(self.person, 99.0))

    def test_box_colours_follow_warning_and_alert_thresholds(self):
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.assertIsNone(self.detector.sitting_box_color(self.person, 0.0))
        self.assertEqual(BOX_COLOR_WARNING, self.detector.sitting_box_color(self.person, 5.0))
        self.assertEqual(BOX_COLOR_ALERT, self.detector.sitting_box_color(self.person, 10.0))


class DistressPacingTests(unittest.TestCase):
    @unittest.skip("No testable pacing module exists yet; unusual-hours movement is not pacing.")
    def test_pacing_alerts_after_repeated_direction_changes(self):
        pass
