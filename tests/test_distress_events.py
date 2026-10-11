import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.detection.person import Person
from backend.event_types import AlertLevel
from backend.detection.detectors.sitting import (
    SittingDetector, SITTING_BREAK_SECONDS, BOX_COLOR_ALERT, BOX_COLOR_WARNING,
)


class DistressSittingTests(unittest.TestCase):
    def setUp(self):
        self.person = Person(id=1)
        self.detector = SittingDetector(timedelta(seconds=10))

    def test_prolonged_sitting_alerts_after_hold_time(self):
        self.detector.manage_person_posture("sitting", self.person, 10.0)
        self.assertIsNone(self.detector.alert_sitting_event(self.person, 14.9))
        self.assertEqual(self.detector.alert_sitting_event(self.person, 15.0), AlertLevel.AMBER)
        self.assertEqual(self.detector.alert_sitting_event(self.person, 19.9), AlertLevel.AMBER)
        self.assertEqual(self.detector.alert_sitting_event(self.person, 20.0), AlertLevel.RED)

    def test_sitting_timer_survives_short_non_sitting_noise(self):
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0 + SITTING_BREAK_SECONDS / 2)
        self.detector.manage_person_posture("sitting", self.person, 32.0)
        self.assertEqual(0.0, self.person.sitting_since)

    def test_sitting_timer_resets_after_enough_non_sitting_observations(self):
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0)
        self.detector.manage_person_posture("not sitting", self.person, 1.0 + SITTING_BREAK_SECONDS)
        self.assertIsNone(self.person.sitting_since)
        self.assertIsNone(self.detector.alert_sitting_event(self.person, 99.0))

    def test_configured_warning_fraction_is_used(self):
        self.detector.warning_fraction = 0.8
        self.detector.manage_person_posture("sitting", self.person, 0.0)
        self.assertIsNone(self.detector.alert_sitting_event(self.person, 7.9))
        self.assertEqual(self.detector.alert_sitting_event(self.person, 8.0), AlertLevel.AMBER)


class DistressPacingTests(unittest.TestCase):
    @unittest.skip("No testable pacing module exists yet; unusual-hours movement is not pacing.")
    def test_pacing_alerts_after_repeated_direction_changes(self):
        pass
