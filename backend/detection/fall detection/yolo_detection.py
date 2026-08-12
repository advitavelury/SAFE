from abc import ABC, abstractmethod
import cv2
from ultralytics import YOLO
import math
import numpy as np
import os
import time
from pathlib import Path
from os.path import join 


DOWN_HOLD_SECONDS = 0.2 #5.0        # persistence required to alert
RECOVERY_GRACE_SECONDS = 0.7   # sustained upright needed to cancel
KP_CONF = 0.5 # confidence level required for a keypoint coordinates to be valid 
# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

PLAYBACK_DELAY_MS = 60   # ~16 fps playback; raise to slow down further

class Person():
    def __init__(self, id):
        self.id = id 
        self.current_position = None
        self.down_since = None  # monotonic time DOWN first observed
        self.upright_since = None  # monotonic time upright first re-observed
        self.alerted = False  # if staff has been alerted


    def manage_person_posture(self, posture:str, video_time = None):
        now = time.monotonic() if video_time is None else video_time
        if self.current_position is None: # if the current position is None, we are starting the tracking for the first time
            self.current_position = posture
            return self.current_position
        if posture.lower() == "standing" or posture.lower() == "falling":
            if self.current_position == "lying down" and self.down_since is not None: # if the person has been identified as fallen down
                # only reset the state to standing if they have been standing for more than the recover grace period
                if self.upright_since is not None and abs(now-self.upright_since)>= RECOVERY_GRACE_SECONDS:
                    self.current_position = posture
                    self.down_since = None
                elif self.upright_since is None:
                    self.upright_since = now
                return 
            else:
                self.current_position = posture
        elif posture.lower() == "lying down":
            if self.current_position == "falling" and self.down_since is None:  # if only the person was falling and then lying down should we flag it as a fall
                self.down_since = now # start the down since timer 
            self.current_position = posture
        return self.current_position

    def alert_fall_event(self, video_time = None) -> bool: 
        # if a person has been "lying down" for more than 5 seconds, then alert a fall event
        # works under the assumptiont that the application is running at a minimum of 10 fps 
        now = time.monotonic() if video_time is None else video_time
        if self.current_position is None:
            return False 
        elif self.current_position.lower() == "lying down":
            if self.down_since is not None and abs(now - self.down_since) >= DOWN_HOLD_SECONDS:
                return True 
        return False

class FallDetector(ABC):
    def __init__(self):
        # Open the default camera. A laptop only has 1 webcame so use index 0. 
        # Shared model/config files live one level up, in backend/detection/,
        # so fall detection and distress detection can both use them.
        dir = os.path.dirname(os.path.abspath(__file__))
        detection_dir = os.path.dirname(dir)
        self.model = YOLO(os.path.join(detection_dir, 'yolo26n-pose.pt'))
        # Use the ONNX version if the run time is slow.
        self.bytetrack_yaml_path = os.path.join(detection_dir, 'bytetrack.yaml')
        
        self.person_posture = {}

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
            video_time =  self.get_video_time() if self.is_video_mode() else None  

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
                annotated_frame = results[0].plot(
                    boxes=True,      # draw bounding boxes
                    kpt_line=True,   # draw skeleton lines between keypoints
                    kpt_radius=5,    # keypoint dot size
                    labels=True,     # draw class + track ID labels
                )
                for i, person_id in enumerate(ids):
                    person = self.person_posture.get(person_id)  # obtain the person object
                    if person is None:
                        person = Person(person_id)
                        self.person_posture[person_id] = person
                    box = boxes[i]
                    box_midpoint = (int(box[0] + abs(box[0]-box[2])/2), int(box[1] + abs(box[1]-box[3])/2))
                    kp = all_kp[i]  # keypoints of a person
                    confidence = results[0].keypoints.conf[i]
                    posture = self.classify_posture(kp = kp, conf=confidence, box = box, frame_h=frame_h)
                    if posture is None:  # this could happen when the frame could not pick up valid keypoints
                        continue 
                    position = person.manage_person_posture(posture, video_time= video_time)
                    cv2.putText(
                                annotated_frame, 
                                position, 
                                box_midpoint, # Coordinates (X, Y)
                                cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                                1,                          # Font scale
                                (255, 0, 0),                # Color (BGR format: Blue)
                                2,                          # Line thickness
                                cv2.LINE_AA
                            )
                    alert = person.alert_fall_event(video_time=video_time)
                    if alert:
                        cv2.putText(
                                    annotated_frame, 
                                    f"Person {person_id} had a fall", 
                                    (30, 40),                   # Coordinates (X, Y)
                                    cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                                    1,                          # Font scale
                                    (0, 0, 255),                # Color (BGR format: RED)
                                    2,                          # Line thickness
                                    cv2.LINE_AA
                                )
                        print(f"Person {person_id} had a fall =========================================")
                        person.alerted = True 
                        return
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

    def _midpoint(self, kp, conf, i, j):
        """Midpoint of two keypoints, or None if either is unreliable."""
        # i - the COCO index for first key point 
        # j - the COCO index for the second key point 
        # kp[x] - gives (x,y) coordinates of keypoint with COCO index x 
        # conf[x] - confidence level of keypoint with COCO index x 
        if conf[i] < KP_CONF or conf[j] < KP_CONF:
            print(f"confidence level is too low {conf[i]} and {conf[j]}")
            return None
        return ((kp[i][0] + kp[j][0]) / 2.0, (kp[i][1] + kp[j][1]) / 2.0)

    def _angle_from_vertical(self, top, bottom):
        """0 deg = segment is vertical, 90 deg = segment is horizontal."""
        # top - keypoint usually located at the top in form (x,y)
        # bottom - keypoint usually located at the bottom in form (x,y)
        dy = abs(bottom[1] - top[1])
        dx = abs(bottom[0] - top[0])
        return abs(90.0 - math.degrees(math.atan2(dy, dx)))


    def classify_posture(self, kp, conf, box, frame_h,
                     standing_threshold=10, lying_threshold=60):
        # shoulder_centre and hip_centre are pixel coordinates but in the form (x, y). Pixel coordinates are normally (y,x) format. 
        shoulder_centre = self._midpoint(kp, conf, L_SHOULDER, R_SHOULDER)
        hip_centre = self._midpoint(kp, conf, L_HIP, R_HIP)
        if shoulder_centre is None or hip_centre is None:
            return None  # not enough information this frame - caller skips

        # Torso length is our scale unit: it is a rigid segment, so it tracks the
        # person's apparent size (i.e. their distance from the camera) without
        # changing much between postures.
        torso_len = math.hypot(hip_centre[0] - shoulder_centre[0],
                            hip_centre[1] - shoulder_centre[1])
        if torso_len < 1.0:
            return None  # degenerate - torso pointing straight at the camera

        torso_angle = self._angle_from_vertical(shoulder_centre, hip_centre)
        if torso_angle < standing_threshold:
            return "standing"
        if torso_angle <= lying_threshold:
            return "falling"

        # Torso looks horizontal. Corroborate with independent evidence before
        # committing to "lying down", since that is what starts the alert timer.
        votes, checks = 0, 0

        # 1. Legs horizontal too. Separates lying from bending over to pick
        #    something up, which also produces a horizontal torso.
        lower = self._midpoint(kp, conf, L_ANKLE, R_ANKLE)
        if lower is None:
            lower = self._midpoint(kp, conf, L_KNEE, R_KNEE)
        if lower is not None:
            checks += 1
            if self._angle_from_vertical(hip_centre, lower) > 50.0: # ideally the hips are in line with lower making the vertical angle 90
                votes += 1

        # 2. Silhouette is wider than it is tall. Comes from the detector rather
        #    than the pose model, so it fails independently of the keypoints.
        x1, y1, x2, y2 = box
        box_w, box_h = max(x2 - x1, 1), max(y2 - y1, 1)
        checks += 1
        if box_w / box_h > 1.0:
            votes += 1

        # 3. Shoulders sit low above the person's own foot line, in units of their
        #    own torso. Standing is roughly 2.5-3.0 torso lengths, sitting roughly 1.5 torso lengths,
        #    lying below 1.3 torso lengths. Skipped when the box is clipped by the bottom of the frame,
        #    because then y2 is not the real foot line.
        if y2 < frame_h - 5: # if y2 is too close to the bottom of the frame 
            checks += 1
            if (y2 - shoulder_centre[1]) / torso_len < 1.3:
                votes += 1

        # Need corroboration from at least two independent checks; if fewer than
        # two were evaluable, demand that every evaluable one agrees.
        required = 2 if checks >= 2 else checks
        if checks > 0 and votes >= required:
            return "lying down"
        return "falling"

    @abstractmethod
    def get_fps(self):
        pass

    # Check if a person is in the lying down position for a while 
    # The "falling" state can be a yellow event. If the person is lying for a prolonged amount of time raise the event to red
    # Work on the fps problem. Try to increase fps with even a lot of people. 
    # If fps problem is fixed, then use velocity to add more confidence to the falling state. 
            
class VideoMode(FallDetector):
    def __init__(self, filepath):
        super().__init__()
        self.cam = cv2.VideoCapture(filepath) #cv2.VideoCapture(0)
        print(self.cam)
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

    def get_video_time(self):
        return (self.frame_index/self.fps) # For video files

class CameraMode(FallDetector):
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

    def is_video_mode(self):
        return False

# This code only runs if you execute the file directly
if __name__ == "__main__": 
    script_dir = Path(__file__).parent
    video_footage_path = join(script_dir, "testing footage", "Fall test.mp4")  # Replace the last argument in the join method with a different file name to test a different video. 
    if not os.path.isfile(video_footage_path):
        raise Exception("Testing video footage file path is incorrect.")
    video_fall_detector = VideoMode(video_footage_path)
    video_fall_detector.run()


