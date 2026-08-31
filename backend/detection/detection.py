
import cv2
from ultralytics import YOLO
import time
from datetime import timedelta
from pathlib import Path
from abc import ABC, abstractmethod
import os
from os.path import join 
from person import Person
from detectors import FallDetector, WanderingDetector, IsolationDetector
from frame_context import FrameContext
import math

PLAYBACK_DELAY_MS = 60   # ~16 fps playback; raise to slow down further
KP_CONF = 0.5 # confidence level required for a keypoint coordinates to be valid 

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

class Program(ABC):
    def __init__(self):
        # Open the default camera. A laptop only has 1 webcame so use index 0. 
        # Use the ONNX version if the run time is slow. 
        dir = os.path.dirname(os.path.abspath(__file__))
        self.model = YOLO(os.path.join(dir, 'yolo26s-pose.pt'))
        # Use the ONNX version if the run time is slow.
        self.bytetrack_yaml_path = os.path.join(dir, 'bytetrack.yaml')
        self.persons : dict[int, Person] = {}
        self.fall_detector = FallDetector()
        self.wandering_detector = WanderingDetector([("08:00", "20:00")])
        self.isolation_detector = IsolationDetector(timedelta(hours=1))

    @abstractmethod
    def get_cam(self):
        pass
    
    @abstractmethod 
    def is_video_mode(self):
        pass 
    
    def run(self):
        cam = self.get_cam()
        model = self.model
                
        while True:
            ret, frame = cam.read()

            # Exit the loop if the frame was not captured or 'q' is pressed 
            if not ret or (cv2.waitKey(1) == ord('q')):
                break

            if self.is_video_mode():
                self.frame_index += 1 
            frame_h, frame_w = frame.shape[0], frame.shape[1]
            annotated_frame = None 

            self.fps = self.get_fps() 
            frame_time =  self.get_frame_time()  

            fps_text = f"FPS: {int(self.fps)}"
            results = model.track(source=frame, 
                                persist=True, 
                                classes = [0], # only track class 0 = person,
                                device = 'cpu', # forces CPU regardless of GPU availability,
                                tracker=self.bytetrack_yaml_path)
            # results variable is a list of Results objects - one per frame/image. Since we are passing a single frame, 
            # we can access the result by doing result[0]. 
            # The .cpu() call moves the tensor from GPU memory to CPU memory.
            if results and results[0].boxes.id is not None: # results seems to never be None. We can only tell if no person is in the frame through id attribute being None
                boxes = results[0].boxes.xyxy.numpy().astype(int)
                ids = results[0].boxes.id.numpy().astype(int).tolist() # a list of ids depending on the amount of people in the frame
                all_kp = results[0].keypoints.xy # list of keypoints depending on the amount of people in the frame
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
                    fall_frame = self.fall_detector.check_detector(ctx=frame_context, person = person)
                    wandering_frame = self.wandering_detector.check_detector(ctx=frame_context, person = person)
                    isolation_frame = self.isolation_detector.check_detector(ctx=frame_context, person = person)
                    annotated_frame = fall_frame # CHANGE this to another frame for testing other detectors
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
            cv2.imshow('frame', display_frame)

            if self.is_video_mode():
                # waitKey(0) blocks indefinitely, which is what gives us pause
                key = cv2.waitKey(0 if self.paused else PLAYBACK_DELAY_MS) & 0xFF # we AND qith 0xFF for bitwise AND only to preserve the lower 8 bits
                if key == ord('q'):
                    break
                elif key == ord(' '):
                    self.paused = not self.paused     # space toggles pause
                elif key == ord('n'):
                    self.paused = True           # advance exactly one frame, then pause
        # Release the capture objects 
        cam.release()
        cv2.destroyAllWindows()

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
    def __init__(self, filepath):
        super().__init__()
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
    def __init__(self):
        super().__init__()
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

# This code only runs if you execute the file directly
if __name__ == "__main__": 
    video_mode = True 
    if video_mode:
        script_dir = Path(__file__).parent
        #video_footage_path = join(script_dir, "..", "..", "..", "my test footage", "Falling backward 1.mp4")
        video_footage_path = join(script_dir, "distress detection", "sitting testing footage", "Test_2.avi")  # Replace the last argument in the join method with a different file name to test a different video. 
        if not os.path.isfile(video_footage_path):
            raise Exception(f"Testing video footage file path {video_footage_path} is incorrect.")
        video_fall_detector = VideoMode(video_footage_path)
        video_fall_detector.run()
    else:
        live_fall_detector = CameraMode()
        live_fall_detector.run()
