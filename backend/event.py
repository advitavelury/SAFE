from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Literal
import cv2
from firebase_config import production_db, production_bucket

class Event(BaseModel):
    id: str
    event_type: Literal["fall", "distress"]
    timestamp: datetime
    image_url: str
    image_path: str

class EventService:

    def __init__(self, db, bucket):
        self.db = db
        self.bucket = bucket

    def create_event(self, event_type: str, timestamp:datetime, frame) -> Event:
        # 1. Generate event ID
        doc_ref = self.db.collection("events").document()
        event_id = doc_ref.id
        # 2. Convert OpenCV frame to JPEG
        success, encoded_image = cv2.imencode(".jpg", frame)

        if not success:
            raise Exception("Could not encode the event image")

        image_bytes = encoded_image.tobytes()

        # 3. Upload JPEG to Firebase Storage
        image_path = f"events/{event_id}.id"
        blob = self.bucket.blob(image_path)
        blob.upload_from_string(
            image_bytes,
            content_type="image/jpeg"
        )

        # 4. Save event metadata to Firestore
        doc_ref.set(
            {
                "event_type": event_type,
                "timestamp": timestamp, 
                "image_path": image_path
            }
        )
        # 5. Return Event
        return Event(
            id=event_id,
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
            event_type=data["event_type"],
            timestamp=data["timestamp"],
            image_path=image_path,
            image_url=image_url
        )

    def get_events(self):
        pass

    def delete_event(self, event_id: str):
        pass

event_service = EventService(db=production_db, bucket=production_bucket)