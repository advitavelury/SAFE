from enum import Enum
from datetime import datetime
from pydantic import BaseModel

class EventType(str, Enum):
    FALL = "fall"
    SITTING_DISTRESS = "sitting distress"
    ISOLATION_DISTRESS = "isolation distress"
    WANDERING_DISTRESS = "wandering distress"

class EventStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


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
