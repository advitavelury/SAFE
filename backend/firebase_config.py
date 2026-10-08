"""Load the team's backend-only Firebase credentials from a local JSON file."""
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore, storage


PROJECT_ID = "safe-ddacb"
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_KEY = BACKEND_DIR / "safe-ddacb-firebase-adminsdk-fbsvc-7c69c74b63.json"


def initialize_firebase():
    try:
        app = firebase_admin.get_app()
    except ValueError:
        configured_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        path = Path(configured_path).expanduser() if configured_path else DEFAULT_KEY
        if not path.is_absolute():
            path = BACKEND_DIR.parent / path
        if not path.is_file():
            raise RuntimeError(
                "Firebase service-account JSON is missing. Set FIREBASE_SERVICE_ACCOUNT "
                "to the local JSON file path, or place the file at the configured "
                "backend default path. Never paste the private key into frontend code."
            )
        try:
            credential = credentials.Certificate(str(path))
        except (OSError, ValueError):
            raise RuntimeError("Unable to load the Firebase service-account JSON file.") from None
        if credential.project_id != PROJECT_ID:
            raise RuntimeError("The service-account file must belong to safe-ddacb.")
        app = firebase_admin.initialize_app(credential, {
            "projectId": PROJECT_ID,
            "storageBucket": "safe-ddacb.firebasestorage.app",
        })
    if app.project_id != PROJECT_ID:
        raise RuntimeError("The active Firebase Admin app must use safe-ddacb.")
    return app


app = initialize_firebase()
production_db = firestore.client(app=app)
production_bucket = storage.bucket(app=app)
