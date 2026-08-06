import cv2
from ultralytics import YOLO
import math
import numpy as np
import os
import time 
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

class FallDetector():
    def __init__(self):
        # Open the default camera. A laptop only has 1 webcame so use index 0. 
        self.cam = cv2.VideoCapture(0)
        self.model = YOLO('yolov8n.pt')
        dir = os.path.dirname(os.path.abspath(__file__))
        self.bytetrack_yaml_path = os.path.join(dir, 'bytetrack.yaml')
        mp_model_path = os.path.join(dir, 'pose_landmarker_lite.task')
        base_options = python.BaseOptions(model_asset_path=mp_model_path)
        self.options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_poses = 1, # Since we crop each person in a frame, we only need to detect 1 pose per call.
            min_pose_detection_confidence=0.5, 
            min_tracking_confidence=0.5
        )
        # MediaPipe's standard 33-landmark skeleton topology (static index pairs).
        self.POSE_CONNECTIONS = [
            (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
            (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
            (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
            (11, 23), (12, 24), (23, 24),
            (23, 25), (24, 26), (25, 27), (26, 28), (27, 29), (28, 30),
            (29, 31), (30, 32), (27, 31), (28, 32),
        ]  # Tells us how to draw lines between different joints. E.g. (0,1) means draw a line between the landmark 
        # point 0 (nose) and landmark point 1 (left eye)
        self.fps = 0 
        self.person_posture = {}
    
    def run(self):
        cam = self.cam
        model = self.model
        prev_time = 0 
        new_time = 0 
        with vision.PoseLandmarker.create_from_options(self.options) as landmarker:
            while True:
                ret, frame = cam.read()

                # Exit the loop if the frame was not captured or 'q' is pressed 
                if not ret or (cv2.waitKey(1) == ord('q')):
                    break
                
                new_time = time.perf_counter()
                time_delta = new_time - prev_time
                self.fps = 1/time_delta if time_delta > 0 else 0 
                prev_time = new_time

                fps_text = f"FPS: {int(self.fps)}"
                results = model.track(source=frame, 
                                    persist=True, 
                                    classes = [0], # only track class 0 = person,
                                    device = 'cpu', # forces CPU regardless of GPU availability
                                    tracker=self.bytetrack_yaml_path)
                # results variable is a list of Results objects - one per frame/image. Since we are passing a single frame, 
                # we can access the result by doing result[0]. 
                # The .cpu() call moves the tensor from GPU memory to CPU memory.
                if results and results[0].boxes.id is not None: # results seems to never be None. We can only tell if no person is in the frame through id attribute being None
                    boxes = results[0].boxes.xyxy.numpy().astype(int)
                    ids = results[0].boxes.id.numpy().astype(int)
                    all_kp = self.get_keypoints(landmarker= landmarker, frame=frame, boxes=boxes, ids=ids, draw=True)
                    for id, kp in all_kp.items():
                        left_shoulder, right_shoulder = kp[11], kp[12] # kp[11] will give the (x,y) coordinates of the left shoulder. 
                        left_hip, right_hip = kp[23], kp[24]
                        shoulder_centre = ((left_shoulder[0] + right_shoulder[0])/2, (left_shoulder[1] + right_shoulder[1])/2)
                        hip_centre = ((left_hip[0] + right_hip[0])/2, (left_hip[1] + right_hip[1])/2)
                        torso_angle = self.calculate_angle(shoulder_centre=shoulder_centre, hip_centre=hip_centre)
                        print(f"The angle of person {id} is {torso_angle}")
                        posture = self.classify_posture(torso_angle=torso_angle)
                        if posture == "falling":
                            print(f"Person {id} had a fall =========================================")
                            break 
                        self.person_posture[id] = posture

                # Write the fps to the frame.    
                cv2.putText(
                        frame, 
                        fps_text, 
                        (10, 40),                   # Coordinates (X, Y)
                        cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                        1,                          # Font scale
                        (0, 255, 0),                # Color (BGR format: Green)
                        2,                          # Line thickness
                        cv2.LINE_AA
                    )
                cv2.imshow('frame', frame)
        # Release the capture objects 
        cam.release()
        cv2.destroyAllWindows()

    def get_keypoints(self, landmarker, frame, boxes, ids, draw=False):
        person_kps = {}
        for box, id in zip(boxes, ids):
            x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
            person_bbox = frame[y1:y2, x1:x2]

            rgb = cv2.cvtColor(person_bbox, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            pose_result = landmarker.detect(mp_image) 
            # pose_result is an object. What we are concerned with is pose_result.pose_landmarks
            # pose_result.pose_landmarks is an array where each index is the landmark of each person detected. 


            if pose_result.pose_landmarks:
                landmark = pose_result.pose_landmarks[0] # Since we only expect one person's landmarks, we get the 0th index.
                # landmark is a list of 33 landmark keypoint objects.
                # Each object has the properties of .x and .y. These are normalised coordinates from 0.0 to 1.0
                # For example landmark[0].x could be 0.5 which means the nose is halfway horizontally in the image

                h, w = person_bbox.shape[:2]
                points = [(int(lm.x*w), int(lm.y*h)) for lm in landmark]

                person_kps[id] = points
                if draw:
                    for px, py in points:
                        cv2.circle(person_bbox, (px,py), 3, (0, 255, 0), -1)
                    for a,b in self.POSE_CONNECTIONS:
                        cv2.line(person_bbox, points[a], points[b], (255, 0, 0), 2)

                    frame[y1:y2, x1:x2] = person_bbox

            if draw:
                cv2.rectangle(img=frame, pt1=(x1, y1), 
                                pt2=(x2, y2), color=(255, 0, 255), 
                                thickness=2)
                cv2.putText(img=frame, text=f'Id = {id}', 
                            org=(x1, y1), 
                            fontFace= cv2.FONT_HERSHEY_SIMPLEX, 
                            fontScale=1, color= (255,0,255), 
                            thickness=2)
        return person_kps
    
    def calculate_angle(self, shoulder_centre, hip_centre):
        # shoulder_centre and hip_centre are pixel coordinates but in the form (x, y). Pixel coordinates are normally (y,x) format. 
        dy = abs(hip_centre[1] - shoulder_centre[1])  # The hip y coordinate is higher than shoulder y coordinate. Apply abs() to always keep the angle in first quadrant. 
        dx = abs(shoulder_centre[0] - hip_centre[0])
        angle = math.atan2(dy, dx)  # Angle between shoulder-hip line and x-axis
        return abs(90 - np.degrees(angle))  # Absolute angle between shoulder-hip line and vertical axis

    def classify_posture(self, torso_angle, standing_threshold=10, lying_threshold = 60):
        if torso_angle < standing_threshold:
            return "standing"
        if torso_angle > lying_threshold:
            return "lying down"
        else:
            return "falling"

            


# This code only runs if you execute the file directly
if __name__ == "__main__":
    fall_detector = FallDetector()
    fall_detector.run()


