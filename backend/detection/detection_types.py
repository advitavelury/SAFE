from typing import NamedTuple
from ..event_types import EventType, AlertLevel

class DetectionResult(NamedTuple):
    event_type: EventType
    alert_level: AlertLevel