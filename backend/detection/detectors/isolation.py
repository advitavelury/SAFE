import cv2 
from person import Person
from frame_context import FrameContext
from datetime import timedelta

CONSECUTIVE_FRAMES_THRESHOLD = 10 # The number of frames required with occupancy more than 1 to reset the isolation timer of a person. 
class IsolationDetector():
    def __init__(self, threshold_time: timedelta):
        self.threshold_seconds = threshold_time.total_seconds()
        self.person_alone_since = {} # key is the person id and value is time when person started being alone.
        self.consecutive_company_frames = {} # key is the person id and value is the number of frames where the person has not been alone. 

    def reset_isolation_status(self, person: Person):
        person_id = person.id
        alone_since = self.person_alone_since.get(person_id)
        if alone_since is not None:
            frames_with_occupants = self.consecutive_company_frames.get(person_id, 0) + 1
            self.consecutive_company_frames[person_id] = frames_with_occupants
            if frames_with_occupants  > CONSECUTIVE_FRAMES_THRESHOLD:
                del self.person_alone_since[person_id]
                del self.consecutive_company_frames[person_id]

    def check_detector(self, ctx: FrameContext, person: Person):
        box_midpoint = person.box_midpoint()
        frame_time = ctx.frame_time
        people_in_frame = ctx.occupancy
        frame = ctx.frame
        if people_in_frame > 1:
            self.reset_isolation_status(person)
            return frame
        else:
            alone_since = self.person_alone_since.get(person.id, None)
            self.consecutive_company_frames.pop(person.id, None) # clear the consecutive frames.
        if alone_since is None:
            alone_since = frame_time
            self.person_alone_since[person.id] = alone_since
        time_alone = frame_time - alone_since
        if time_alone > self.threshold_seconds:
            person.isolation_alerted = True 
        cv2.putText(
                    frame, 
                    f"Isolation time {time_alone:.1f}s.", 
                    box_midpoint, # Coordinates (X, Y)
                    cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                    1,                          # Font scale
                    (255, 0, 0),                # Color (BGR format: Blue)
                    2,                          # Line thickness
                    cv2.LINE_AA
                )
        return frame