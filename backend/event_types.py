from enum import Enum

class EventType(str, Enum):
    FALL = "fall"
    SITTING_DISTRESS = "sitting distress"
    ISOLATION_DISTRESS = "isolation distress"
    WANDERING_DISTRESS = "wandering distress"