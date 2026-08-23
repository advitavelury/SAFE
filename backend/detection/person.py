import time
from collections import deque
import statistics
import math

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

class FallDetectorMetrics():
    def __init__(self):
        # metrics used by FallDetector
        self.current_position = None
        self.down_since = None  # monotonic time DOWN first observed.
        self.upright_since = None  # monotonic time upright first re-observed.
        self.alerted = False  # if staff has been alerted.
        self.ratios_shoulder = deque(maxlen=30) # box_h/shoulder_w.
        self.ratios_box = deque(maxlen=30)  # box_h/box_w.
        self.torso_len = None # The length of the persons torso in the frame.
        self.torso_angle = None # The angle of the persons torso in the frame. 
        self.frame_h = None     # The height of the frame. 
        self.frame_w = None     # The width of the frame. 
        
    def get_shoulder_width(self):
        MIN_SHOULDER_PX = 10.0      # Minimum shoulder width distance. Anything below this is where noise dominates. 
        kp = self.keypoints
        dx = float(kp[L_SHOULDER][0] - kp[R_SHOULDER][0])
        dy = float(kp[L_SHOULDER][1] - kp[R_SHOULDER][1])
        width =  math.hypot(dx, dy)
        if width < MIN_SHOULDER_PX:
            return None
        return width

    def get_frontality_ratio(self):        
        MIN_FRONTALITY = 0.5        # Minimum ratio of shoulder_w/torso_len to verify if the person is standing facing the front
        shoulder_width = self.get_shoulder_width()
        torso_len = self.torso_len
        if torso_len < 1e-6 or shoulder_width is None:
            return None
        frontality_ratio = shoulder_width/torso_len
        if frontality_ratio >= MIN_FRONTALITY:
            return frontality_ratio
        return None 

    def baseline(self, which):
        q = self.ratios_shoulder if which == "shoulder" else self.ratios_box
        return statistics.median(q) if len(q) >= 10 else None

    def check_update_baselines(self, shoulder_ratio = None, box_ratio = None):
        if shoulder_ratio is None and box_ratio is None:
            return 
        if shoulder_ratio is not None:
            base = self.baseline("shoulder")
            if base is None:
                # This means we haven't accumulated 10 values yet in the queue. Accept plausible values 
                if 2.0 < shoulder_ratio < 6.0:
                    self.ratios_shoulder.append(shoulder_ratio)
            elif 0.85 * base < shoulder_ratio < 1.2 * base: # If the ratio abnormally low or high, it must mean the person is not standing anymore. 
                self.ratios_shoulder.append(shoulder_ratio)

        if box_ratio is not None:
            base = self.baseline("box")
            if base is None:
                # This means we haven't accumulated 10 values yet in the queue. Accept plausible values 
                if 2.0 < box_ratio < 6.0:
                    self.ratios_box.append(box_ratio)
            elif 0.8 * base < box_ratio <  1.20 * base: # If the ratio abnormally low or high, it must mean the person is not standing anymore. 
                self.ratios_box.append(box_ratio)

class Person(FallDetectorMetrics):
    def __init__(self, id):
        self.id = id 
        self.keypoints = {} # stores keypoints where the key is the COCO index and value is the tensor object.
        self.box_coords = None # Box coordinates are in the form (x1, y1, x2, y2). Defines the top left and bottom right corner of the box surrounding the person. 
        super().__init__() 

    def box_midpoint(self):
        box_midpoint = None
        if self.box_coords is not None:
            x1, y1, x2, y2 = self.box_coords
            box_midpoint = (int(x1 + abs(x1-x2)/2), int(y1 + abs(y1-y2)/2))
        return box_midpoint
    
    def _midpoint(self, i, j):
        """Midpoint of two keypoints, or None if either is unreliable."""
        # i - the COCO index for first key point 
        # j - the COCO index for the second key point 
        # kp[x] - gives (x,y) coordinates of keypoint with COCO index x 
        # conf[x] - confidence level of keypoint with COCO index x 
        kp = self.keypoints
        if kp[i] is None or kp[j] is None:
            print("One of the keypoints is not reliable to find the midpoint.")
            return None
        x_midpoint = float((kp[i][0] + kp[j][0]) / 2.0)
        y_midpoint = float((kp[i][1] + kp[j][1]) / 2.0)
        return (x_midpoint, y_midpoint)

    def _angle_from_vertical(self, top, bottom):
        """0 deg = segment is vertical, 90 deg = segment is horizontal."""
        # top - keypoint usually located at the top in form (x,y)
        # bottom - keypoint usually located at the bottom in form (x,y)
        dy = abs(bottom[1] - top[1])
        dx = abs(bottom[0] - top[0])
        return abs(90.0 - math.degrees(math.atan2(dy, dx)))      
