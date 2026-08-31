from person import Person
from frame_context import FrameContext
import cv2

DOWN_HOLD_SECONDS = 0.2 #5.0        # persistence required to alert
RECOVERY_GRACE_SECONDS = 0.7   # sustained upright needed to cancel

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

class FallDetector():
    def __init__(self):
        self.person_posture : dict[int, str] = {}

    def alert_fall_event(self, person: Person, frame_time) -> bool: 
        # if a person has been "lying down" for more than 5 seconds, then alert a fall event
        # works under the assumptiont that the application is running at a minimum of 10 fps 
        person_id = person.id
        current_position = self.person_posture.get(person_id)
        if current_position is None:
            return False 
        elif current_position.lower() == "lying down":
            if person.down_since is not None and abs(frame_time - person.down_since) >= DOWN_HOLD_SECONDS:
                return True 
        return False
    
    def manage_person_posture(self, posture:str, person:Person, frame_time = None):
        person_id = person.id
        current_position = self.person_posture.get(person_id)
        if current_position is None: # if the current position is None, we are starting the tracking for the first time
            self.person_posture[person_id] = posture
            person.current_position = posture
            return posture
        if posture.lower() == "standing" or posture.lower() == "falling":
            if current_position == "lying down" and person.down_since is not None: # if the person has been identified as fallen down
                # only reset the state to standing if they have been standing for more than the recovery grace period time.
                if person.upright_since is not None:
                    print(f"the time since the person has stood up is {frame_time-person.upright_since}")
                if person.upright_since is not None and abs(frame_time-person.upright_since)>= RECOVERY_GRACE_SECONDS:
                    person.current_position = posture
                    person.down_since = None
                    self.person_posture[person_id] = posture
                elif person.upright_since is None:
                    person.upright_since = frame_time
            else:
                person.current_position = posture
                self.person_posture[person_id] = posture
        elif posture.lower() == "lying down":
            if current_position == "falling" and person.down_since is None:  # if only the person was falling and then lying down should we flag it as a fall
                person.down_since = frame_time # start the down since timer 
            person.upright_since = None # reset the upright since flag to None since the person as possibly fallen. 
            person.current_position = posture
            self.person_posture[person_id] = posture
        return self.person_posture[person_id]

    def check_detector(self, ctx: FrameContext, person: Person):
        frame = ctx.frame
        frame_time = ctx.frame_time
        posture = self.classify_posture(person=person)
        if posture is None:  # this could happen when the frame could not pick up valid keypoints
            return frame  
        position = self.manage_person_posture(posture, person=person, frame_time=frame_time)
        box_midpoint = person.box_midpoint()
        cv2.putText(
            frame, 
            position, 
            box_midpoint, # Coordinates (X, Y)
            cv2.FONT_HERSHEY_SIMPLEX,   # Font type
            1,                          # Font scale
            (255, 0, 0),                # Color (BGR format: Blue)
            2,                          # Line thickness
            cv2.LINE_AA
        )
        alert = self.alert_fall_event(person=person, frame_time=frame_time)
        if alert:
            cv2.putText(
                frame, 
                f"Person {person.id} had a fall", 
                (30, 40),                   # Coordinates (X, Y)
                cv2.FONT_HERSHEY_SIMPLEX,   # Font type
                1,                          # Font scale
                (0, 0, 255),                # Color (BGR format: RED)
                2,                          # Line thickness
                cv2.LINE_AA
            )
            print(f"Person {person.id} had a fall =========================================")
            person.fall_alerted = True
        return frame


    def classify_posture(self, person: Person,
                     standing_threshold=10, lying_threshold=60):
        # shoulder_centre and hip_centre are pixel coordinates but in the form (x, y). Pixel coordinates are normally (y,x) format. 
        shoulder_centre = person._midpoint(L_SHOULDER, R_SHOULDER)
        hip_centre = person._midpoint(L_HIP, R_HIP)
        if shoulder_centre is None or hip_centre is None:
            return None  # not enough information this frame - caller skips

        # Torso length is our scale unit: it is a rigid segment, so it tracks the
        # person's apparent size (i.e. their distance from the camera) without
        # changing much between postures.
        torso_len = person.torso_len
        x1, y1, x2, y2 = person.box_coords

        shoulder_width = person.get_shoulder_width()
        frontality_ratio = person.get_frontality_ratio() # frontality_ratio describes how oriented the person is in terms of facing forward. 
        
        facing_forward = frontality_ratio is not None and frontality_ratio > 0.5
        box_width = abs(x2-x1)
        box_height = abs(y2-y1)
        ratio_shoulder = abs(box_height/shoulder_width) if shoulder_width else None
        ratio_box = abs(box_height/box_width)
        
        print(f"Shoulder width is {shoulder_width}, torso len is {torso_len}, frontality ratio is {frontality_ratio}")

        
        torso_angle = person._angle_from_vertical(shoulder_centre, hip_centre)
        
        print(f"The torso angle is {torso_angle}")
        shoulder_baseline = None
        if ratio_shoulder is not None:
            shoulder_baseline = person.baseline("shoulder") # Get the median shoulder ratio
        box_baseline = person.baseline("box") # Get the median box ratio 

        box_current_vs_median = ratio_box/box_baseline if box_baseline else None
        shoulder_current_vs_median = ratio_shoulder/shoulder_baseline if (ratio_shoulder is not None and shoulder_baseline is not None) else None
        print(f"The current shoulder ratio is {ratio_shoulder} and median is {shoulder_baseline} and their ratio is {shoulder_current_vs_median}")
        print(f"The current box ratio is {ratio_box} and median is {box_baseline} and their ratio is { box_current_vs_median}")

        # CHECK IF THE PERSON IS STANDING 
        standing_checks, standing_votes = 0, 0 

        if torso_angle is not None :
            standing_checks += 1
            if torso_angle < standing_threshold:
                print("standing vote 1")
                standing_votes += 1
        if box_current_vs_median is not None and facing_forward:
            standing_checks += 1
            if box_current_vs_median > 0.80:
                print("standing vote 2")
                standing_votes += 1
        if shoulder_current_vs_median is not None and facing_forward:
            standing_checks += 1
            if shoulder_current_vs_median > 0.80:
                # if both the ratio_shoulder and ratio_box is reducing compared to their respective median, the person must be in the motion of falling 
                print("standing vote 3")
                standing_votes += 1
        if standing_checks > 0 and (standing_votes/standing_checks) > 0.5:
            if facing_forward:
                person.check_update_baselines(shoulder_ratio=ratio_shoulder, box_ratio=ratio_box)
            return "standing"

        # CHECK IF THE PERSON IS FALLING 
        #if torso_angle and standing_threshold <= torso_angle <= lying_threshold:
        #    # The person is possibly falling if his torso is not upright. 
        #    return "falling"


        # CHECK IF THE PERSON IS LYING DOWN
        # Torso looks horizontal. Corroborate with independent evidence before
        # committing to "lying down", since that is what starts the alert timer.
        lying_down_votes, lying_down_checks = 0, 0

        # 1. Legs horizontal too. Separates lying from bending over to pick
        #    something up, which also produces a horizontal torso.
        lower = person._midpoint(L_ANKLE, R_ANKLE)
        if lower is None:
            lower = person._midpoint(L_KNEE, R_KNEE)
        if lower is not None:
            lying_down_checks += 1
            if person._angle_from_vertical(hip_centre, lower) > 50.0: # ideally the hips are in line with lower making the vertical angle 90
                lying_down_votes += 1

        # 2. Silhouette is wider than it is tall. Comes from the detector rather
        #    than the pose model, so it fails independently of the keypoints.
        box_w, box_h = max(x2 - x1, 1), max(y2 - y1, 1)
        lying_down_checks += 1
        if box_w / box_h > 1.0:
            lying_down_votes += 1

        # 3. Shoulders sit low above the person's own foot line, in units of their
        #    own torso. Standing is roughly 2.5-3.0 torso lengths, sitting roughly 1.5 torso lengths,
        #    lying below 1.3 torso lengths. Skipped when the box is clipped by the bottom of the frame,
        #    because then y2 is not the real foot line.
        if y2 < person.frame_h - 5: # if y2 is not too close to the bottom of the frame 
            lying_down_checks += 1
            if (y2 - shoulder_centre[1]) / torso_len < 1.3:
                lying_down_votes += 1

        # 4. The torso angle is above the lying threshold. This means the person is laying flat across the camera (towards west or east)
        if torso_angle is not None:
            lying_down_checks += 1
            if torso_angle >= lying_threshold:
                lying_down_votes += 1
            
        # Need corroboration from at least two independent checks; if fewer than
        # two were evaluable, demand that every evaluable one agrees.
        required = min(3, lying_down_checks)
        print(f"required is {required} and votes is {lying_down_votes}")
        if lying_down_checks > 0 and lying_down_votes >= required:
            return "lying down"
        
        # All the checks above will fail if the person is falling forwards/backwards. Check the ratio_box and ratio_shoulder compared to the median
        compression_votes = 0 

        if box_current_vs_median is not None and box_current_vs_median < 0.68:
            print("compression vote 1")
            compression_votes += 2
        if shoulder_current_vs_median is not None and shoulder_current_vs_median < 0.80:
            print("compression vote 2")
            compression_votes += 1
        #if frontality_ratio is not None and frontality_ratio >= 0.7:
        #    print("compression vote 3")
        #    compression_votes += 1
        if hip_centre[1] - shoulder_centre[1] < 0:  # This is when the person is falling forwards (out of the camera).
            print("compression vote 4")
            compression_votes += 1
        print(f"compression votes are {compression_votes}")
        if compression_votes >= 2:
            return "lying down"
                
        return "falling"  # Default to "falling" if none of the other states are verified.

            

