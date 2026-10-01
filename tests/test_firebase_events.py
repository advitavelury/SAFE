import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETECTION_DIR = PROJECT_ROOT / "backend" / "detection"
sys.path.insert(0, str(DETECTION_DIR))

import firebase_events


class FakeDocument:
    def __init__(self):
        self.payload = None

    def set(self, payload, **kwargs):
        self.payload = payload


class FakeCollection:
    def __init__(self):
        self.document_id = None
        self.document_ref = FakeDocument()

    def document(self, document_id):
        self.document_id = document_id
        return self.document_ref


class FakeFirestoreClient:
    def __init__(self):
        self.collection_name = None
        self.collection_ref = FakeCollection()

    def collection(self, collection_name):
        self.collection_name = collection_name
        return self.collection_ref


class FirebaseEventsTests(unittest.TestCase):
    def test_write_failure_does_not_crash_detection(self):
        client = Mock()
        client.collection.return_value.document.return_value.set.side_effect = RuntimeError("offline")
        with patch.object(firebase_events, "load_backend_env"), \
             patch.object(firebase_events, "get_firestore_client", return_value=client), \
             patch.object(firebase_events, "firestore", types.SimpleNamespace(SERVER_TIMESTAMP="now")), \
             redirect_stdout(StringIO()):
            self.assertIsNone(firebase_events.publish_incident("fall", 1))

    def test_publish_incident_logs_when_firebase_is_disabled(self):
        with patch.object(firebase_events, "load_backend_env", lambda: None):
            with patch.dict(os.environ, {"SAFE_FIREBASE_ENABLED": "", "SAFE_ZONE_ID": "B"}):
                output = StringIO()
                with redirect_stdout(output):
                    incident_id = firebase_events.publish_incident(
                        event_type="fall",
                        person_id=7,
                        note="Fall detected",
                    )

        self.assertTrue(incident_id.startswith("fall-B-7-"))
        self.assertIn("[firebase disabled]", output.getvalue())
        self.assertIn("'zoneId': 'B'", output.getvalue())

    def test_publish_incident_writes_expected_firestore_payload(self):
        fake_client = FakeFirestoreClient()

        with patch.object(firebase_events, "load_backend_env", lambda: None):
            with patch.object(firebase_events, "get_firestore_client", return_value=fake_client):
                with patch.object(
                    firebase_events,
                    "firestore",
                    types.SimpleNamespace(SERVER_TIMESTAMP="SERVER_TIMESTAMP"),
                ):
                    with patch.dict(
                        os.environ,
                        {
                            "FIREBASE_INCIDENTS_COLLECTION": "care_incidents",
                            "SAFE_ZONE_ID": "Room-2",
                        },
                    ):
                        with redirect_stdout(StringIO()):
                            incident_id = firebase_events.publish_incident(
                                event_type="distress",
                                person_id="12",
                                note="Prolonged sitting detected",
                                confidence=0.82,
                            )

        self.assertEqual("care_incidents", fake_client.collection_name)
        self.assertEqual(incident_id, fake_client.collection_ref.document_id)

        payload = fake_client.collection_ref.document_ref.payload
        self.assertEqual(incident_id, payload["incidentId"])
        self.assertEqual("distress", payload["type"])
        self.assertEqual("active", payload["status"])
        self.assertEqual("Room-2", payload["zoneId"])
        self.assertEqual("12", payload["personId"])
        self.assertEqual("Prolonged sitting detected", payload["note"])
        self.assertEqual(0.82, payload["confidence"])
        self.assertEqual("SERVER_TIMESTAMP", payload["createdAt"])


class DetectorEventPublisherTests(unittest.TestCase):
    def test_all_alert_types_publish_once_per_person_and_latch(self):
        publish = Mock()
        adapter = firebase_events.DetectorEventPublisher(publish=publish)
        person = types.SimpleNamespace(id=1, fall_alerted=True, sitting_alerted=True,
                                       isolation_alerted=True, wandering_alerted=True)
        adapter.publish_person(person)
        adapter.publish_person(person)
        self.assertEqual(publish.call_count, 4)
        self.assertEqual({c.kwargs["event_type"] for c in publish.call_args_list},
                         {"fall", "prolonged_sitting", "isolation", "wandering"})
        person.id = 2
        adapter.publish_person(person)
        self.assertEqual(publish.call_count, 8)

    def test_reset_latch_allows_new_incident(self):
        publish = Mock()
        adapter = firebase_events.DetectorEventPublisher(publish=publish)
        person = types.SimpleNamespace(id=1, sitting_alerted=True)
        adapter.publish_person(person)
        person.sitting_alerted = False
        adapter.publish_person(person)
        person.sitting_alerted = True
        adapter.publish_person(person)
        self.assertEqual(publish.call_count, 2)


if __name__ == "__main__":
    unittest.main()
