from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from firebase_admin import firestore
import cv2
from .firebase_config import production_db, production_bucket
from .event_types import EventType, EventStatus

class Event(BaseModel):
    id: str
    person_id: int
    status: EventStatus = EventStatus.OPEN
    completed_at: datetime | None = None 
    completed_by: str | None = None 
    event_type: EventType
    timestamp: datetime
    image_url: str | None = None
    image_path: str

class EventService:

    def __init__(self, db, bucket):
        self.db = db
        self.bucket = bucket

    def create_event(self, person_id:int, event_type: EventType, frame, timestamp:datetime|None = None) -> Event:

        event_type = EventType(event_type) # validate the event type before saving

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # 1. Generate event ID
        doc_ref = self.db.collection("events").document()
        event_id = doc_ref.id
        # 2. Convert OpenCV frame to JPEG
        success, encoded_image = cv2.imencode(".jpg", frame)

        if not success:
            raise Exception("Could not encode the event image")

        image_bytes = encoded_image.tobytes()

        # 3. Upload JPEG to Firebase Storage
        image_path = f"events/{event_id}.jpeg"
        blob = self.bucket.blob(image_path)
        blob.upload_from_string(
            image_bytes,
            content_type="image/jpeg"
        )

        # 4. Save event metadata to Firestore
        doc_ref.set(
            {
                "person_id": person_id,
                "event_type": event_type.value,
                "status": EventStatus.OPEN,
                "timestamp": timestamp, 
                "image_path": image_path
            }
        )
        # 5. Return Event
        return Event(
            id=event_id,
            person_id=person_id,
            event_type=event_type,
            timestamp=timestamp,
            image_path=image_path,
        )

    def get_event(self, event_id: str):
        doc_ref = self.db.collection("events").document(event_id)
        doc = doc_ref.get()

        if not doc.exists:
            return None

        data = doc.to_dict()

        image_path = data["image_path"]

        blob = self.bucket.blob(image_path) # a python object representing a particular element inside the bucket. 

        image_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET"
        )

        return Event(
            id=event_id,
            person_id=(data["person_id"]),
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            image_path=image_path,
            image_url=image_url,
            status= EventStatus(data.get("status", EventStatus.OPEN.value)), 
            completed_by=data.get("completed_by"),
            completed_at=data.get("completed_at"),
        )

    def complete_event(self, event_id : str, completed_by: str ):
        doc_ref = self.db.collection("events").document(event_id) # The address of the document

        @firestore.transactional
        def update_completion(transaction):
            doc = doc_ref.get(transaction=transaction) # fetching the data from the address of the document. 

            if not doc.exists:
                return None

            data = doc.to_dict()

            # A repeated request leaves the original completion unchanged.
            if data.get("status") == EventStatus.CLOSED.value:
                return {"id": doc.id, **data}

            updates = {
                "status": EventStatus.CLOSED.value,
            }

            # Preserve any completion details already present.
            if data.get("completed_by") is None:
                updates["completed_by"] = completed_by

            if data.get("completed_at") is None:
                updates["completed_at"] = datetime.now(timezone.utc)

            transaction.update(doc_ref, updates)

            # Update our local dictionary for the response too.
            data.update(updates)
            return {"id": doc.id, **data}

        return update_completion(self.db.transaction())

    def get_events(self):
        pass

    def delete_event(self, event_id: str):
        pass

event_service = EventService(db=production_db, bucket=production_bucket)