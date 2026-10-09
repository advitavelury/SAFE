"""Persistent settings shared by the API and detection thread in one process."""
from datetime import time
from queue import Empty, SimpleQueue
from threading import RLock

from firebase_admin import firestore
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalHoursWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def valid_clock_time(cls, value):
        # Keep clock times unambiguous: HH:MM, without dates or offsets.
        if len(value) != 5 or value[2] != ":":
            raise ValueError("Use HH:MM in 24-hour time.")
        try:
            parsed = time.fromisoformat(value)
        except ValueError:
            raise ValueError("Use HH:MM in 24-hour time.") from None
        if parsed.strftime("%H:%M") != value:
            raise ValueError("Use HH:MM in 24-hour time.")
        return value


class DetectorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False) # configures how Pydantic validates and handles model objects.
    # extra='forbid': Reject fields we haven't defined. 
    # frozen=True : Prevent assigning new values to an existing model's attribute.
    # allow_inf_nan=False : Reject numeric infinity and NaN values. 
    wandering_normal_hours: tuple[NormalHoursWindow, ...] = Field(
        default=(NormalHoursWindow(start="08:00", end="20:00"),),
        min_length=1, max_length=24,
    )
    sitting_seconds: float = Field(default=7200, gt=0, le=604800, strict=True)
    isolation_seconds: float = Field(default=3600, gt=0, le=604800, strict=True)
    sitting_break_seconds: float = Field(default=60, gt=0, le=3600, strict=True)
    sitting_warning_fraction: float = Field(default=0.5, gt=0, lt=1, strict=True)


class DetectorSettingsPatch(DetectorSettings):
    """Only explicitly supplied fields are merged; nulls and unknown keys fail."""


class SettingsUnavailable(RuntimeError):
    pass


class DetectorSettingsService:
    def __init__(self, db=None):
        self._db = db
        self._lock = RLock() # The RLock allows a lock to be aquired again if it is within the same thread. However, different threads cannot aquire the same lock. 
        # Example:
        #Thread A enters update(): acquires lock, count = 1
        #Thread A enters get():    acquires again, count = 2
        #Thread A leaves get():    releases once, count = 1
        #Thread A leaves update(): releases again, count = 0
        #Thread B can now enter.
        self._settings = None
        self._updates: SimpleQueue[DetectorSettings] = SimpleQueue()

    def _document(self):
        if self._db is None:
            from .firebase_config import production_db
            self._db = production_db
        return self._db.collection("settings").document("detectors")

    def get(self) -> DetectorSettings:
        with self._lock:
            if self._settings is None:
                try:
                    snapshot = self._document().get(timeout=5)
                    self._settings = (DetectorSettings.model_validate(
                        snapshot.to_dict()["thresholds"]
                    ) if snapshot.exists else DetectorSettings())
                except Exception:
                    raise SettingsUnavailable("Unable to load detector settings.") from None
            return self._settings

    def update(self, patch: DetectorSettingsPatch, *, updated_by: str) -> DetectorSettings:
        with self._lock:
            current = self.get()
            # model_dump converts a model object into a dictionary. 
            changes = patch.model_dump(mode="json", exclude_unset=True) # The 'exclude_unset=True' leaves out fields that the admin didn't explicitly supply. Therefore, though fields have default values.
            # the exclude_unset=True will make sure these fields are left out. 
            if not changes:
                return current
            # model_validate function accepts data and checks it against the model's fields and validation rules. It is inherited from Pydantic's BaseModel.
            updated = DetectorSettings.model_validate({ # combine dictionary values from existing settings , with the changes requested.
                **current.model_dump(mode="json"), # returns a dictionary.
                **changes, # Since changes come second, its values override matchine current values. 
            })
            try:
                self._document().set({
                    "thresholds": updated.model_dump(mode="json"),
                    "updated_by": updated_by,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }, timeout=5)
            except Exception:
                raise SettingsUnavailable("Unable to save detector settings.") from None
            # Publish only after persistence succeeds. Snapshots are immutable.
            self._settings = updated
            self._updates.put(updated)
            return updated

    def take_pending_update(self) -> DetectorSettings | None:
        """One detection thread consumes updates without taking the storage lock."""
        latest = None
        while True:
            try:
                latest = self._updates.get_nowait()
            except Empty:
                return latest


def apply_detector_settings(settings, *, wandering, sitting, isolation):
    """Called at startup and by the detection thread when settings change."""
    from .detection.detectors.wandering import TimeWindow
    wandering.normal_hours = [TimeWindow.parse(w.start, w.end)
                              for w in settings.wandering_normal_hours]
    sitting.threshold_seconds = settings.sitting_seconds
    sitting.break_seconds = settings.sitting_break_seconds
    sitting.warning_fraction = settings.sitting_warning_fraction
    isolation.threshold_seconds = settings.isolation_seconds
