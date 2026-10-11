import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.browser_camera_api import create_app
from backend.detector_settings import (
    DetectorSettings, DetectorSettingsPatch, DetectorSettingsService,
    SettingsUnavailable, apply_detector_settings,
)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.document = self.db.collection.return_value.document.return_value
        self.document.get.return_value.exists = False
        self.service = DetectorSettingsService(self.db)

    def test_defaults_and_persisted_update_apply_to_all_detectors(self):
        self.assertEqual(self.service.get().sitting_seconds, 7200)
        updated = self.service.update(DetectorSettingsPatch(sitting_seconds=30, isolation_seconds=45), updated_by='admin')
        self.assertEqual(self.document.set.call_args.args[0]['updated_by'], 'admin')
        wandering, sitting, isolation = Mock(), Mock(), Mock()
        apply_detector_settings(self.service.take_pending_update(), wandering=wandering,
                                sitting=sitting, isolation=isolation)
        self.assertEqual(sitting.threshold_seconds, 30)
        self.assertEqual(isolation.threshold_seconds, 45)
        self.assertIsNone(self.service.take_pending_update())
        self.assertEqual(self.service.get(), updated)

    def test_failed_save_never_changes_running_settings(self):
        original = self.service.get()
        self.document.set.side_effect = RuntimeError('private details')
        with self.assertRaises(SettingsUnavailable):
            self.service.update(DetectorSettingsPatch(sitting_seconds=30), updated_by='admin')
        self.assertEqual(self.service.get(), original)
        self.assertIsNone(self.service.take_pending_update())

    def test_invalid_thresholds_are_rejected(self):
        for patch in [{'sitting_seconds': 0}, {'isolation_seconds': -1},
                      {'sitting_warning_fraction': 1}, {'sitting_seconds': '30'},
                      {'wandering_normal_hours': [{'start': '25:00', 'end': '20:00'}]}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                DetectorSettingsPatch(**patch)

    def test_browser_settings_routes_require_fresh_admin_access(self):
        authorizer = Mock()
        def verify(token):
            if token not in ('admin', 'operator'):
                raise HTTPException(401, 'Invalid token')
            return SimpleNamespace(uid='verified-uid', role=token)
        authorizer.verify.side_effect = verify
        with TestClient(create_app(authorizer=authorizer, detector_factory=Mock(),
                                  settings_service=self.service)) as client:
            url = '/admin/detector-settings'
            for token, status in [(None, 401), ('invalid', 401), ('operator', 403), ('admin', 200)]:
                headers = {'Authorization': f'Bearer {token}'} if token else {}
                self.assertEqual(client.get(url, headers=headers).status_code, status)
                self.assertEqual(client.patch(url, headers=headers, json={'sitting_seconds': 30}).status_code, status)
            self.assertEqual(self.document.set.call_args.args[0]['updated_by'], 'verified-uid')
            self.assertEqual(authorizer.verify.call_count, 6)
            self.assertEqual(client.patch(url, headers={'Authorization': 'Bearer admin'},
                                          json={'sitting_seconds': 0}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
