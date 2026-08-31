from person import Person
from datetime import datetime, time
from dataclasses import dataclass
from frame_context import FrameContext
import cv2

@dataclass(frozen=True)
class TimeWindow:
    """ A window of normal activity. Wraps midnight when start > end."""
    start: time
    end: time 

    def contains(self, t: time) -> bool:
        """ Indicates if the time 't' is contained in the valid time window"""
        if self.start <= self.end:
            return self.start <= t <= self.end 
        return t >= self.start or t <= self.end # e.g. 22:00 -> 6:00

    @classmethod
    def parse(cls, start: str, end:str) -> "TimeWindow":
        # normally a method in a class accepts an instance as the first argument (also known as self). 
        # Since we have the classmethod decorater applied to this method, we accept a class constructor as 
        # the first argument. Therefore, we can apply cls to create an instance of the class. The point is that 
        # you can call this method without having an instance yet. 
        return cls(time.fromisoformat(start), time.fromisoformat(end))

class WanderingDetector():
    def __init__(self, normal_hours):
        # accepts normal_hours in form of [("08:00", "20:00"), ...] or [TimeWindow(...), ...]. Time has to be in ISO format. 
        self.normal_hours = [w if isinstance(w, TimeWindow ) 
                            else TimeWindow.parse(w[0], w[1]) 
                            for w in normal_hours]

    def is_normal_time(self, now: time) -> bool:
        return any(w.contains(now) for w in self.normal_hours)        

    def check_detector(self, ctx: FrameContext, person: Person):
        box_midpoint = person.box_midpoint()
        frame = ctx.frame
        now = datetime.now().time()
        res = self.is_normal_time(now = now)
        if not res:
            person.wandering_alerted = True
            cv2.putText(
                        frame, 
                        f"Person {person.id} wandering detected.", 
                        box_midpoint, # Coordinates (X, Y)
                        cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                        1,                          # Font scale
                        (255, 0, 0),                # Color (BGR format: Blue)
                        2,                          # Line thickness
                        cv2.LINE_AA
                    )
        return frame 

            


