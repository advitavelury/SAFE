from abc import ABC, abstractmethod
import cv2
from ultralytics import YOLO
import math
import numpy as np
import os
import time
from pathlib import Path
from os.path import join


# =============================================================================
# POSTURE CLASSIFICATION - design notes
#
# A person is "sitting" when their knees are at roughly hip height rather than
# a full femur below their hips. That vertical relationship is the core of the
# whole classifier, and it was chosen deliberately over the more obvious tests
# (thigh angle, knee angle) for one reason:
#
#   Rotating a person about their own vertical axis changes their x
#   coordinates but leaves their y coordinates alone.
#
# So the vertical hip->knee drop survives the camera azimuth changes that
# destroy every angle measured in the image plane. A seated person angled
# towards the camera has a thigh that projects to a near-vertical stub - the
# thigh angle says "standing", the knee drop still says "sitting".
#
# The angle tests are kept, but as CORROBORATION only, applied when the limb
# projects long enough to be trustworthy. This ordering is what stops the
# classifier from measuring the camera instead of the pose.
#
# EVENT TIMING - design notes
#
# Every timed state in this file follows the same rule, learned the hard way:
# an event must be confirmed by a sustained NUMBER OF OBSERVATIONS as well as
# a sustained INTERVAL OF TIME. Testing elapsed time alone lets two stray
# frames either side of a dropout satisfy a one-second threshold on the
# strength of two frames of evidence. Every threshold below therefore comes in
# pairs: a _SECONDS and an _OBSERVATIONS constant.
# =============================================================================

DOWN_HOLD_SECONDS = 0.2        # persistence required to alert
RECOVERY_GRACE_SECONDS = 0.7   # sustained upright needed to cancel a fall
KP_CONF = 0.5                  # confidence required for a keypoint to be valid

# Consecutive upright readings needed alongside RECOVERY_GRACE_SECONDS before
# a fall is treated as recovered. Without this, one stray "standing" frame, a
# dropout, and one more stray frame cancels a real fall.
MIN_UPRIGHT_OBSERVATIONS = 5

# --- Prolonged sitting ---------------------------------------------------
# NOTE: 10 seconds is a TESTING value. Clinically the concern is immobility
# over tens of minutes to hours - pressure injury risk, missed meals, someone
# who cannot get themselves back up. A 10 second alert in a real ward would
# fire on essentially every resident continuously. Raise this to something
# like 1800 (30 min) before any real deployment or demo with clinical staff.
SITTING_HOLD_SECONDS = 3.0

# Consecutive NON-sitting readings needed to break a sitting streak. Same
# reasoning as MIN_UPRIGHT_OBSERVATIONS: without it, a single misclassified
# frame at t=9.8s silently restarts a ten second timer and the alert never
# fires. Unreadable frames do not count either way - they never reach here.
SITTING_BREAK_OBSERVATIONS = 5

# Lower floor for the sitting tests specifically. 0.5 is punishing on small,
# dim or backlit footage; the geometry tests below reject bad poses anyway.
KP_CONF_SITTING = 0.30

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

PLAYBACK_DELAY_MS = 60   # ~16 fps playback; raise to slow down further

# --- PRIMARY sitting test -----------------------------------------------
# Vertical hip->knee gap, in units of the person's own torso length.
#   standing -> ~1.0-1.2 (knee a full femur below the hip)
#   sitting  -> ~0.0-0.4 (knee at roughly hip height)
# Only an upper bound is applied: a reclining person with their feet up puts
# the knee ABOVE the hip, which is negative, and is still seated.
KNEE_DROP_SEATED_MAX = 0.55

# --- Corroborating angle tests (used only when the limb projects long) ---
# Hip angle = shoulder-hip-knee. Note how far this swings with slouch, which
# is why the band is so wide:
#   standing ~180, upright sitting ~90, hunched-forward sitting ~30
HIP_BENT_MIN, HIP_BENT_MAX = 25.0, 130.0
# Knee angle = hip-knee-ankle. Nominally 90 when seated.
KNEE_BENT_MIN, KNEE_BENT_MAX = 45.0, 140.0

# A limb shorter than this fraction of the torso is foreshortened (pointing at
# or away from the camera), so any ANGLE derived from it is noise. The knee
# drop is still valid, so this suppresses the angle tests only.
MIN_SEGMENT_RATIO = 0.30

# Torso gate. Set at 75 rather than 50 because it no longer has to reject
# "bent over at the waist" - the knee drop does that, since a bent-over
# stander still has their knees a full femur below their hips. All this has
# to exclude now is a genuinely horizontal person, which is what separates
# sitting from lying curled on one side (identical leg geometry, different
# torso).
TORSO_FOLDED_MAX = 75.0

# A lying person's silhouette is wider than tall. A hunched sitter tends
# towards square, so this is deliberately lenient.
SITTING_MIN_BOX_ASPECT = 0.75      # box_h / box_w

# Seated shoulders sit in a band above the person's own foot line. Below the
# band (~1.0-1.3) is someone propped up on the floor after a fall; above it
# (~2.5-3.0) is standing. The upper bound matters because it catches standing
# even when the leg geometry is ambiguous - hip and shoulder height are set by
# the seat, not by which leg happens to be bent, so an extended or swinging
# leg cannot fool it. Only applied when the box is not clipped by the frame
# bottom, since then y2 is the crop edge rather than the real foot line.
SITTING_SHOULDER_HEIGHT_MIN, SITTING_SHOULDER_HEIGHT_MAX = 1.4, 2.2

# torso_len is itself a projected length: someone leaning directly towards or
# away from the camera collapses shoulder onto hip, and every ratio that
# divides by it inflates. Requiring the torso to be a sane fraction of the
# detection box catches that far better than the old `torso_len < 1.0`.
MIN_TORSO_FRACTION_OF_BOX = 0.15

UPRIGHT_POSTURES = ("standing", "falling", "sitting")

# BGR
COLOUR_RED = (0, 0, 255)
COLOUR_AMBER = (0, 165, 255)
COLOUR_BLUE = (255, 0, 0)
COLOUR_GREEN = (0, 255, 0)


class Person():
    def __init__(self, id):
        self.id = id
        self.current_position = None
        self.down_since = None            # time DOWN was first observed
        self.upright_since = None         # time upright was first re-observed
        self.upright_observations = 0     # consecutive upright readings
        self.alerted = False              # LATCH: a fall has been reported

        self.sitting_since = None         # time the current sitting streak began
        self.non_sitting_observations = 0  # consecutive non-sitting readings
        self.sitting_alerted = False      # LATCH: prolonged sitting reported

    # ------------------------------------------------------------------

    def _update_sitting_timer(self, posture, now):
        """Maintain the sitting streak.

        Deliberately runs before the posture branch below, so it still ticks
        on the first observation of a track and during fall recovery, both of
        which return early.
        """
        if posture == "sitting":
            self.non_sitting_observations = 0
            if self.sitting_since is None:
                self.sitting_since = now
        else:
            self.non_sitting_observations += 1
            if self.non_sitting_observations >= SITTING_BREAK_OBSERVATIONS:
                self.sitting_since = None
                self.sitting_alerted = False

    def manage_person_posture(self, posture: str, video_time=None):
        now = time.monotonic() if video_time is None else video_time
        posture = posture.lower()

        self._update_sitting_timer(posture, now)

        # First observation of this track: adopt the posture without arming
        # any fall timer. This is what stops someone who is already lying down
        # when tracking begins (asleep in bed) being reported as a fall.
        if self.current_position is None:
            self.current_position = posture
            return self.current_position

        if posture in UPRIGHT_POSTURES:
            if self.current_position == "lying down" and self.down_since is not None:
                # Recovering from a fall. Confirmation needs BOTH a sustained
                # interval and a sustained number of readings - see the event
                # timing note at the top of the file.
                if self.upright_since is None:
                    self.upright_since = now
                    self.upright_observations = 1
                else:
                    self.upright_observations += 1
                    if (abs(now - self.upright_since) >= RECOVERY_GRACE_SECONDS
                            and self.upright_observations >= MIN_UPRIGHT_OBSERVATIONS):
                        self.current_position = posture
                        self.down_since = None
                        self.upright_since = None
                        self.upright_observations = 0
                        self.alerted = False        # release the latch
                return self.current_position

            self.current_position = posture
            self.upright_since = None
            self.upright_observations = 0

        elif posture == "lying down":
            self.upright_since = None
            self.upright_observations = 0
            # Arms on any upright -> lying transition. The in-bed case stays
            # safe because such a track's FIRST observation is already "lying
            # down", and that returns above without ever reaching here.
            if self.down_since is None and self.current_position in UPRIGHT_POSTURES:
                self.down_since = now
            self.current_position = posture

        return self.current_position

    # ------------------------------------------------------------------

    def alert_fall_event(self, video_time=None) -> bool:
        """Is a fall happening RIGHT NOW? Per-frame test, not the latch."""
        now = time.monotonic() if video_time is None else video_time
        if self.current_position is None:
            return False
        if self.current_position.lower() == "lying down":
            if self.down_since is not None and abs(now - self.down_since) >= DOWN_HOLD_SECONDS:
                return True
        return False

    def alert_prolonged_sitting(self, video_time=None) -> bool:
        """Has the current sitting streak exceeded the threshold?

        Keyed off sitting_since rather than current_position, so an unreadable
        frame or a momentary misclassification does not drop the alert. The
        streak itself is what gets broken, and only by SITTING_BREAK_OBSERVATIONS
        consecutive non-sitting readings.
        """
        now = time.monotonic() if video_time is None else video_time
        if self.sitting_since is None:
            return False
        return abs(now - self.sitting_since) >= SITTING_HOLD_SECONDS

    def seconds_seated(self, video_time=None) -> float:
        now = time.monotonic() if video_time is None else video_time
        if self.sitting_since is None:
            return 0.0
        return abs(now - self.sitting_since)

    def acknowledge(self):
        """Staff-facing hook: close both alerts manually."""
        self.alerted = False
        self.sitting_alerted = False


class FallDetector(ABC):
    # Set to True on the instance to print, per person per frame, which test
    # rejected "sitting". Invaluable for tuning the thresholds above.
    DEBUG_POSTURE = False

    def __init__(self):
        # Shared model/config files live one level up, in backend/detection/,
        # so fall detection and distress detection can both use them.
        dir = os.path.dirname(os.path.abspath(__file__))
        detection_dir = os.path.dirname(dir)
        self.model = YOLO(os.path.join(detection_dir, 'yolo26n-pose.pt'))
        # Use the ONNX version if the run time is slow.
        self.bytetrack_yaml_path = os.path.join(detection_dir, 'bytetrack.yaml')

        self.person_posture = {}
        self.paused = False

    @abstractmethod
    def get_cam(self):
        pass

    @abstractmethod
    def is_video_mode(self):
        pass

    @abstractmethod
    def get_fps(self):
        pass

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _midpoint(self, kp, conf, i, j, min_conf=KP_CONF):
        """Midpoint of two keypoints, or None if either is unreliable."""
        if conf[i] < min_conf or conf[j] < min_conf:
            if self.DEBUG_POSTURE:
                print(f"  kp conf too low: {float(conf[i]):.2f} / {float(conf[j]):.2f}")
            return None
        return ((float(kp[i][0]) + float(kp[j][0])) / 2.0,
                (float(kp[i][1]) + float(kp[j][1])) / 2.0)

    def _pt(self, kp, i):
        """Keypoint i as a plain (x, y) float tuple, out of the tensor."""
        return (float(kp[i][0]), float(kp[i][1]))

    def _angle_from_vertical(self, top, bottom):
        """0 deg = segment is vertical, 90 deg = segment is horizontal."""
        dy = abs(bottom[1] - top[1])
        dx = abs(bottom[0] - top[0])
        return abs(90.0 - math.degrees(math.atan2(dy, dx)))

    def _joint_angle(self, a, b, c):
        """Interior angle at joint b, between segments b->a and b->c, degrees.

        180 = limb fully extended, 90 = right angle, 0 = folded shut.
        Unlike _angle_from_vertical this measures the angle BETWEEN two
        segments, so it does not change when the person is rotated in the
        image plane. It DOES still change with azimuth, which is why it is
        corroboration rather than the primary test.
        """
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(v1[0], v1[1])
        n2 = math.hypot(v2[0], v2[1])
        if n1 < 1e-6 or n2 < 1e-6:
            return None
        cosine = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        cosine = max(-1.0, min(1.0, cosine))   # clamp before acos
        return math.degrees(math.acos(cosine))

    # ------------------------------------------------------------------
    # Sitting detection
    # ------------------------------------------------------------------

    def _leg_looks_seated(self, kp, conf, shoulder_centre, hip_i, knee_i,
                          ankle_i, torso_len, debug=None):
        """Seated geometry for one leg. True / False / None.

        None means "cannot judge this leg this frame" and is deliberately
        distinct from False, so the caller can ignore an unusable leg rather
        than count it as evidence against sitting. In a side-on view the far
        leg is occluded most of the time.

        Only the hip and knee are required. The ankle is used when present and
        skipped silently when it is not - footage cropped at the waist or
        knees, or a person seated at a desk, simply has no ankles to offer.
        """
        if conf[hip_i] < KP_CONF_SITTING or conf[knee_i] < KP_CONF_SITTING:
            if debug is not None:
                debug.append(f"leg{knee_i}: hip/knee conf low "
                             f"({float(conf[hip_i]):.2f}/{float(conf[knee_i]):.2f})")
            return None

        hip = self._pt(kp, hip_i)
        knee = self._pt(kp, knee_i)

        # ---- PRIMARY TEST: vertical drop, normalised by torso length ----
        # Signed: y grows downwards, so a knee below the hip is positive.
        knee_drop = (knee[1] - hip[1]) / torso_len
        if debug is not None:
            debug.append(f"leg{knee_i}: knee_drop={knee_drop:.2f}")
        if knee_drop > KNEE_DROP_SEATED_MAX:
            return False        # knee hangs a femur below the hip -> standing

        # ---- CORROBORATION: only when the thigh projects long enough ----
        thigh_len = math.hypot(knee[0] - hip[0], knee[1] - hip[1])
        if thigh_len < MIN_SEGMENT_RATIO * torso_len:
            if debug is not None:
                debug.append(f"leg{knee_i}: thigh foreshortened, drop test only")
            return True

        hip_angle = self._joint_angle(shoulder_centre, hip, knee)
        if hip_angle is not None:
            if debug is not None:
                debug.append(f"leg{knee_i}: hip_angle={hip_angle:.0f}")
            if not (HIP_BENT_MIN <= hip_angle <= HIP_BENT_MAX):
                return False

        if conf[ankle_i] >= KP_CONF_SITTING:
            ankle = self._pt(kp, ankle_i)
            shin_len = math.hypot(ankle[0] - knee[0], ankle[1] - knee[1])
            if shin_len >= MIN_SEGMENT_RATIO * torso_len:
                knee_angle = self._joint_angle(hip, knee, ankle)
                if knee_angle is not None:
                    if debug is not None:
                        debug.append(f"leg{knee_i}: knee_angle={knee_angle:.0f}")
                    if not (KNEE_BENT_MIN <= knee_angle <= KNEE_BENT_MAX):
                        return False

        return True

    def _is_sitting(self, kp, conf, torso_angle, torso_len, box, frame_h,
                    shoulder_centre, debug=None):
        """Torso gate, silhouette gate, both legs, then a height sanity check."""
        # Cheapest tests first, and they are the ones excluding "lying down".
        if torso_angle > TORSO_FOLDED_MAX:
            if debug is not None:
                debug.append(f"reject: torso {torso_angle:.0f} deg")
            return False

        x1, y1, x2, y2 = box
        box_w, box_h = max(x2 - x1, 1), max(y2 - y1, 1)
        if box_h / box_w < SITTING_MIN_BOX_ASPECT:
            if debug is not None:
                debug.append(f"reject: box aspect {box_h / box_w:.2f}")
            return False

        left = self._leg_looks_seated(kp, conf, shoulder_centre,
                                      L_HIP, L_KNEE, L_ANKLE, torso_len, debug)
        right = self._leg_looks_seated(kp, conf, shoulder_centre,
                                       R_HIP, R_KNEE, R_ANKLE, torso_len, debug)
        usable = [v for v in (left, right) if v is not None]
        if not usable:
            if debug is not None:
                debug.append("reject: no judgeable leg")
            return False

        # any() rather than all(): desks, chair arms and the person's own body
        # occlude one leg constantly, and when both legs are clean they are
        # near-parallel and agree anyway. Swap to all() if false "sitting"
        # shows up on people bending over.
        if not any(usable):
            return False

        if y2 < frame_h - 5:
            height_ratio = (y2 - shoulder_centre[1]) / torso_len
            if debug is not None:
                debug.append(f"height_ratio={height_ratio:.2f}")
            if not (SITTING_SHOULDER_HEIGHT_MIN <= height_ratio
                    <= SITTING_SHOULDER_HEIGHT_MAX):
                return False

        return True

    # ------------------------------------------------------------------

    def classify_posture(self, kp, conf, box, frame_h,
                         standing_threshold=10, lying_threshold=60):
        shoulder_centre = self._midpoint(kp, conf, L_SHOULDER, R_SHOULDER)
        hip_centre = self._midpoint(kp, conf, L_HIP, R_HIP)
        if shoulder_centre is None or hip_centre is None:
            return None   # not enough information this frame - caller holds

        # Torso length is our scale unit: a rigid segment, so it tracks the
        # person's apparent size (their distance from the camera) without
        # changing much between postures.
        torso_len = math.hypot(hip_centre[0] - shoulder_centre[0],
                               hip_centre[1] - shoulder_centre[1])
        x1, y1, x2, y2 = box
        box_h = max(y2 - y1, 1)
        if torso_len < MIN_TORSO_FRACTION_OF_BOX * box_h:
            return None   # torso pointing at the camera - every ratio that
                          # divides by torso_len would be garbage

        torso_angle = self._angle_from_vertical(shoulder_centre, hip_centre)

        debug = [] if self.DEBUG_POSTURE else None
        if self._is_sitting(kp, conf, torso_angle, torso_len, box, frame_h,
                            shoulder_centre, debug):
            if debug:
                print("SITTING     | " + " | ".join(debug))
            return "sitting"
        if debug:
            print(f"not sitting | torso={torso_angle:.0f} | " + " | ".join(debug))

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
            if self._angle_from_vertical(hip_centre, lower) > 50.0:
                votes += 1

        # 2. Silhouette is wider than it is tall. Comes from the detector
        #    rather than the pose model, so it fails independently of the
        #    keypoints.
        box_w = max(x2 - x1, 1)
        checks += 1
        if box_w / box_h > 1.0:
            votes += 1

        # 3. Shoulders sit low above the person's own foot line, in units of
        #    their own torso. Standing is roughly 2.5-3.0 torso lengths,
        #    sitting roughly 1.5, lying below 1.3. Skipped when the box is
        #    clipped by the bottom of the frame, because then y2 is not the
        #    real foot line.
        if y2 < frame_h - 5:
            checks += 1
            if (y2 - shoulder_centre[1]) / torso_len < 1.3:
                votes += 1

        # Need corroboration from at least two independent checks; if fewer
        # than two were evaluable, demand that every evaluable one agrees.
        required = 2 if checks >= 2 else checks
        if checks > 0 and votes >= required:
            return "lying down"
        return "falling"

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        cam = self.get_cam()
        model = self.model

        while True:
            ret, frame = cam.read()
            if not ret:
                break

            if self.is_video_mode():
                self.frame_index += 1
            frame_h, frame_w = frame.shape[0], frame.shape[1]
            annotated_frame = None
            banners = []          # (text, colour) drawn stacked, top-left

            self.fps = self.get_fps()
            video_time = self.get_video_time() if self.is_video_mode() else None

            results = model.track(source=frame,
                                  persist=True,
                                  classes=[0],      # only track class 0 = person
                                  device='cpu',     # force CPU regardless of GPU
                                  tracker=self.bytetrack_yaml_path)

            # results is a list of Results objects, one per frame. We pass a
            # single frame, so results[0]. It is never None - the only way to
            # tell nobody is in frame is boxes.id being None.
            has_people = (results
                          and results[0].boxes.id is not None
                          and results[0].keypoints is not None
                          and results[0].keypoints.conf is not None)

            if has_people:
                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                ids = results[0].boxes.id.cpu().numpy().astype(int).tolist()
                all_kp = results[0].keypoints.xy.cpu()
                all_conf = results[0].keypoints.conf.cpu()
                annotated_frame = results[0].plot(
                    boxes=True,      # draw bounding boxes
                    kpt_line=True,   # draw skeleton lines between keypoints
                    kpt_radius=5,    # keypoint dot size
                    labels=True,     # draw class + track ID labels
                )
                for i, person_id in enumerate(ids):
                    person = self.person_posture.get(person_id)
                    if person is None:
                        person = Person(person_id)
                        self.person_posture[person_id] = person

                    box = boxes[i]
                    box_midpoint = (int(box[0] + abs(box[0] - box[2]) / 2),
                                    int(box[1] + abs(box[1] - box[3]) / 2))
                    kp = all_kp[i]
                    confidence = all_conf[i]

                    posture = self.classify_posture(kp=kp, conf=confidence,
                                                    box=box, frame_h=frame_h)

                    # An unreadable frame is not evidence that the person
                    # changed posture. Hold the last known state rather than
                    # `continue`-ing, which used to erase the label on every
                    # frame with dodgy keypoints - i.e. most frames while
                    # someone is curled on the floor.
                    if posture is not None:
                        position = person.manage_person_posture(
                            posture, video_time=video_time)
                    else:
                        position = person.current_position   # hold, don't advance

                    if position is not None:
                        cv2.putText(annotated_frame, position, box_midpoint,
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                    COLOUR_BLUE, 2, cv2.LINE_AA)

                    # --- Fall: latched -------------------------------------
                    # alert_fall_event() asks "is a fall happening now"; the
                    # `alerted` flag records that one already did. Drawing on
                    # the latch means the banner survives dropped detections,
                    # unreadable keypoints and momentary misclassification.
                    if person.alert_fall_event(video_time=video_time):
                        if not person.alerted:
                            print(f"Person {person_id} had a fall "
                                  f"=========================================")
                            person.alerted = True
                    if person.alerted:
                        banners.append((f"Person {person_id} had a fall",
                                        COLOUR_RED))

                    # --- Prolonged sitting: latched ------------------------
                    if person.alert_prolonged_sitting(video_time=video_time):
                        if not person.sitting_alerted:
                            print(f"Person {person_id} seated over "
                                  f"{SITTING_HOLD_SECONDS:.0f}s "
                                  f"-----------------------------------------")
                            person.sitting_alerted = True
                    if person.sitting_alerted:
                        secs = person.seconds_seated(video_time=video_time)
                        banners.append((f"Person {person_id} seated {secs:.0f}s",
                                        COLOUR_RED))

            display_frame = frame if annotated_frame is None else annotated_frame
            cv2.putText(display_frame, f"FPS: {int(self.fps)}", (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, COLOUR_GREEN, 2, cv2.LINE_AA)

            # Stacked so several people, or one person with both alerts open,
            # do not overwrite each other.
            for idx, (text, colour) in enumerate(banners):
                cv2.putText(display_frame, text, (30, 80 + idx * 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2, cv2.LINE_AA)

            cv2.imshow('frame', display_frame)

            # Single waitKey per iteration. Calling waitKey(1) at the top of
            # the loop AND waitKey(delay) at the bottom split keypresses
            # between whichever call happened to catch them.
            if self.is_video_mode():
                # waitKey(0) blocks indefinitely, which is what gives us pause.
                key = cv2.waitKey(0 if self.paused else PLAYBACK_DELAY_MS) & 0xFF
            else:
                key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                break
            elif key == ord(' '):
                self.paused = not self.paused    # space toggles pause
            elif key == ord('n'):
                self.paused = True               # one frame on, then pause
            elif key == ord('a'):
                # Acknowledge every open alert - stands in for the staff-
                # facing acknowledgement the real system would have.
                for p in self.person_posture.values():
                    p.acknowledge()

        cam.release()
        cv2.destroyAllWindows()

    # TODO
    # "falling" is currently a single-frame torso angle, not motion. Once the
    # frame rate is stable, add vertical velocity of the hip centre to
    # distinguish an actual fall from someone leaning forward.
    # Add the ID hand-off: on a new track ID, inherit state from a Person lost
    # within the last second whose last box was nearby. Tracker tuning alone
    # will not survive every fall, and an ID switch mid-fall currently means
    # the new track's first observation is "lying down", which never arms the
    # timer - a silently missed alert.


class VideoMode(FallDetector):
    def __init__(self, filepath):
        super().__init__()
        self.cam = cv2.VideoCapture(filepath)
        video_fps = self.cam.get(cv2.CAP_PROP_FPS)
        if not video_fps or video_fps <= 0:
            video_fps = 30.0   # some files report 0
        self.fps = video_fps
        self.frame_index = -1

    def get_cam(self):
        return self.cam

    def get_fps(self):
        return self.fps

    def is_video_mode(self):
        return True

    def get_video_time(self):
        return self.frame_index / self.fps


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
        self.fps = (1 / self.time_delta) if self.time_delta > 0 else 0
        self.prev_time = self.new_time

    def get_fps(self):
        self.calculate_fps()
        return self.fps

    def is_video_mode(self):
        return False


if __name__ == "__main__":
    script_dir = Path(__file__).parent
    video_footage_path = join(script_dir, "sitting testing footage", "Test_1.avi")
    if not os.path.isfile(video_footage_path):
        raise Exception("Testing video footage file path is incorrect.")
    video_fall_detector = VideoMode(video_footage_path)
    video_fall_detector.DEBUG_POSTURE = True   # set False once tuned
    video_fall_detector.run()



