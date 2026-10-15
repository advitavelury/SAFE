from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from backend.detector_settings import DetectorSettings, DetectorSettingsService, apply_detector_settings
from backend.detection.detectors.sitting import SittingDetector
from backend.detection.person import Person
from backend.event_types import AlertLevel
from backend.routes import setup_routes


class DetectorSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.document = self.db.collection.return_value.document.return_value
        self.document.get.return_value = SimpleNamespace(exists=False)
        self.settings = DetectorSettingsService(self.db)
        self.auth = Mock()
        self.auth.verify.return_value = SimpleNamespace(uid='admin-uid', role='admin', token='test')
        self.client = TestClient(setup_routes(Mock(), Mock(), authorizer=self.auth,
                                              events=Mock(), settings=self.settings))
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer test'}

    def test_save_30_seconds_persists_and_updates_existing_detector(self):
        response = self.client.patch('/admin/detector-settings', headers=self.headers,
                                     json={'sitting_seconds': 30})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['sitting_seconds'], 30)
        self.assertEqual(response.json()['isolation_seconds'], 3600)
        written = self.document.set.call_args.args[0]
        self.assertEqual(written['thresholds']['sitting_seconds'], 30)
        self.assertEqual(written['updated_by'], 'admin-uid')
        updated = self.settings.take_pending_update()
        sitting = SittingDetector(timedelta(hours=2))
        apply_detector_settings(updated, sitting=sitting, isolation=Mock(), wandering=Mock())
        person = Person(1)
        person.sitting_since = 0
        self.assertIsNone(sitting.alert_sitting_event(person, 14.9))
        self.assertEqual(sitting.alert_sitting_event(person, 15), AlertLevel.AMBER)
        self.assertEqual(sitting.alert_sitting_event(person, 29.9), AlertLevel.AMBER)
        self.assertEqual(sitting.alert_sitting_event(person, 30), AlertLevel.RED)
        self.assertEqual(self.client.get('/admin/detector-settings', headers=self.headers).json()['sitting_seconds'], 30)

    def test_operator_and_signed_out_user_cannot_read_or_change_settings(self):
        for method in ['GET', 'PATCH']:
            self.assertEqual(self.client.request(method, '/admin/detector-settings', json={'sitting_seconds': 30}).status_code, 401)
        self.auth.verify.return_value.role = 'operator'
        for method in ['GET', 'PATCH']:
            self.assertEqual(self.client.request(method, '/admin/detector-settings', headers=self.headers,
                                                  json={'sitting_seconds': 30}).status_code, 403)
        self.document.set.assert_not_called()

    def test_invalid_seconds_do_not_write_settings(self):
        for value in [0, -1, 604801, '30', None]:
            response = self.client.patch('/admin/detector-settings', headers=self.headers,
                                         json={'sitting_seconds': value})
            self.assertEqual(response.status_code, 422)
        self.document.set.assert_not_called()

    def test_failed_cloud_write_does_not_publish_detector_update(self):
        self.document.set.side_effect = RuntimeError('offline')
        response = self.client.patch('/admin/detector-settings', headers=self.headers,
                                     json={'sitting_seconds': 30})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.settings.get(), DetectorSettings())
        self.assertIsNone(self.settings.take_pending_update())
