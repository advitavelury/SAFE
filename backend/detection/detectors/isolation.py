from person import Person
from frame_context import FrameContext
from overlay import draw_label
from datetime import timedelta

CONSECUTIVE_FRAMES_THRESHOLD = 10 # The number of frames required with occupancy more than 1 to reset the isolation timer of a person.

# Label rendering. LABEL_Y_OFFSET staggers this detector's per-person label
# below the box midpoint so it doesn't overlap the other detectors' labels -
# see fall.py, wandering.py, sitting.py for their own offsets.
LABEL_FONT_SCALE = 0.5
LABEL_THICKNESS = 1
LABEL_Y_OFFSET = 40
LABEL_COLOR = (204, 0, 204)   # BGR: magenta/purple
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
        label_point = (box_midpoint[0], box_midpoint[1] + LABEL_Y_OFFSET)
        draw_label(frame, f"Isolation time {time_alone:.1f}s.", label_point,
                   LABEL_FONT_SCALE, LABEL_COLOR, LABEL_THICKNESS)
        return frame