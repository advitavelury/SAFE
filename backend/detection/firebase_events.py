import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None


_db = None
_warned = False
_env_loaded = False


def load_backend_env():
    """Load backend/.env if present, without requiring python-dotenv."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def firebase_enabled():
    load_backend_env()
    return _truthy(os.getenv("SAFE_FIREBASE_ENABLED", ""))


def _warn_once(message):
    global _warned
    if not _warned:
        print(message)
        _warned = True


def get_firestore_client():
    """Return a Firestore client, or None when Firebase is not configured."""
    global _db

    if _db is not None:
        return _db

    if not firebase_enabled():
        return None

    if firebase_admin is None:
        _warn_once(
            "Firebase is enabled but firebase-admin is not installed. "
            "Run: pip install firebase-admin"
        )
        return None

    service_account_path = (
        os.getenv("FIREBASE_SERVICE_ACCOUNT")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )

    try:
        if not firebase_admin._apps:
            if service_account_path:
                cred = credentials.Certificate(service_account_path)
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    except Exception as exc:
        _warn_once(f"Firebase initialisation failed: {exc}")
        return None

    return _db


def publish_incident(
    event_type,
    person_id,
    zone_id=None,
    note=None,
    status="active",
    confidence=None,
    source="safe-backend",
):
    """Publish a detection incident to Firestore.

    The frontend listens to the same collection and renders these records live.
    Disabled Firebase logs to the terminal. Failed writes are reported without
    crashing the detector; delivery is not queued or retried automatically.
    """
    load_backend_env()
    now = datetime.now(timezone.utc)
    zone_id = zone_id or os.getenv("SAFE_ZONE_ID", "A")
    collection_name = os.getenv("FIREBASE_INCIDENTS_COLLECTION", "incidents")
    incident_id = f"{event_type}-{zone_id}-{person_id}-{uuid.uuid4().hex}"

    payload = {
        "incidentId": incident_id,
        "type": event_type,
        "status": status,
        "zoneId": zone_id,
        "personId": str(person_id),
        "note": note or event_type.replace("_", " ").title(),
        "source": source,
        "tsIso": now.isoformat(),
        "createdAtIso": now.isoformat(),
    }
    if confidence is not None:
        payload["confidence"] = float(confidence)

    client = get_firestore_client()
    if client is None:
        print(f"[firebase disabled] {payload}")
        return incident_id

    payload["ts"] = firestore.SERVER_TIMESTAMP
    payload["createdAt"] = firestore.SERVER_TIMESTAMP
    try:
        client.collection(collection_name).document(incident_id).set(payload, timeout=3, retry=None)
    except Exception as exc:
        print(f"[firebase] incident {incident_id} was not saved ({type(exc).__name__}).")
        return None
    print(f"[firebase] published incident {incident_id}")
    return incident_id


class DetectorEventPublisher:
    """Publish one record per rising alert latch without changing detector rules."""

    EVENTS = (
        ("fall_alerted", "fall", "Fall detected"),
        ("sitting_alerted", "prolonged_sitting", "Prolonged sitting detected"),
        ("isolation_alerted", "isolation", "Prolonged isolation detected"),
        ("wandering_alerted", "wandering", "Movement outside normal hours detected"),
    )

    def __init__(self, publish=None, on_incident=None):
        self.publish = publish or publish_incident
        self.on_incident = on_incident
        self.active = set()

    def publish_person(self, person):
        for attribute, event_type, note in self.EVENTS:
            key = (person.id, event_type)
            if getattr(person, attribute, False):
                if key not in self.active:
                    self.active.add(key)
                    event_time = time.monotonic()
                    incident_id = self.publish(event_type=event_type, person_id=person.id, note=note)
                    if incident_id and self.on_incident:
                        try:
                            self.on_incident(incident_id, event_time)
                        except Exception as exc:
                            print(f"[clips] recording could not start ({type(exc).__name__})")
            else:
                self.active.discard(key)
