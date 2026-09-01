"""
Sitting detection - YOLO-pose variant.

Single responsibility: decide whether each tracked person is SITTING, and
raise an alert when they have been sitting for too long. Fall / lying-down
handling has been removed; the only reason "horizontal" is still mentioned
below is that a lying person has to be EXCLUDED from "sitting", not because
anything here reports it.

=============================================================================
POSTURE CLASSIFICATION - design notes

A person is "sitting" when their knees are at roughly hip height rather than
a full femur below their hips. That vertical relationship is the core of the
whole classifier, and it was chosen deliberately over the more obvious tests
(thigh angle, knee angle) for one reason:

  Rotating a person about their own vertical axis changes their x
  coordinates but leaves their y coordinates alone.

So the vertical hip->knee drop survives the camera azimuth changes that
destroy every angle measured in the image plane. A seated person angled
towards the camera has a thigh that projects to a near-vertical stub - the
thigh angle says "standing", the knee drop still says "sitting".

The angle tests are kept, but as CORROBORATION only, applied when the limb
projects long enough to be trustworthy. This ordering is what stops the
classifier from measuring the camera instead of the pose.

WHEN THE BODY-RELATIVE TESTS RUN OUT - scene context

Every test above is measured in units of torso_len, which is the person's
own projected torso. That is scale-invariant, which is exactly what we want
- until the person is far enough away that torso_len is only ~20px. Then a
couple of pixels of keypoint jitter is a 10-20% error in EVERY ratio, and
the whole pipeline goes soft at once. No amount of extra body-relative
geometry fixes this, because they all share the same failing denominator.

So past that point we stop asking the body and start asking the SCENE.
Three independent signals, none of which divide by torso_len:

  1. GROUND PLANE (homography). Four floor points, measured once per camera,
     give an image -> floor-coordinate map. A person's foot position then
     becomes a real (X, Y) in metres. This is the only one of the three that
     genuinely resolves depth, and it is what separates "standing IN FRONT
     of the bench" from "sitting ON the bench" - the two project to the same
     place in the image and to very different places on the floor.

  2. SEAT REGIONS. Furniture detected once at startup and cached (the camera
     is static, the bench does not move). Gives us "is this person's hip at
     seat height" in image space, and with (1) also "is this person actually
     AT the seat" on the floor plane.

  3. HIP STILLNESS. A seated person's hip is static for many seconds; a
     stander sways and drifts. Purely temporal, so it fails independently of
     everything geometric.

All three are EVIDENCE, never overrides. Signal 2 on its own has exactly the
depth ambiguity we are trying to escape (a 2D box does not know who is in
front of it), and signal 3 on its own cannot tell "seated" from "standing
very still". They are only trustworthy in conjunction, which is why the
near-vertical-torso branch below requires seat evidence AND a second signal
before it will promote a verdict to "sitting".

EVENT TIMING - design notes

Every timed state in this file follows the same rule, learned the hard way:
an event must be confirmed by a sustained NUMBER OF OBSERVATIONS as well as
a sustained INTERVAL OF TIME. Testing elapsed time alone lets two stray
frames either side of a dropout satisfy a one-second threshold on the
strength of two frames of evidence. Every threshold below therefore comes in
pairs: a _SECONDS and an _OBSERVATIONS constant.
=============================================================================
"""

from abc import ABC, abstractmethod
from collections import deque
import cv2
from ultralytics import YOLO
import math
import numpy as np
import os
import time
from pathlib import Path
from os.path import join


# --- Prolonged sitting ---------------------------------------------------
# NOTE: this is a TESTING value. Clinically the concern is immobility over
# tens of minutes to hours - pressure injury risk, missed meals, someone who
# cannot get themselves back up. A few seconds in a real ward would fire on
# essentially every resident continuously. Raise to something like 1800
# (30 min) before any real deployment or demo with clinical staff.
SITTING_HOLD_SECONDS = 3.0

# Consecutive NON-sitting readings needed to break a sitting streak. Without
# it, a single misclassified frame just before the threshold silently restarts
# the timer and the alert never fires. Unreadable frames do not count either
# way - they never reach here.
SITTING_BREAK_OBSERVATIONS = 5

# Confidence required for a keypoint to be usable. 0.30 rather than 0.5:
# the higher value is punishing on small, dim or backlit footage, and the
# geometry tests below reject bad poses anyway.
KP_CONF = 0.30

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

# --- Bent-knee evidence --------------------------------------------------
# Used only in the scene-context branch, as a cheap second signal alongside
# seat evidence. It asks "is this knee visibly bent", using the same
# hip-knee-ankle angle as the sitting corroboration test with a looser gate.
# Someone sitting upright with only a slight forward lean often fails the
# full sitting test (occluded ankle, a knee_drop a hair over
# KNEE_DROP_SEATED_MAX) while their leg geometry is obviously not "standing
# on straight legs".
BENT_KNEE_ANGLE_MAX = 150.0

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

# Below this the torso reads as near-vertical, which is where the scene
# context branch runs: a straight-legged stander and someone sitting upright
# look identical by torso angle alone.
TORSO_UPRIGHT_MAX = 10.0

# A lying person's silhouette is wider than tall. A hunched sitter tends
# towards square, so this is deliberately lenient.
SITTING_MIN_BOX_ASPECT = 0.75      # box_h / box_w

# Seated shoulders sit in a band above the person's own foot line. Below the
# band (~1.0-1.3) is someone propped up on the floor; above it (~2.5-3.0) is
# standing. The upper bound matters because it catches standing even when the
# leg geometry is ambiguous - hip and shoulder height are set by the seat, not
# by which leg happens to be bent, so an extended or swinging leg cannot fool
# it. Only applied when the box is not clipped by the frame bottom, since then
# y2 is the crop edge rather than the real foot line.
SITTING_SHOULDER_HEIGHT_MIN, SITTING_SHOULDER_HEIGHT_MAX = 1.4, 2.2

# torso_len is itself a projected length: someone leaning directly towards or
# away from the camera collapses shoulder onto hip, and every ratio that
# divides by it inflates. Requiring the torso to be a sane fraction of the
# detection box catches that.
MIN_TORSO_FRACTION_OF_BOX = 0.15

# =============================================================================
# SCENE CONTEXT CONFIGURATION
# =============================================================================

# --- 1. Ground plane (homography) ---------------------------------------
# Measure a rectangle on the floor that the camera can see - floor tiles, or
# four bits of tape - and enter its real dimensions here. Then run with
# CALIBRATE_ON_START, or press 'c', and click its four corners in this order:
#
#     near-left, near-right, far-right, far-left
#
# ("near" = closest to the camera). The clicked points get printed; paste them
# into GROUND_PLANE_IMAGE_POINTS so calibration persists across runs.
#
# Leave GROUND_PLANE_IMAGE_POINTS as None and everything still works - the
# floor-plane tests simply report "cannot judge" and the classifier falls back
# to the image-space seat test plus stillness.
GROUND_RECT_WIDTH_M = 2.0     # near-left -> near-right, in metres
GROUND_RECT_DEPTH_M = 2.0     # near edge -> far edge, in metres
GROUND_PLANE_IMAGE_POINTS = None   # e.g. [[120,400],[510,400],[430,250],[190,250]]
CALIBRATE_ON_START = False

# A point this far (metres) from a seat's front edge counts as "at" that seat.
# Roughly one shuffling step - tight enough to exclude someone walking past,
# loose enough to survive foot-point error.
SEAT_FLOOR_PROXIMITY_M = 0.45

# Homography extrapolates violently outside the calibrated quad, and explodes
# entirely near the horizon. Anything mapping beyond this many metres from the
# origin is treated as unmeasurable rather than believed.
GROUND_MAX_SANE_METRES = 50.0

# --- 2. Seat detection ---------------------------------------------------
# The pose weights are person-only, so furniture needs a separate detection
# model. It runs for the first SEAT_DETECT_FRAMES frames and then NEVER AGAIN:
# on a fixed camera the bench does not move, so this costs a handful of
# inferences at startup rather than one per frame. That matters a lot given
# everything here is pinned to device='cpu'.
SEAT_MODEL_FILENAME = 'yolo26s.pt'   # standard detection weights, not -pose
SEAT_CLASSES = {13: 'bench', 56: 'chair', 57: 'couch', 59: 'bed'}
SEAT_DETECT_FRAMES = 30      # frames to accumulate before finalising
SEAT_DETECT_CONF = 0.35
SEAT_MIN_PERSISTENCE = 0.5   # must appear in this fraction of those frames

# THE BACKREST GOTCHA. The top edge of a detection box is not the seat
# surface. For a backless bench the box top IS roughly the seat; for a chair
# or couch the box top is the top of the BACKREST and the seat surface sits
# about halfway down. Hardcoding "seat surface = y1" is right on benches and
# consistently wrong on chairs. These are fractions of box height below y1.
SEAT_SURFACE_FRACTION = {'bench': 0.15, 'chair': 0.50,
                         'couch': 0.55, 'bed': 0.25}
SEAT_SURFACE_FRACTION_DEFAULT = 0.40

# How close (in torso lengths) the hip must be to the estimated seat surface,
# and how far outside the seat's horizontal span it may stray (as a fraction
# of seat width) before it stops counting.
SEAT_HIP_BAND = 0.60
SEAT_X_MARGIN = 0.25

# --- 3. Hip stillness ----------------------------------------------------
# Purely temporal, so it fails independently of every geometric test. Note the
# usual pairing: a window in SECONDS and a minimum number of OBSERVATIONS, so
# two frames either side of a dropout cannot satisfy it.
STILLNESS_WINDOW_SECONDS = 3.0
STILLNESS_MIN_OBSERVATIONS = 8
STILLNESS_MAX_DRIFT_TORSO = 0.35   # torso lengths, when no ground plane
STILLNESS_MAX_DRIFT_M = 0.20       # metres, when the ground plane is calibrated
HIP_HISTORY_MAXLEN = 240

# BGR
COLOUR_RED = (0, 0, 255)
COLOUR_AMBER = (0, 165, 255)
COLOUR_BLUE = (255, 0, 0)
COLOUR_GREEN = (0, 255, 0)
COLOUR_CYAN = (255, 255, 0)
COLOUR_WHITE = (255, 255, 255)

# Box outline colour by alert state. Swap the alert colour to COLOUR_AMBER if
# red reads as too severe for a sitting notice in the demo.
BOX_COLOUR_NORMAL = COLOUR_GREEN
BOX_COLOUR_SITTING_ALERT = COLOUR_RED
BOX_THICKNESS = 2


# =============================================================================
# Scene geometry
# =============================================================================

class GroundPlane:
    """Image <-> floor-plane mapping from a single homography.

    Calibrated from four points on a real floor rectangle. Everything is
    optional: if construction fails, or no points were supplied, `ok` is False
    and to_floor() returns None forever, so callers treat the floor tests as
    "cannot judge" rather than as evidence either way.

    IMPORTANT LIMITATION. A homography maps ONE plane - the floor. It is only
    valid for image points that are actually on the floor, which in practice
    means feet and the base of furniture. Passing it a hip or a shoulder
    returns a meaningless number, because those points are metres above the
    plane being mapped. That is why every caller below feeds it foot points
    and seat base points, never torso keypoints. Recovering true heights above
    the plane needs full single-view metrology (a vertical vanishing point),
    which is well beyond what this buys us - floor POSITION is all we need to
    tell "in front of the bench" from "on the bench".
    """

    def __init__(self, image_points=None, world_points=None):
        self.H = None
        self.ok = False
        if image_points is None or world_points is None:
            return
        if len(image_points) < 4 or len(image_points) != len(world_points):
            print("GroundPlane: need >= 4 matched point pairs; disabled.")
            return
        src = np.array(image_points, dtype=np.float32).reshape(-1, 1, 2)
        dst = np.array(world_points, dtype=np.float32).reshape(-1, 1, 2)
        H, _ = cv2.findHomography(src, dst)
        if H is None:
            print("GroundPlane: findHomography failed (degenerate points?); "
                  "disabled.")
            return
        self.H = H
        self.ok = True

    @classmethod
    def from_rectangle(cls, image_points, width_m, depth_m):
        """Build from four clicked corners of a floor rectangle.

        Click order is near-left, near-right, far-right, far-left, so the
        world frame has its origin at the near-left corner, +X to the right
        along the near edge and +Y away from the camera.
        """
        if image_points is None:
            return cls()
        world = [[0.0, 0.0], [width_m, 0.0], [width_m, depth_m], [0.0, depth_m]]
        return cls(image_points, world)

    def to_floor(self, pt):
        """Image point -> (X, Y) metres on the floor plane, or None.

        Returns None rather than a wild number when the mapping is not
        trustworthy: outside the calibrated quad the homography extrapolates
        badly, and at the horizon the perspective divide approaches zero and
        the result runs off to infinity.
        """
        if not self.ok or pt is None:
            return None
        p = np.array([[[float(pt[0]), float(pt[1])]]], dtype=np.float32)
        out = cv2.perspectiveTransform(p, self.H)
        x, y = float(out[0][0][0]), float(out[0][0][1])
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        if abs(x) > GROUND_MAX_SANE_METRES or abs(y) > GROUND_MAX_SANE_METRES:
            return None
        return (x, y)

    @staticmethod
    def distance(a, b):
        if a is None or b is None:
            return None
        return math.hypot(a[0] - b[0], a[1] - b[1])


def point_to_segment_distance(p, a, b):
    """Shortest distance from point p to line segment ab. All 2D tuples."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    # Projection parameter of p onto ab, clamped to the segment.
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class SeatRegion:
    """One piece of seating furniture, fixed in the frame."""

    def __init__(self, box, cls_name):
        self.x1, self.y1, self.x2, self.y2 = [float(v) for v in box]
        self.cls_name = cls_name
        self.floor_segment_world = None   # filled in once the plane is known

    @property
    def width(self):
        return max(self.x2 - self.x1, 1.0)

    @property
    def height(self):
        return max(self.y2 - self.y1, 1.0)

    @property
    def surface_y(self):
        """Estimated y of the SEAT SURFACE, not the top of the box.

        See the SEAT_SURFACE_FRACTION note above - conflating the two is the
        single easiest way to get this wrong on chairs.
        """
        frac = SEAT_SURFACE_FRACTION.get(self.cls_name,
                                         SEAT_SURFACE_FRACTION_DEFAULT)
        return self.y1 + frac * self.height

    def base_segment_image(self):
        """The furniture's front edge where it meets the floor, in image
        coordinates. This is the only part of the box that lies ON the floor
        plane, so it is the only part safe to hand to GroundPlane."""
        return ((self.x1, self.y2), (self.x2, self.y2))

    def bind_to_ground(self, ground):
        if ground is None or not ground.ok:
            return
        a, b = self.base_segment_image()
        wa, wb = ground.to_floor(a), ground.to_floor(b)
        if wa is not None and wb is not None:
            self.floor_segment_world = (wa, wb)

    def hip_over_surface(self, hip_centre, torso_len):
        """Image-space test: is the hip horizontally over this seat and
        vertically near its surface? True/False.

        On its own this has EXACTLY the depth ambiguity we are trying to
        escape - someone standing in front of the bench at the right distance
        satisfies it too. It is only meaningful alongside a second signal.
        """
        margin = SEAT_X_MARGIN * self.width
        if not (self.x1 - margin <= hip_centre[0] <= self.x2 + margin):
            return False
        return abs(hip_centre[1] - self.surface_y) <= SEAT_HIP_BAND * torso_len

    def floor_distance_to(self, foot_world):
        """Metres from a person's floor position to this seat's front edge,
        or None if either end is unavailable."""
        if self.floor_segment_world is None or foot_world is None:
            return None
        a, b = self.floor_segment_world
        return point_to_segment_distance(foot_world, a, b)


class SeatRegistry:
    """Detects seating once at startup, then caches it.

    Deliberately NOT per-frame. The camera is fixed, so re-running furniture
    detection every frame would burn CPU to re-derive a constant. Accumulating
    over SEAT_DETECT_FRAMES and keeping only boxes that persist guards against
    a single flaky frame defining the scene geometry for the whole session.
    """

    def __init__(self, model_path, ground=None):
        self.ground = ground
        self.model = None
        self._accumulators = []   # [{'boxes': [...], 'cls': name, 'count': n}]
        self._frames_seen = 0
        self._finalised = False
        self._seats = []

        if not os.path.isfile(model_path):
            print(f"SeatRegistry: '{os.path.basename(model_path)}' not found - "
                  f"seat detection disabled. Body-relative tests and stillness "
                  f"still run.")
            self._finalised = True
            return
        try:
            self.model = YOLO(model_path)
        except Exception as exc:                      # noqa: BLE001
            print(f"SeatRegistry: could not load detector ({exc}); disabled.")
            self._finalised = True

    # -- accumulation ------------------------------------------------

    @property
    def finalised(self):
        return self._finalised

    def seats(self):
        return self._seats

    @staticmethod
    def _iou(a, b):
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(a[2] - a[0], 0) * max(a[3] - a[1], 0)
        area_b = max(b[2] - b[0], 0) * max(b[3] - b[1], 0)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def observe(self, frame):
        """Feed one startup frame. Finalises itself once it has enough."""
        if self._finalised or self.model is None:
            return
        results = self.model.predict(source=frame, device='cpu',
                                     conf=SEAT_DETECT_CONF, verbose=False)
        self._frames_seen += 1

        if results and results[0].boxes is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            classes = results[0].boxes.cls.cpu().numpy().astype(int)
            for box, cls_id in zip(boxes, classes):
                if cls_id not in SEAT_CLASSES:
                    continue
                name = SEAT_CLASSES[cls_id]
                box = [float(v) for v in box]
                # Match to an existing accumulator, or start a new one.
                for acc in self._accumulators:
                    if acc['cls'] == name and self._iou(acc['boxes'][-1], box) > 0.5:
                        acc['boxes'].append(box)
                        acc['count'] += 1
                        break
                else:
                    self._accumulators.append({'boxes': [box], 'cls': name,
                                               'count': 1})

        if self._frames_seen >= SEAT_DETECT_FRAMES:
            self.finalise()

    def finalise(self):
        """Keep persistent detections, median their coordinates, bind to the
        floor plane. After this the detector is dropped entirely."""
        if self._finalised:
            return
        needed = max(1, int(SEAT_MIN_PERSISTENCE * self._frames_seen))
        for acc in self._accumulators:
            if acc['count'] < needed:
                continue
            median_box = np.median(np.array(acc['boxes']), axis=0).tolist()
            seat = SeatRegion(median_box, acc['cls'])
            seat.bind_to_ground(self.ground)
            self._seats.append(seat)

        self._finalised = True
        self._accumulators = []
        self.model = None          # release the detector; never needed again

        if self._seats:
            bound = sum(1 for s in self._seats if s.floor_segment_world)
            print(f"SeatRegistry: locked {len(self._seats)} seat region(s) "
                  f"({', '.join(s.cls_name for s in self._seats)}); "
                  f"{bound} bound to the floor plane.")
        else:
            print("SeatRegistry: no seating found; seat tests will abstain.")

    def draw(self, frame):
        for seat in self._seats:
            cv2.rectangle(frame, (int(seat.x1), int(seat.y1)),
                          (int(seat.x2), int(seat.y2)), COLOUR_CYAN, 1)
            # The estimated seat surface, which is what the hip is compared
            # against - worth seeing, since it is the most error-prone part.
            sy = int(seat.surface_y)
            cv2.line(frame, (int(seat.x1), sy), (int(seat.x2), sy),
                     COLOUR_CYAN, 2)
            cv2.putText(frame, seat.cls_name, (int(seat.x1), max(int(seat.y1) - 4, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOUR_CYAN, 1, cv2.LINE_AA)


class Person():
    """One tracked person: their current verdict and their sitting streak."""

    def __init__(self, id):
        self.id = id
        self.current_position = None

        self.sitting_since = None          # time the current streak began
        self.non_sitting_observations = 0  # consecutive non-sitting readings
        self.sitting_alerted = False       # LATCH: prolonged sitting reported

        # Rolling (time, x, y) of the hip centre, for the stillness test.
        # Bounded so a long-running track cannot grow this without limit.
        self.hip_history = deque(maxlen=HIP_HISTORY_MAXLEN)

    # ------------------------------------------------------------------

    def record_hip(self, hip_centre, now):
        self.hip_history.append((now, hip_centre[0], hip_centre[1]))

    def hip_drift(self, now, window=STILLNESS_WINDOW_SECONDS):
        """Max hip displacement (pixels) within the recent window, and the
        number of samples it was measured over.

        Max spread rather than start-to-end displacement: someone who rocks
        forward and back returns to where they started, and a start-to-end
        measure would call that perfectly still.
        """
        recent = [(t, x, y) for (t, x, y) in self.hip_history
                  if abs(now - t) <= window]
        if len(recent) < 2:
            return None, len(recent)
        xs = [x for (_, x, _) in recent]
        ys = [y for (_, _, y) in recent]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        return spread, len(recent)

    def manage_person_posture(self, posture: str, video_time=None):
        """Feed one READABLE observation. Unreadable frames must not call
        this: a frame we could not read is not evidence that the person moved,
        so the caller holds the previous state instead."""
        now = time.monotonic() if video_time is None else video_time
        posture = posture.lower()

        if posture == "sitting":
            self.non_sitting_observations = 0
            if self.sitting_since is None:
                self.sitting_since = now
        else:
            self.non_sitting_observations += 1
            if self.non_sitting_observations >= SITTING_BREAK_OBSERVATIONS:
                self.sitting_since = None
                self.sitting_alerted = False

        self.current_position = posture
        return self.current_position

    # ------------------------------------------------------------------

    def alert_prolonged_sitting(self, video_time=None) -> bool:
        """Has the current sitting streak exceeded the threshold?

        Keyed off sitting_since rather than current_position, so an unreadable
        frame or a momentary misclassification does not drop the alert. The
        streak itself is what gets broken, and only by
        SITTING_BREAK_OBSERVATIONS consecutive non-sitting readings.
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

    def box_colour(self):
        """Outline colour for this person's detection box.

        Reads the LATCH, not the per-frame test, so the box stays red through
        dropped detections and unreadable keypoints for exactly the same
        reason the banner does.
        """
        return BOX_COLOUR_SITTING_ALERT if self.sitting_alerted else BOX_COLOUR_NORMAL

    def acknowledge(self):
        """Staff-facing hook: close the alert manually."""
        self.sitting_alerted = False


class SittingDetector(ABC):
    # Set to True on the instance to print, per person per frame, which test
    # rejected "sitting". Invaluable for tuning the thresholds above.
    DEBUG_POSTURE = False

    def __init__(self):
        # Shared model/config files live one level up, in backend/detection/,
        # so sitting detection and distress detection can both use them.
        dir = os.path.dirname(os.path.abspath(__file__))
        detection_dir = os.path.dirname(dir)
        self.model = YOLO(os.path.join(detection_dir, 'yolo26s-pose.pt'))
        # Use the ONNX version if the run time is slow.
        self.bytetrack_yaml_path = os.path.join(detection_dir, 'bytetrack.yaml')

        self.person_posture = {}
        self.paused = False

        # --- scene context ---
        self.ground = GroundPlane.from_rectangle(GROUND_PLANE_IMAGE_POINTS,
                                                 GROUND_RECT_WIDTH_M,
                                                 GROUND_RECT_DEPTH_M)
        if self.ground.ok:
            print("GroundPlane: calibrated.")
        else:
            print("GroundPlane: not calibrated - floor-plane tests will "
                  "abstain. Press 'c' to calibrate.")
        self.seats = SeatRegistry(os.path.join(detection_dir,
                                               SEAT_MODEL_FILENAME),
                                  ground=self.ground)
        self._calib_clicks = []

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

    def _foot_point(self, kp, conf, box):
        """Where this person meets the floor, in image coordinates.

        Prefers the ankle midpoint; falls back to the bottom centre of the
        detection box, which is a decent proxy for feet and survives ankles
        being occluded or cropped.
        """
        ankles = self._midpoint(kp, conf, L_ANKLE, R_ANKLE)
        if ankles is not None:
            return ankles
        x1, y1, x2, y2 = box
        return ((float(x1) + float(x2)) / 2.0, float(y2))

    # ------------------------------------------------------------------
    # Sitting detection - body-relative
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
        if conf[hip_i] < KP_CONF or conf[knee_i] < KP_CONF:
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

        if conf[ankle_i] >= KP_CONF:
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

    def _leg_is_bent(self, kp, conf, hip_i, knee_i, ankle_i, torso_len, debug=None):
        """Lightweight knee-bend check, used only as scene-context evidence.

        True: the knee angle (hip-knee-ankle) is bent past
        BENT_KNEE_ANGLE_MAX. False: the leg reads straight. None: not enough
        reliable information this frame.
        """
        if (conf[hip_i] < KP_CONF or conf[knee_i] < KP_CONF
                or conf[ankle_i] < KP_CONF):
            return None

        hip = self._pt(kp, hip_i)
        knee = self._pt(kp, knee_i)
        ankle = self._pt(kp, ankle_i)

        thigh_len = math.hypot(knee[0] - hip[0], knee[1] - hip[1])
        shin_len = math.hypot(ankle[0] - knee[0], ankle[1] - knee[1])
        if (thigh_len < MIN_SEGMENT_RATIO * torso_len
                or shin_len < MIN_SEGMENT_RATIO * torso_len):
            if debug is not None:
                debug.append(f"bend-check leg{knee_i}: foreshortened, skipped")
            return None

        angle = self._joint_angle(hip, knee, ankle)
        if angle is None:
            return None
        if debug is not None:
            debug.append(f"bend-check leg{knee_i}: knee_angle={angle:.0f}")
        return angle < BENT_KNEE_ANGLE_MAX

    def _is_sitting(self, kp, conf, torso_angle, torso_len, box, frame_h,
                    shoulder_centre, debug=None):
        """Torso gate, silhouette gate, both legs, then a height sanity check."""
        # Cheapest tests first, and they are the ones excluding a horizontal
        # person - lying curled on one side has the same leg geometry as
        # sitting and only the torso separates them.
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
    # Sitting detection - scene context
    # ------------------------------------------------------------------

    def _seat_evidence(self, hip_centre, foot_point, torso_len, debug=None):
        """Does the scene suggest this person is on a seat?

        Returns (over_surface, at_seat_floor), each True/False/None, where
        None means "no seat or no plane to judge against".

        The two are deliberately separate because they fail differently:

          over_surface  - image space only. Cannot tell who is in front of the
                          bench and who is on it. Cheap, always available.
          at_seat_floor - floor plane. THIS is the one that resolves depth: a
                          person standing in front of the bench is a real
                          half-metre or more away from it on the floor, even
                          though they overlap it in the image.

        Requiring both is what makes the pair worth more than either alone.
        """
        seats = self.seats.seats()
        if not seats:
            return None, None

        over_surface = False
        at_seat_floor = None      # stays None if nothing is bound to the plane

        foot_world = self.ground.to_floor(foot_point) if self.ground.ok else None

        for seat in seats:
            if seat.hip_over_surface(hip_centre, torso_len):
                over_surface = True
                if debug is not None:
                    debug.append(f"hip over {seat.cls_name} surface")

            dist = seat.floor_distance_to(foot_world)
            if dist is not None:
                if at_seat_floor is None:
                    at_seat_floor = False
                if dist <= SEAT_FLOOR_PROXIMITY_M:
                    at_seat_floor = True
                if debug is not None:
                    debug.append(f"floor dist to {seat.cls_name}={dist:.2f}m")

        return over_surface, at_seat_floor

    def _hip_is_still(self, person, now, torso_len, debug=None):
        """True / False / None (not enough history yet).

        Scale handling matters here. In pixels, a person far from the camera
        barely moves for a real metre of walking, so a fixed pixel threshold
        would call every distant person "still". Two fixes, in order of
        preference: measure the drift in metres on the floor plane, or
        normalise it by torso_len. Both make the threshold mean the same
        thing everywhere in the frame.
        """
        drift_px, samples = person.hip_drift(now)
        if drift_px is None or samples < STILLNESS_MIN_OBSERVATIONS:
            return None

        # Prefer real metres when the plane is calibrated. The hip is not on
        # the floor, so we convert the DISPLACEMENT using the person's foot
        # position as the anchor - locally the scale is near enough constant.
        if self.ground.ok and person.hip_history:
            recent = list(person.hip_history)[-1]
            anchor = (recent[1], recent[2] + torso_len * 2.0)  # approx feet
            a = self.ground.to_floor(anchor)
            b = self.ground.to_floor((anchor[0] + drift_px, anchor[1]))
            metres = GroundPlane.distance(a, b)
            if metres is not None:
                if debug is not None:
                    debug.append(f"hip drift={metres:.2f}m over {samples}")
                return metres <= STILLNESS_MAX_DRIFT_M

        normalised = drift_px / torso_len
        if debug is not None:
            debug.append(f"hip drift={normalised:.2f} torso over {samples}")
        return normalised <= STILLNESS_MAX_DRIFT_TORSO

    # ------------------------------------------------------------------

    def classify_posture(self, kp, conf, box, frame_h, person=None, now=None):
        """Returns "sitting", "not sitting", or None.

        None means the frame was unreadable and is deliberately NOT the same
        as "not sitting" - the caller holds the previous verdict rather than
        counting it against the sitting streak.
        """
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

        # Feed the stillness history every readable frame, regardless of what
        # we end up deciding. Doing this inside the posture branch would only
        # sample the frames that already agreed with us.
        if person is not None and now is not None:
            person.record_hip(hip_centre, now)

        torso_angle = self._angle_from_vertical(shoulder_centre, hip_centre)

        debug = [] if self.DEBUG_POSTURE else None

        # ---- 1. Body-relative test ------------------------------------
        if self._is_sitting(kp, conf, torso_angle, torso_len, box, frame_h,
                            shoulder_centre, debug):
            if debug:
                print("SITTING     | " + " | ".join(debug))
            return "sitting"
        if debug:
            print(f"not sitting | torso={torso_angle:.0f} | " + " | ".join(debug))

        # ---- 2. Scene context, for near-vertical torsos only ----------
        # A straight-legged stander and someone sitting upright look identical
        # by torso angle alone, so gather the independent evidence before
        # settling for "not sitting". Anything with a folded torso has already
        # been judged on its geometry above and is left alone.
        if torso_angle < TORSO_UPRIGHT_MAX:
            left_bent = self._leg_is_bent(kp, conf, L_HIP, L_KNEE, L_ANKLE,
                                          torso_len, debug)
            right_bent = self._leg_is_bent(kp, conf, R_HIP, R_KNEE, R_ANKLE,
                                           torso_len, debug)
            knees_bent = bool(left_bent or right_bent)

            foot_point = self._foot_point(kp, conf, box)
            over_surface, at_seat_floor = self._seat_evidence(
                hip_centre, foot_point, torso_len, debug)
            still = (self._hip_is_still(person, now, torso_len, debug)
                     if person is not None and now is not None else None)

            # Seat evidence is REQUIRED before promoting to "sitting":
            # stillness alone is just as consistent with standing still, and
            # bent knees alone is just as consistent with crouching. When the
            # floor plane is calibrated we insist on it too, since the
            # image-space test alone cannot tell in-front-of from on-top-of.
            if at_seat_floor is not None:
                seat_evidence = bool(over_surface and at_seat_floor)
            else:
                seat_evidence = bool(over_surface)

            if seat_evidence and (still is True or knees_bent):
                if debug:
                    print("SITTING(ctx)| " + " | ".join(debug))
                return "sitting"

        return "not sitting"

    # ------------------------------------------------------------------
    # Ground plane calibration (interactive)
    # ------------------------------------------------------------------

    def calibrate_ground_plane(self, frame):
        """Click the four corners of a known floor rectangle.

        Order: near-left, near-right, far-right, far-left. The clicked points
        are printed so they can be pasted into GROUND_PLANE_IMAGE_POINTS and
        reused - this is a per-camera constant, not something to redo every
        run.
        """
        self._calib_clicks = []
        window = 'calibrate ground plane'
        preview = frame.copy()

        def on_click(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(self._calib_clicks) < 4:
                self._calib_clicks.append([x, y])
                cv2.circle(preview, (x, y), 5, COLOUR_CYAN, -1)
                cv2.putText(preview, str(len(self._calib_clicks)), (x + 8, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOUR_CYAN, 2)

        cv2.namedWindow(window)
        cv2.setMouseCallback(window, on_click)
        labels = ["near-left", "near-right", "far-right", "far-left"]
        while len(self._calib_clicks) < 4:
            shown = preview.copy()
            cv2.putText(shown, f"Click {labels[len(self._calib_clicks)]}"
                               f"  (ESC to cancel)", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOUR_WHITE, 2)
            cv2.imshow(window, shown)
            if (cv2.waitKey(20) & 0xFF) == 27:      # ESC
                cv2.destroyWindow(window)
                return
        cv2.destroyWindow(window)

        self.ground = GroundPlane.from_rectangle(self._calib_clicks,
                                                 GROUND_RECT_WIDTH_M,
                                                 GROUND_RECT_DEPTH_M)
        # Seats were bound to the OLD plane (or to none). Re-bind them.
        self.seats.ground = self.ground
        for seat in self.seats.seats():
            seat.bind_to_ground(self.ground)

        print("\nGROUND_PLANE_IMAGE_POINTS = "
              f"{self._calib_clicks}")
        print(f"  (rectangle assumed {GROUND_RECT_WIDTH_M} m wide x "
              f"{GROUND_RECT_DEPTH_M} m deep - paste the line above into the "
              f"constants to persist)\n")

    def draw_ground_plane(self, frame):
        if not self.ground.ok:
            return
        pts = self._calib_clicks or GROUND_PLANE_IMAGE_POINTS
        if not pts or len(pts) < 4:
            return
        cv2.polylines(frame, [np.array(pts, dtype=np.int32)], True,
                      COLOUR_CYAN, 1)

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
            now = time.monotonic() if video_time is None else video_time

            # One-off calibration before anything else touches the frame.
            if CALIBRATE_ON_START and not self.ground.ok and not self._calib_clicks:
                self.calibrate_ground_plane(frame)

            # Startup-only furniture detection. Silently a no-op once locked.
            if not self.seats.finalised:
                self.seats.observe(frame)

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

                # boxes=False / labels=False: ultralytics would draw its own
                # class-coloured boxes, which we cannot recolour per alert
                # state. We keep its skeleton rendering and draw the boxes and
                # ID labels ourselves below.
                annotated_frame = results[0].plot(
                    boxes=False,
                    labels=False,
                    kpt_line=True,   # draw skeleton lines between keypoints
                    kpt_radius=5,    # keypoint dot size
                )
                for i, person_id in enumerate(ids):
                    person = self.person_posture.get(person_id)
                    if person is None:
                        person = Person(person_id)
                        self.person_posture[person_id] = person

                    box = boxes[i]
                    x1, y1, x2, y2 = (int(box[0]), int(box[1]),
                                      int(box[2]), int(box[3]))
                    box_midpoint = (x1 + abs(x1 - x2) // 2,
                                    y1 + abs(y1 - y2) // 2)
                    kp = all_kp[i]
                    confidence = all_conf[i]

                    posture = self.classify_posture(kp=kp, conf=confidence,
                                                    box=box, frame_h=frame_h,
                                                    person=person, now=now)

                    # An unreadable frame is not evidence that the person
                    # changed posture. Hold the last known state rather than
                    # advancing, which would erase the label - and break the
                    # sitting streak - on every frame with dodgy keypoints.
                    if posture is not None:
                        position = person.manage_person_posture(
                            posture, video_time=video_time)
                    else:
                        position = person.current_position   # hold, don't advance

                    # --- Evaluate the alert BEFORE drawing ----------------
                    # The box colour depends on alert state, so the latch has
                    # to be up to date before anything is rendered. Latching
                    # is what makes the box and banner survive dropped
                    # detections and momentary misclassification.
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

                    # --- Draw ---------------------------------------------
                    outline = person.box_colour()
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2),
                                  outline, BOX_THICKNESS)
                    cv2.putText(annotated_frame, f"id:{person_id}",
                                (x1, max(y1 - 6, 14)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                outline, 2, cv2.LINE_AA)

                    if position is not None:
                        cv2.putText(annotated_frame, position, box_midpoint,
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                    COLOUR_BLUE, 2, cv2.LINE_AA)

            display_frame = frame if annotated_frame is None else annotated_frame

            # Scene overlays. Drawn after the people so the cached geometry is
            # visible on top - it is what you are checking when tuning.
            self.seats.draw(display_frame)
            self.draw_ground_plane(display_frame)

            cv2.putText(display_frame, f"FPS: {int(self.fps)}", (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, COLOUR_GREEN, 2, cv2.LINE_AA)

            # Stacked so several seated people do not overwrite each other.
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
            elif key == ord('c'):
                self.calibrate_ground_plane(frame)
            elif key == ord('a'):
                # Acknowledge every open alert - stands in for the staff-
                # facing acknowledgement the real system would have.
                for p in self.person_posture.values():
                    p.acknowledge()

        cam.release()
        cv2.destroyAllWindows()

    # TODO
    # Add the ID hand-off: on a new track ID, inherit state from a Person lost
    # within the last second whose last box was nearby. Without it, a tracker
    # ID switch on a seated resident silently restarts their sitting timer, so
    # a long sit is never reported - the failure mode is a MISSED alert, not a
    # false one, which is exactly the kind that goes unnoticed in testing.


class VideoMode(SittingDetector):
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


class CameraMode(SittingDetector):
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
    video_sitting_detector = VideoMode(video_footage_path)
    video_sitting_detector.DEBUG_POSTURE = True   # set False once tuned
    video_sitting_detector.run()