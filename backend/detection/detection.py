
import cv2
from ultralytics import YOLO
import time
from datetime import timedelta
from abc import ABC, abstractmethod
import os
import math
from threading import Lock, Event
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

from .person import Person
from .anonymise_frame import anonymise_event
from .detectors import FallDetector, WanderingDetector, IsolationDetector, SittingDetector
from ..event_types import AlertLevel
from .detection_types import DetectionResult
from .frame_context import FrameContext
from ..event_types import EventType
from ..detector_settings import DetectorSettingsService, apply_detector_settings


PLAYBACK_DELAY_MS = 60   # ~16 fps playback; raise to slow down further
KP_CONF = 0.5 # confidence level required for a keypoint coordinates to be valid 

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

class Program(ABC):
    def __init__(self, frame_lock: Lock, events=None, settings_service=None):
        if events is None:
            from ..event import event_service
            events = event_service
        self.events = events
        # Open the default camera. A laptop only has 1 webcame so use index 0. 
        # Use the ONNX version if the run time is slow. 
        dir = os.path.dirname(os.path.abspath(__file__))
        self.model = YOLO(os.path.join(dir, 'yolo26s-pose.pt'))
        self.frame_lock = frame_lock
        self.current_raw_frame = None
        self.current_annotated_frame = None 
        # Use the ONNX version if the run time is slow.
        self.bytetrack_yaml_path = os.path.join(dir, 'bytetrack.yaml')
        self.persons : dict[int, Person] = {}
        self.fall_detector = FallDetector()
        self.wandering_detector = WanderingDetector([("08:00", "20:00")]) # pass in normal hours in the form of tuples.
        self.isolation_detector = IsolationDetector(timedelta(hours=1))
        self.sitting_detector = SittingDetector(timedelta(hours=2))
        self.settings_service = settings_service if settings_service is not None else DetectorSettingsService()
        self._applied_settings = self.settings_service.get()
        self.apply_settings(self._applied_settings)
        self.completion_queue: Queue[str] = Queue()  # this Queue is used by the API thread too. Passes in events that have been marked completed in the database. 
        self.outstanding_events: dict[str, int] = {}  # Maps an outstanding event in the current session to its person. 
        self.event_executor = ThreadPoolExecutor(max_workers=2)  # Used when creating an event in the detection loop
        self.pending_events = {}  # person_id -> Future
        self.pending_results = {}
        self.deferred_events = {}

    def close(self):
        self.event_executor.shutdown(wait=True)
        self.process_pending_events(flush=True)

    @staticmethod
    def should_raise(event, active):
        if active is None:
            return True
        return (active['alert_level'] == AlertLevel.AMBER and event.alert_level == AlertLevel.RED
                or event.event_type == EventType.FALL and active['event_type'] != EventType.FALL)

    def submit_event(self, person_id, event, frame):
        self.pending_results[person_id] = event
        self.pending_events[person_id] = self.event_executor.submit(
            self.events.create_event, person_id=person_id,
            event_type=event.event_type, alert_level=event.alert_level, frame=frame)


    def refresh_detector_settings(self):
        settings = self.settings_service.take_pending_update()
        if settings is not None:
            self.apply_settings(settings)
            self._applied_settings = settings

    def apply_settings(self, settings):
        apply_detector_settings(settings, wandering=self.wandering_detector,
                                sitting=self.sitting_detector,
                                isolation=self.isolation_detector)

    @abstractmethod
    def get_cam(self):
        pass
    
    @abstractmethod 
    def is_video_mode(self):
        pass 

    def enqueue_event_completion(self, event_id: str):
        # This method is called by the API thread. 
        self.completion_queue.put(event_id)

    def process_event_completions(self):
        # this method is called by the detection thread and inside the continuous loop. 
        while True:
            try:
                event_id = self.completion_queue.get_nowait() # This will return an event if there has been one recently completed by the API thread.
            except Empty: # no events to be processed 
                break 

            try:
                person_id = self.outstanding_events.pop(event_id, None)

                if person_id is None: 
                    # Nothing to process. This event may have been from another running session. After the system restarded, it is not in the memory of the program anymore to be processed. 
                    continue

                person = self.persons.get(person_id)

                if person is not None and person.active_event_id is not None and person.active_event_id['id'] == event_id:
                    person.active_event_id = None # the 'active_event_id' attribute is cleared and events can be raised for the person again.
                    person.active_event_type = None

            finally:
                self.completion_queue.task_done()

    def process_pending_events(self, flush=False):
        for person_id, future in list(self.pending_events.items()):
            if not future.done():
                continue

            del self.pending_events[person_id]
            self.pending_results.pop(person_id, None)

            try:
                created_event = future.result()  # Already done, so won't wait.
            except Exception:
                self.deferred_events.pop(person_id, None)
                raise RuntimeError("Incident saving failed") from None

            self.persons[person_id].active_event_id = {
                "id": created_event.id,
                "event_type": created_event.event_type,
                "alert_level": created_event.alert_level,
            }
            self.outstanding_events[created_event.id] = person_id
            self.persons[person_id].active_event_type = created_event.event_type
            deferred = self.deferred_events.pop(person_id, None)
            if deferred and self.should_raise(deferred[0], self.persons[person_id].active_event_id):
                if flush:
                    # A brief fall must still be saved when the session stops during an amber write.
                    event, frame = deferred
                    self.events.create_event(person_id=person_id, event_type=event.event_type,
                                             alert_level=event.alert_level, frame=frame)
                else:
                    self.submit_event(person_id, *deferred)
            # when the event is marked as closed by the staff, it will be processed to clear the active_event_id attribute on the person.

    def get_priority_event(self, events: list[DetectionResult]):
        if not events:
            return None
        urgent_alerts = [] # These are alerts that are of alert level = 'red'
        non_urgent_alerts = [] # These are alerts that are of alert level = 'amber'
        for res in events:
            if res.alert_level == AlertLevel.RED.value:
                urgent_alerts.append(res)
            else:
                non_urgent_alerts.append(res)
        if urgent_alerts:
            return urgent_alerts[0]
        elif non_urgent_alerts:
            return non_urgent_alerts[0]
        return None


    def run(self, stop_event: Event):
        cam = self.get_cam()
        try:
            while not stop_event.is_set():
                ret, frame = cam.read()

                # Exit the loop if the frame was not captured or 'q' is pressed 
                if not ret or (cv2.waitKey(1) == ord('q')):
                    break

                with self.frame_lock: # variables are shared by the FrameStreamer method
                    self.current_raw_frame = frame.copy()
                    self.fps = self.get_fps() 

                if self.is_video_mode():
                    self.frame_index += 1 
                display_frame = self.process_frame(frame, self.get_frame_time())

                cv2.imshow('frame', display_frame)

                if self.is_video_mode():
                    # waitKey(0) blocks indefinitely, which is what gives us pause
                    key = cv2.waitKey(0 if self.paused else PLAYBACK_DELAY_MS) & 0xFF # we AND with 0xFF for bitwise AND only to preserve the lower 8 bits
                    if key == ord('q'):
                        break
                    elif key == ord(' '):
                        self.paused = not self.paused     # space toggles pause
                    elif key == ord('n'):
                        self.paused = True           # advance exactly one frame, then pause
        finally: # runs after an except or try block
            # Release the capture objects 
            cam.release()
            cv2.destroyAllWindows()
            self.close()

    def process_frame(self, frame, frame_time):
        self.refresh_detector_settings()
        self.process_pending_events()
        self.process_event_completions()
        frame_h, frame_w = frame.shape[0], frame.shape[1]
        annotated_frame = None

        fps_text = f"FPS: {int(self.fps)}"
        results = self.model.track(source=frame,
                            persist=True,
                            classes = [0], # only track class 0 = person,
                            device = 'cpu', # forces CPU regardless of GPU availability,
                            tracker=self.bytetrack_yaml_path,
                            )
        # results variable is a list of Results objects - one per frame/image. Since we are passing a single frame,
        # we can access the result by doing result[0].
        # The .cpu() call moves the tensor from GPU memory to CPU memory.
        if results and results[0].boxes.id is not None: # results seems to never be None. We can only tell if no person is in the frame through id attribute being None
            boxes = results[0].boxes.xyxy.numpy().astype(int)
            ids = results[0].boxes.id.numpy().astype(int).tolist() # a list of ids depending on the amount of people in the frame
            all_kp = results[0].keypoints.xy # list of keypoints depending on the amount of people in the frame
            all_conf = results[0].keypoints.conf
            people_in_frame = len(ids)
            annotated_frame = results[0].plot(
                boxes=True,      # draw bounding boxes
                kpt_line=True,   # draw skeleton lines between keypoints
                kpt_radius=5,    # keypoint dot size
                labels=True,     # draw class + track ID labels
            )
            for i, person_id in enumerate(ids):
                person = self.persons.get(person_id)  # obtain the person object
                if person is None:
                    person = Person(person_id)
                    self.persons[person_id] = person
                box = boxes[i]
                kp = all_kp[i]  # keypoints of a person
                confidence = results[0].keypoints.conf[i]
                self.update_person_properties(kp = kp, conf=confidence, box = box, frame_h=frame_h, frame_w= frame_w, person=person)
                frame_context = FrameContext(
                    frame=annotated_frame,
                    frame_time=frame_time,
                    occupancy=people_in_frame
                )
                fall_event = self.fall_detector.check_detector(ctx=frame_context, person = person)
                wandering_event = self.wandering_detector.check_detector(ctx=frame_context, person = person)
                isolation_event = self.isolation_detector.check_detector(ctx=frame_context, person = person)
                sitting_event = self.sitting_detector.check_detector(ctx=frame_context, person = person)

                event = self.get_priority_event([result for result in
                    (fall_event, wandering_event, isolation_event, sitting_event) if result is not None])
                active = person.active_event_id
                pending = self.pending_results.get(person_id)
                deferred = self.deferred_events.get(person_id)
                if deferred:
                    pending = deferred[0]
                if pending:
                    active = {'event_type': pending.event_type, 'alert_level': pending.alert_level}
                if event and self.should_raise(event, active):
                    snapshot = None
                    if getattr(self.events, 'stores_images', True):
                        snapshot = anonymise_event(frame=frame.copy(), all_keypoints=all_kp,
                            boxes=boxes, all_conf=all_conf, person_index=i)
                    if person_id in self.pending_events:
                        self.deferred_events[person_id] = (event, snapshot)
                    else:
                        self.submit_event(person_id, event, snapshot)

        # Write the fps to the frame.
        display_frame = frame if annotated_frame is None else annotated_frame
        cv2.putText(
                display_frame,
                fps_text,
                (10, 40),                   # Coordinates (X, Y)
                cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                1,                          # Font scale
                (0, 255, 0),                # Color (BGR format: Green)
                2,                          # Line thickness
                cv2.LINE_AA
            )
        with self.frame_lock: # variable is shared by the FrameStreamer method
            self.current_annotated_frame = display_frame.copy()

        return display_frame

    def update_person_properties(self, kp, conf, box, frame_h, frame_w, person: Person):
        self.extract_keypoints(kp, conf, person)
        person.box_coords = box
        self.fall_detector_metrics(person=person, frame_w=frame_w, frame_h=frame_h)

    def fall_detector_metrics(self, person:Person, frame_h, frame_w):
        MIN_TORSO_PX = 8            # Below this torso pixel length, using the torso for angles will be affected greatly by noise. 

        shoulder_centre = person._midpoint(L_SHOULDER, R_SHOULDER)
        hip_centre = person._midpoint(L_HIP, R_HIP)
        if shoulder_centre is not None and hip_centre is not None:
            # defining the torso length in the frame
            person.torso_len = math.hypot(hip_centre[0] - shoulder_centre[0],
                            hip_centre[1] - shoulder_centre[1])

            # defining the torso angle in the frame 
            if person.torso_len < MIN_TORSO_PX:
                person.torso_angle =  None  # torso_angle will be too noisy if the torso length is very small.
            else:
                person.torso_angle = person._angle_from_vertical(shoulder_centre, hip_centre)
        else: 
            person.torso_len = None      
            person.torso_angle = None          

        person.frame_h = frame_h
        person.frame_w = frame_w


    def extract_keypoints(self, kp, conf, person: Person):
        # This function updates the keypoints for a person every frame.
        keypoints = person.keypoints

        keypoints[NOSE] = kp[NOSE] if conf[NOSE] > KP_CONF else None

        keypoints[L_SHOULDER] = kp[L_SHOULDER] if conf[L_SHOULDER] > KP_CONF else None 
        keypoints[R_SHOULDER] = kp[R_SHOULDER] if conf[R_SHOULDER] > KP_CONF else None 

        keypoints[L_HIP] = kp[L_HIP] if conf[L_HIP] > KP_CONF else None 
        keypoints[R_HIP] = kp[R_HIP] if conf[R_HIP] > KP_CONF else None 

        keypoints[L_KNEE] = kp[L_KNEE] if conf[L_KNEE] > KP_CONF else None 
        keypoints[R_KNEE] = kp[R_KNEE] if conf[R_KNEE] > KP_CONF else None 

        keypoints[L_ANKLE] = kp[L_ANKLE] if conf[L_ANKLE] > KP_CONF else None 
        keypoints[R_ANKLE] = kp[R_ANKLE] if conf[R_ANKLE] > KP_CONF else None 

        return None

    @abstractmethod
    def get_fps(self):
        pass

    @abstractmethod
    def get_frame_time(self):
        pass

class VideoMode(Program):
    def __init__(self, frame_lock:Lock, filepath):
        super().__init__(frame_lock=frame_lock)
        self.cam = cv2.VideoCapture(filepath)
        video_fps = self.cam.get(cv2.CAP_PROP_FPS)
        if not video_fps or video_fps <= 0:
            video_fps = 30.0   # some files report 0
        self.fps = video_fps

        self.frame_index = -1 
        self.paused = False 

    def get_cam(self):
        return self.cam
    
    def get_fps(self):
        return self.fps

    def is_video_mode(self):
        return True

    def get_frame_time(self):
        return (self.frame_index/self.fps) # For video files

class CameraMode(Program):
    def __init__(self, frame_lock:Lock):
        super().__init__(frame_lock=frame_lock)
        self.cam = cv2.VideoCapture(0)
        self.fps = 0 
        self.prev_time = 0 
        self.new_time = 0
        self.time_delta = 0 

    def get_cam(self):
        return self.cam
    
    def calculate_fps(self):
        self.new_time = time.perf_counter()
        self.time_delta = self.new_time - self.prev_time
        self.fps = (1/self.time_delta) if self.time_delta > 0 else 0 
        self.prev_time = self.new_time

    def get_fps(self):
        self.calculate_fps()
        return self.fps

    def get_frame_time(self):
            return time.monotonic() # For video files
    
    def is_video_mode(self):
        return False
