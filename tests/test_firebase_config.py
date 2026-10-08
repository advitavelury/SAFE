import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


CONFIG = Path(__file__).resolve().parents[1] / "backend" / "firebase_config.py"


class FirebaseConfigTests(unittest.TestCase):
    def load_config(self, path, *, project="safe-ddacb", existing=False, invalid=False):
        app = Mock(project_id=project)
        credential = Mock(project_id=project)
        spec = importlib.util.spec_from_file_location("firebase_config_test", CONFIG)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"FIREBASE_SERVICE_ACCOUNT": str(path)}), \
             patch("firebase_admin.get_app", return_value=app, side_effect=None if existing else ValueError()), \
             patch("firebase_admin.credentials.Certificate", return_value=credential,
                   side_effect=ValueError("invalid private data") if invalid else None) as certificate, \
             patch("firebase_admin.initialize_app", return_value=app) as initialize, \
             patch("firebase_admin.firestore.client") as db, \
             patch("firebase_admin.storage.bucket") as bucket:
            spec.loader.exec_module(module)
            return module, certificate, initialize, db, bucket, app

    def test_explicit_file_initializes_same_project_for_db_and_bucket(self):
        with tempfile.NamedTemporaryFile(suffix=".json") as file:
            module, certificate, initialize, db, bucket, app = self.load_config(file.name)
        certificate.assert_called_once_with(file.name)
        self.assertEqual(initialize.call_args.args[1], {
            "projectId": "safe-ddacb", "storageBucket": "safe-ddacb.firebasestorage.app",
        })
        db.assert_called_once_with(app=app)
        bucket.assert_called_once_with(app=app)
        self.assertIs(module.app, app)

    def test_default_filename_is_still_supported(self):
        with patch("pathlib.Path.is_file", return_value=True):
            _, certificate, *_ = self.load_config("")
        self.assertEqual(Path(certificate.call_args.args[0]),
                         CONFIG.parent / "safe-ddacb-firebase-adminsdk-fbsvc-7c69c74b63.json")

    def test_relative_paths_resolve_from_repo_root(self):
        with patch("pathlib.Path.is_file", return_value=True):
            _, certificate, *_ = self.load_config(".secrets/firebase-service-account.json")
        self.assertEqual(Path(certificate.call_args.args[0]), CONFIG.parent.parent / ".secrets/firebase-service-account.json")

    def test_missing_file_produces_setup_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "JSON is missing"):
                self.load_config(Path(directory) / "missing.json")

    def test_old_project_credentials_are_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".json") as file:
            with self.assertRaisesRegex(RuntimeError, "must belong to safe-ddacb"):
                self.load_config(file.name, project="safe-1426e")

    def test_invalid_file_does_not_expose_credential_details(self):
        with tempfile.NamedTemporaryFile(suffix=".json") as file:
            with self.assertRaises(RuntimeError) as error:
                self.load_config(file.name, invalid=True)
        self.assertEqual(str(error.exception), "Unable to load the Firebase service-account JSON file.")

    def test_existing_matching_app_is_reused(self):
        _, certificate, initialize, *_ = self.load_config("missing.json", existing=True)
        certificate.assert_not_called()
        initialize.assert_not_called()

    def test_existing_wrong_project_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "must use safe-ddacb"):
            self.load_config("missing.json", existing=True, project="safe-1426e")
