"""
Sitting detection - segmentation-primary, pose-supplementary.

Single responsibility: decide whether each tracked person is SITTING, and
raise an alert when they have been sitting for too long. Fall / lying-down
handling has been removed; the only reason "horizontal" is still mentioned
below is that a lying person has to be EXCLUDED from "sitting", not because
anything here reports it.

=============================================================================
ARCHITECTURE - who detects, who tracks, who classifies

The SEGMENTATION model is the primary detector and the thing ByteTrack runs
on. The POSE model runs separately and its keypoints are matched onto those
tracks by box overlap. This ordering is deliberate and it is the opposite of
the obvious arrangement, so it is worth saying why:

  A person exists whether or not we can read their pose.

Pose estimation needs a mostly-complete body. Someone half out of frame, or
behind a chair back, or lit from behind, produces a detection but not a
usable skeleton. If pose were the tracker, that person would blink out of
existence - no ID, no outline, and worse, their sitting streak would restart
every time the skeleton dropped. With segmentation as the tracker they stay
tracked, stay outlined, and simply have no posture verdict for those frames,
which the classifier already models correctly: `None` means "could not read",
which HOLDS the previous state rather than counting against the streak.

So the pipeline is:

    seg.track()  -> id + box + outline    (identity: always available)
    pose.predict() -> keypoints           (posture: available when readable)
    match by IoU -> classify

This costs two model inferences per frame, which on CPU is the single most
expensive decision in this file. Both are timed and reported on screen so
the price is measurable rather than assumed - see the `pose:`/`seg:` readout.
Set USE_SEGMENTATION = False to fall back to pose-as-tracker and compare.

WHAT THE MASK ACTUALLY BUYS US

Not just a nicer overlay. A bounding box is an axis-aligned rectangle around
a person, so it contains a great deal that is not the person: the chair they
are on, the table in front of them, the floor between their legs. Two tests
in this file were reading that contamination as if it were body shape:

  1. The silhouette gate. `box_h / box_w` was standing in for "is this
     person horizontal". A mask gives the real thing - the orientation of
     the person's own pixel distribution - which is both more accurate and
     more honest, because it can report that a curled-up blob has no
     meaningful axis at all instead of inventing one.

  2. The foot point. The bottom-centre of a box is only the feet if the box
     is tight. Sitting at a table inflates the box sideways and downwards,
     and that error goes straight into the ground-plane lookup, which is the
     one measurement that resolves depth. The lowest band of the MASK is
     actual floor contact.

Both fall back to the box when no mask is available, so nothing breaks when
segmentation is off or the seg model misses someone.

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

Every body test is measured in units of torso_len, the person's own
projected torso. That is scale-invariant, which is exactly what we want -
until the person is far enough away that torso_len is only ~20px. Then a
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
     is static, the bench does not move).

  3. HIP STILLNESS. A seated person's hip is static for many seconds; a
     stander sways and drifts. Purely temporal, so it fails independently of
     everything geometric.

All three are EVIDENCE, never overrides. Signal 2 alone has exactly the
depth ambiguity we are trying to escape (a 2D box does not know who is in
front of it), and signal 3 alone cannot tell "seated" from "standing very
still". They are only trustworthy in conjunction, which is why the
near-vertical-torso branch requires seat evidence AND a second signal.

EVENT TIMING - design notes

Every timed state follows the same rule, learned the hard way: an event must
be confirmed by a sustained NUMBER OF OBSERVATIONS as well as a sustained
INTERVAL OF TIME. Testing elapsed time alone lets two stray frames either
side of a dropout satisfy a one-second threshold on the strength of two
frames of evidence. Every threshold therefore comes in pairs: a _SECONDS and
an _OBSERVATIONS constant.
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


# =============================================================================
# DETECTION / TRACKING CONFIGURATION
# =============================================================================

# The master switch for the architecture described at the top of the file.
# True  -> segmentation detects and tracks; pose is matched on for posture.
#          People survive unreadable poses. Two inferences per frame.
# False -> pose detects, tracks AND classifies, as before. One inference per
#          frame, but anyone the pose model cannot resolve vanishes.
# Flip this and watch the on-screen timings to measure what it costs you.
USE_SEGMENTATION = True

POSE_MODEL_FILENAME = 'yolo26s-pose.pt'
SEG_MODEL_FILENAME = 'yolo26s-seg.pt'

# Detection confidence for the person segmenter. Lower than you might expect
# on purpose: a partially-visible person is exactly the case this
# architecture exists to keep, and they score lower than a whole one.
SEG_CONF = 0.30
POSE_CONF = 0.25

# A pose skeleton is attached to a track when their boxes overlap by at least
# this much. Deliberately loose - the two models draw slightly different
# boxes around the same person, and a missed match costs us a posture reading
# while a wrong match is unlikely when people are not overlapping.
POSE_MATCH_MIN_IOU = 0.45

# Below this many mask pixels the silhouette statistics are noise, so the
# Silhouette reports itself unusable and every caller falls back to the box.
MIN_MASK_PIXELS = 400

# Computing covariance over every pixel of a close-up person is wasteful when
# a few thousand samples give the same axis. Subsample above this count.
MASK_PCA_MAX_SAMPLES = 3000

# --- Drawing -------------------------------------------------------------
# The pose model's own rendering (its boxes and labels) is never used: the
# outline is the boundary now, and ultralytics cannot colour it per alert
# state anyway. Everything below is drawn by hand.
DRAW_MASK_OUTLINE = True
DRAW_MASK_FILL = True       # translucent fill inside the outline
MASK_FILL_ALPHA = 0.25
DRAW_BOX = False            # set True only to compare box vs outline
DRAW_SKELETON = True        # the pose overlay, when a skeleton was matched
DRAW_FOOT_POINT = True      # the floor-contact point fed to the ground plane
MASK_OUTLINE_THICKNESS = 2
BOX_THICKNESS = 2

# COCO 17-keypoint skeleton topology, 0-indexed. Needed because we no longer
# call results.plot() - that would draw the pose model's boxes back in.
POSE_SKELETON = [
    (15, 13), (13, 11), (16, 14), (14, 12), (11, 12),
    (5, 11), (6, 12), (5, 6), (5, 7), (6, 8), (7, 9), (8, 10),
    (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
]


# =============================================================================
# CLASSIFIER CONFIGURATION
# =============================================================================

# --- Prolonged sitting ---------------------------------------------------
# NOTE: this is a TESTING value. Clinically the concern is immobility over
# tens of minutes to hours - pressure injury risk, missed meals, someone who
# cannot get themselves back up. A few seconds in a real ward would fire on
# essentially every resident continuously. Raise to something like 1800
# (30 min) before any real deployment or demo with clinical staff.
SITTING_HOLD_SECONDS = 3.0

# Consecutive NON-sitting readings needed to break a sitting streak. Without
# it, a single misclassified frame just before the threshold silently
# restarts the timer and the alert never fires. Unreadable frames do not
# count either way - they never reach here.
SITTING_BREAK_OBSERVATIONS = 5

# Confidence required for a keypoint to be usable.
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
# Only an upper bound: a reclining person with their feet up puts the knee
# ABOVE the hip, which is negative, and is still seated.
KNEE_DROP_SEATED_MAX = 0.55

# --- Corroborating angle tests (used only when the limb projects long) ---
# Hip angle = shoulder-hip-knee. The band is wide because slouch swings it:
#   standing ~180, upright sitting ~90, hunched-forward sitting ~30
HIP_BENT_MIN, HIP_BENT_MAX = 25.0, 130.0
# Knee angle = hip-knee-ankle. Nominally 90 when seated.
KNEE_BENT_MIN, KNEE_BENT_MAX = 45.0, 140.0

# Cheap knee-bend check, used only as scene-context evidence.
BENT_KNEE_ANGLE_MAX = 150.0

# A limb shorter than this fraction of the torso is foreshortened (pointing
# at or away from the camera), so any ANGLE derived from it is noise. The
# knee drop is still valid, so this suppresses the angle tests only.
MIN_SEGMENT_RATIO = 0.30

# Torso gate. Set at 75 rather than 50 because it no longer has to reject
# "bent over at the waist" - the knee drop does that, since a bent-over
# stander still has their knees a full femur below their hips. All this has
# to exclude is a genuinely horizontal person, which is what separates
# sitting from lying curled on one side (identical leg geometry, different
# torso).
TORSO_FOLDED_MAX = 75.0

# Below this the torso reads as near-vertical, which is where the scene
# context branch runs: a straight-legged stander and someone sitting upright
# look identical by torso angle alone.
TORSO_UPRIGHT_MAX = 10.0

# --- Silhouette gate -----------------------------------------------------
# THE MASK VERSION of the old box-aspect test. Two regimes, because a
# person's pixel distribution only HAS a meaningful axis when it is
# elongated:
#
#   elongated (standing, lying)  -> trust the major axis orientation
#   compact  (seated, crouched)  -> the axis is arbitrary; fall back to the
#                                   extent ratio and stay lenient
#
# Refusing to read an axis off a round blob is the same discipline as
# MIN_SEGMENT_RATIO refusing to read an angle off a foreshortened limb: a
# measurement taken from a degenerate configuration is not a weak
# measurement, it is a meaningless one.
MIN_ELONGATION_FOR_AXIS = 1.60      # sqrt of the eigenvalue ratio
SILHOUETTE_FOLDED_MAX = 60.0        # major-axis angle from vertical, degrees
SITTING_MIN_SILHOUETTE_ASPECT = 0.70   # mask height / mask width

# Box-aspect fallback, used only when there is no usable mask.
SITTING_MIN_BOX_ASPECT = 0.75

# Fraction of the silhouette's height, measured from its lowest pixel, that
# counts as "the feet" for the floor-contact point.
FOOT_BAND_FRACTION = 0.08

# Seated shoulders sit in a band above the person's own foot line. Below the
# band (~1.0-1.3) is someone propped up on the floor; above it (~2.5-3.0) is
# standing. The upper bound matters because it catches standing even when the
# leg geometry is ambiguous - hip and shoulder height are set by the seat,
# not by which leg happens to be bent, so an extended or swinging leg cannot
# fool it. Only applied when the box is not clipped by the frame bottom.
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
SEAT_FLOOR_PROXIMITY_M = 0.45

# Homography extrapolates violently outside the calibrated quad, and explodes
# entirely near the horizon. Anything mapping beyond this many metres from the
# origin is treated as unmeasurable rather than believed.
GROUND_MAX_SANE_METRES = 50.0

# --- 2. Seat detection ---------------------------------------------------
# NOTE: standard DETECTION weights, not -pose and not -seg. It runs for the
# first SEAT_DETECT_FRAMES frames and then NEVER AGAIN: on a fixed camera the
# bench does not move, so this costs a handful of inferences at startup
# rather than one per frame. Prefer a SMALL scale - it is looking for
# furniture, and a medium model turns startup into a visible stall on CPU.
SEAT_MODEL_FILENAME = 'yolo26s.pt'
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
COLOUR_GREY = (150, 150, 150)

OUTLINE_COLOUR_NORMAL = COLOUR_GREEN
OUTLINE_COLOUR_SITTING_ALERT = COLOUR_RED
# A track with no readable pose yet. Drawn deliberately differently so it is
# obvious at a glance that the person is SEEN but not JUDGED - the whole point
# of segmentation-primary tracking.
OUTLINE_COLOUR_UNKNOWN = COLOUR_GREY


# =============================================================================
# Small shared helpers
# =============================================================================

def box_iou(a, b):
    """Intersection-over-union of two xyxy boxes."""
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


def greedy_match(boxes_a, boxes_b, min_iou):
    """Greedy one-to-one IoU matching. Returns {index_a: index_b}.

    Greedy rather than Hungarian on purpose: with a handful of people in a
    room the highest-IoU pair is essentially always correct, and the failure
    mode of greedy (two heavily overlapping people swapping) is not fixed by
    optimal assignment either - it needs appearance features.
    """
    pairs = []
    for i, ba in enumerate(boxes_a):
        for j, bb in enumerate(boxes_b):
            iou = box_iou(ba, bb)
            if iou >= min_iou:
                pairs.append((iou, i, j))
    pairs.sort(reverse=True)

    matched, used_a, used_b = {}, set(), set()
    for iou, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        matched[i] = j
        used_a.add(i)
        used_b.add(j)
    return matched


def load_model(model_path, label):
    """Load a checkpoint, preferring a local copy and falling back to the
    bare filename so ultralytics can resolve/download a standard name.

    Returns the model, or None. Bailing out on a missing file (the previous
    behaviour) silently disabled whole subsystems, which is worse than a
    one-off download.
    """
    source = model_path
    if not os.path.isfile(model_path):
        source = os.path.basename(model_path)
        print(f"{label}: '{source}' not found at\n    {model_path}\n"
              f"  falling back to the bare name - ultralytics will download "
              f"it once if it is a standard checkpoint.")
    try:
        return YOLO(source)
    except Exception as exc:                          # noqa: BLE001
        print(f"{label}: could not load '{source}' ({exc}).")
        return None


# =============================================================================
# Silhouette - the person's actual outline
# =============================================================================

class Silhouette:
    """Shape statistics computed from one person's segmentation mask.

    The mask is rasterised into an ROI the size of the detection box rather
    than the whole frame: a full-frame buffer per person per frame is a real
    cost at 1080p and buys nothing, since every statistic here is local.

    `ok` is False when there are too few pixels to say anything. Callers must
    check it and fall back to the bounding box - the mask is an upgrade, never
    a dependency.
    """

    def __init__(self, polygon, box, frame_shape):
        self.ok = False
        self.mask = None
        self.polygon = polygon
        self.area = 0
        self.aspect = None
        self.fill = None
        self.axis_angle = None      # major axis, degrees from vertical
        self.elongation = None      # sqrt(eigenvalue ratio); 1.0 = round
        self.foot_point = None

        frame_h, frame_w = frame_shape[0], frame_shape[1]
        x1 = max(int(box[0]), 0)
        y1 = max(int(box[1]), 0)
        x2 = min(int(box[2]), frame_w)
        y2 = min(int(box[3]), frame_h)
        w, h = x2 - x1, y2 - y1
        if w <= 1 or h <= 1 or polygon is None or len(polygon) < 3:
            return

        self.x_off, self.y_off = x1, y1
        mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.round(np.asarray(polygon, dtype=np.float32)
                       - np.array([x1, y1], dtype=np.float32)).astype(np.int32)
        cv2.fillPoly(mask, [pts], 1)

        ys, xs = np.nonzero(mask)
        if xs.size < MIN_MASK_PIXELS:
            return

        self.mask = mask
        self.area = int(xs.size)

        x_min, x_max = int(xs.min()), int(xs.max())
        y_min, y_max = int(ys.min()), int(ys.max())
        # +1 because the extent is inclusive of both end pixels. Without it
        # `fill` comes out slightly above 1.0, which looks like a bug in the
        # debug output even though it is only an off-by-one.
        self.width = max(x_max - x_min + 1, 1)
        self.height = max(y_max - y_min + 1, 1)
        self.aspect = self.height / self.width
        # How much of its own bounding box the person actually fills. A
        # standing person is a tall sliver (~0.3-0.4); a seated one is
        # blockier. Not used as a gate - it varies too much with clothing and
        # limb position - but printed in debug, where it is a useful sanity
        # check that the mask is tracking the person and not the chair.
        self.fill = self.area / float(self.width * self.height)

        # --- principal axis ------------------------------------------
        # Subsample first: covariance over 200k pixels gives the same answer
        # as over 3k and costs 60x more.
        if xs.size > MASK_PCA_MAX_SAMPLES:
            step = xs.size // MASK_PCA_MAX_SAMPLES
            xs_s, ys_s = xs[::step], ys[::step]
        else:
            xs_s, ys_s = xs, ys

        pts_f = np.stack([xs_s.astype(np.float64), ys_s.astype(np.float64)])
        cov = np.cov(pts_f)
        if np.all(np.isfinite(cov)):
            vals, vecs = np.linalg.eigh(cov)        # ascending
            major = vecs[:, -1]
            l_major = float(max(vals[-1], 0.0))
            l_minor = float(max(vals[0], 1e-9))
            self.elongation = math.sqrt(l_major / l_minor) if l_minor > 0 else None
            # Same convention as _angle_from_vertical: 0 deg = vertical,
            # 90 deg = horizontal.
            self.axis_angle = abs(90.0 - math.degrees(
                math.atan2(abs(float(major[1])), abs(float(major[0])))))

        # --- floor contact -------------------------------------------
        # The lowest band of the mask, in frame coordinates. This is real
        # floor contact (shoe soles), unlike the ankle keypoint which sits
        # ~10 cm above the floor and unlike the box bottom which is wherever
        # the detector decided to stop.
        band = max(int(FOOT_BAND_FRACTION * self.height), 1)
        sel = ys >= (y_max - band)
        if np.any(sel):
            self.foot_point = (float(xs[sel].mean()) + x1,
                               float(ys[sel].max()) + y1)

        self.ok = True

    def draw(self, frame, colour):
        """Outline, and optionally a translucent fill inside it."""
        if self.polygon is None or len(self.polygon) < 3:
            return
        pts = np.round(np.asarray(self.polygon, dtype=np.float32)).astype(np.int32)

        if DRAW_MASK_FILL and self.mask is not None:
            h, w = self.mask.shape
            y1, x1 = self.y_off, self.x_off
            roi = frame[y1:y1 + h, x1:x1 + w]
            if roi.shape[:2] == self.mask.shape:
                tint = np.empty_like(roi)
                tint[:] = colour
                blended = cv2.addWeighted(roi, 1.0 - MASK_FILL_ALPHA,
                                          tint, MASK_FILL_ALPHA, 0)
                # Only where the mask is set - np.where keeps this a single
                # vectorised pass rather than a per-pixel loop.
                roi[:] = np.where(self.mask[:, :, None].astype(bool), blended, roi)

        if DRAW_MASK_OUTLINE:
            cv2.polylines(frame, [pts], True, colour, MASK_OUTLINE_THICKNESS,
                          cv2.LINE_AA)


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
    and seat base points, never torso keypoints.
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
        vertically near its surface?

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
        self._accumulators = []   # [{'boxes': [...], 'cls': name, 'count': n}]
        self._frames_seen = 0
        self._finalised = False
        self._seats = []

        self.model = load_model(model_path, "SeatRegistry")
        if self.model is None:
            print("  Seat detection disabled. Body-relative tests and "
                  "stillness still run, but the scene-context promotion to "
                  "'sitting' will never fire.")
            self._finalised = True

    @property
    def finalised(self):
        return self._finalised

    def seats(self):
        return self._seats

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
                    if acc['cls'] == name and box_iou(acc['boxes'][-1], box) > 0.5:
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
            cv2.putText(frame, seat.cls_name,
                        (int(seat.x1), max(int(seat.y1) - 4, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOUR_CYAN, 1, cv2.LINE_AA)


# =============================================================================
# Tracked people
# =============================================================================

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
        so the caller holds the previous state instead. Under
        segmentation-primary tracking this happens constantly and by design -
        a half-visible person is tracked every frame and classified on none
        of them."""
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

    def alert_prolonged_sitting(self, video_time=None) -> bool:
        """Has the current sitting streak exceeded the threshold?

        Keyed off sitting_since rather than current_position, so an unreadable
        frame or a momentary misclassification does not drop the alert.
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

    def outline_colour(self):
        """Colour for this person's outline.

        Reads the LATCH, not the per-frame test, so the outline stays red
        through dropped detections and unreadable keypoints for exactly the
        same reason the banner does. Grey means "seen but never yet judged" -
        an honest third state, not a failure.
        """
        if self.sitting_alerted:
            return OUTLINE_COLOUR_SITTING_ALERT
        if self.current_position is None:
            return OUTLINE_COLOUR_UNKNOWN
        return OUTLINE_COLOUR_NORMAL

    def acknowledge(self):
        """Staff-facing hook: close the alert manually."""
        self.sitting_alerted = False


class Track:
    """One person in one frame: identity from segmentation, pose attached if
    it could be read. `kp is None` is the normal, expected case for anyone
    partially out of frame - not an error path."""

    __slots__ = ('id', 'box', 'polygon', 'silhouette', 'kp', 'conf')

    def __init__(self, id, box, polygon=None, silhouette=None, kp=None, conf=None):
        self.id = id
        self.box = box
        self.polygon = polygon
        self.silhouette = silhouette
        self.kp = kp
        self.conf = conf


# =============================================================================
# Detector
# =============================================================================

class SittingDetector(ABC):
    # Set to True on the instance to print, per person per frame, which test
    # rejected "sitting". Invaluable for tuning the thresholds above.
    DEBUG_POSTURE = False

    def __init__(self):
        # Shared model/config files live one level up, in backend/detection/,
        # so sitting detection and distress detection can both use them.
        dir = os.path.dirname(os.path.abspath(__file__))
        detection_dir = os.path.dirname(dir)
        self.detection_dir = detection_dir
        self.bytetrack_yaml_path = os.path.join(detection_dir, 'bytetrack.yaml')

        self.pose_model = load_model(
            os.path.join(detection_dir, POSE_MODEL_FILENAME), "PoseModel")
        if self.pose_model is None:
            raise RuntimeError("Pose model failed to load - there is no "
                               "posture classification without it.")

        # Segmentation is the primary detector when enabled. If it fails to
        # load we degrade to pose-as-tracker rather than refusing to run:
        # losing outlines and partial-person tracking is bad, losing the whole
        # system is worse.
        self.seg_model = None
        if USE_SEGMENTATION:
            self.seg_model = load_model(
                os.path.join(detection_dir, SEG_MODEL_FILENAME), "SegModel")
            if self.seg_model is None:
                print("  Falling back to pose-as-tracker: no outlines, and "
                      "partially-visible people will not be tracked.")
        self.seg_primary = self.seg_model is not None

        print(f"Tracking source: "
              f"{'segmentation' if self.seg_primary else 'pose'}")

        self.person_posture = {}
        self.paused = False
        self.pose_ms = 0.0
        self.seg_ms = 0.0

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
    # Detection + association
    # ------------------------------------------------------------------

    def _run_pose(self, frame, track=False):
        """Pose inference. `track=True` only in the fallback arrangement
        where pose is also the tracker."""
        t0 = time.perf_counter()
        if track:
            results = self.pose_model.track(source=frame, persist=True,
                                            classes=[0], conf=POSE_CONF,
                                            device='cpu', verbose=False,
                                            tracker=self.bytetrack_yaml_path)
        else:
            results = self.pose_model.predict(source=frame, classes=[0],
                                              conf=POSE_CONF, device='cpu',
                                              verbose=False)
        self.pose_ms = (time.perf_counter() - t0) * 1000.0
        return results

    def _run_seg(self, frame):
        """Segmentation inference, WITH tracking - this is where the IDs come
        from in the primary arrangement."""
        t0 = time.perf_counter()
        results = self.seg_model.track(source=frame, persist=True,
                                       classes=[0], conf=SEG_CONF,
                                       device='cpu', verbose=False,
                                       tracker=self.bytetrack_yaml_path)
        self.seg_ms = (time.perf_counter() - t0) * 1000.0
        return results

    def gather_tracks(self, frame):
        """One frame in, a list of Track out.

        This is the only place the two arrangements differ. Everything
        downstream sees the same Track objects either way, which is what
        keeps USE_SEGMENTATION a genuine A/B switch rather than a fork.
        """
        if self.seg_primary:
            return self._gather_seg_primary(frame)
        return self._gather_pose_primary(frame)

    def _gather_seg_primary(self, frame):
        seg_results = self._run_seg(frame)
        if not seg_results:
            return []
        r = seg_results[0]
        if r.boxes is None or r.boxes.id is None or r.masks is None:
            return []

        boxes = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int).tolist()
        polygons = r.masks.xy      # already in original-image coordinates

        tracks = []
        for i, tid in enumerate(ids):
            poly = polygons[i] if i < len(polygons) else None
            sil = Silhouette(poly, boxes[i], frame.shape)
            tracks.append(Track(id=tid, box=boxes[i], polygon=poly,
                                silhouette=sil if sil.ok else None))

        # Attach pose. A track with no match keeps kp=None and is simply not
        # classified this frame - it stays tracked and outlined.
        pose_results = self._run_pose(frame, track=False)
        if pose_results:
            pr = pose_results[0]
            if (pr.boxes is not None and pr.keypoints is not None
                    and pr.keypoints.conf is not None):
                pose_boxes = pr.boxes.xyxy.cpu().numpy()
                pose_kp = pr.keypoints.xy.cpu()
                pose_conf = pr.keypoints.conf.cpu()
                matched = greedy_match([t.box for t in tracks], pose_boxes,
                                       POSE_MATCH_MIN_IOU)
                for ti, pi in matched.items():
                    tracks[ti].kp = pose_kp[pi]
                    tracks[ti].conf = pose_conf[pi]
        return tracks

    def _gather_pose_primary(self, frame):
        """Fallback: no segmentation available, so pose detects and tracks.
        Note what is lost - no outlines, and anyone the pose model cannot
        resolve is invisible to the whole system."""
        results = self._run_pose(frame, track=True)
        self.seg_ms = 0.0
        if not results:
            return []
        r = results[0]
        if (r.boxes is None or r.boxes.id is None
                or r.keypoints is None or r.keypoints.conf is None):
            return []

        boxes = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int).tolist()
        kps = r.keypoints.xy.cpu()
        confs = r.keypoints.conf.cpu()
        return [Track(id=tid, box=boxes[i], kp=kps[i], conf=confs[i])
                for i, tid in enumerate(ids)]

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _midpoint(self, kp, conf, i, j, min_conf=KP_CONF):
        """Midpoint of two keypoints, or None if either is unreliable."""
        if conf[i] < min_conf or conf[j] < min_conf:
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

    def _foot_point(self, kp, conf, box, silhouette):
        """Where this person meets the floor, in image coordinates.

        Preference order, best first:
          1. The bottom band of the MASK. Actual floor contact - shoe soles.
          2. The ankle midpoint. A real joint, but ~10 cm above the floor,
             and it disappears whenever the feet are occluded.
          3. The bottom-centre of the box. Only correct when the box is
             tight; a table or an outstretched arm ruins it.

        This ordering matters more than it looks. The result goes straight
        into the ground-plane lookup, and that is the one measurement that
        resolves "on the bench" from "in front of the bench" - error here
        does not degrade the verdict gracefully, it inverts it.
        """
        if silhouette is not None and silhouette.foot_point is not None:
            return silhouette.foot_point
        if kp is not None and conf is not None:
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
        skipped silently when it is not.
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

    def _silhouette_allows_sitting(self, silhouette, box, debug=None):
        """Is this person's OUTLINE consistent with sitting? True/False.

        The job here is only to exclude a genuinely horizontal person - lying
        curled on one side has the same leg geometry as sitting, and shape is
        the only thing that separates them.

        Three regimes:
          - elongated mask  -> read the major axis. Best case.
          - compact mask    -> the axis is arbitrary, so do NOT read it; fall
                               back to the mask's extent ratio, leniently.
          - no mask         -> the old box-aspect test, which is the weakest
                               of the three because the box contains
                               furniture and background as well as person.
        """
        if silhouette is not None and silhouette.ok:
            if debug is not None:
                debug.append(f"sil: aspect={silhouette.aspect:.2f} "
                             f"fill={silhouette.fill:.2f} "
                             f"elong={silhouette.elongation:.2f} "
                             f"axis={silhouette.axis_angle:.0f}")
            if (silhouette.elongation is not None
                    and silhouette.elongation >= MIN_ELONGATION_FOR_AXIS
                    and silhouette.axis_angle is not None):
                if silhouette.axis_angle > SILHOUETTE_FOLDED_MAX:
                    if debug is not None:
                        debug.append(f"reject: silhouette axis "
                                     f"{silhouette.axis_angle:.0f} deg")
                    return False
                return True
            # Compact blob - no trustworthy axis.
            if silhouette.aspect < SITTING_MIN_SILHOUETTE_ASPECT:
                if debug is not None:
                    debug.append(f"reject: silhouette aspect "
                                 f"{silhouette.aspect:.2f}")
                return False
            return True

        x1, y1, x2, y2 = box
        box_w, box_h = max(x2 - x1, 1), max(y2 - y1, 1)
        if box_h / box_w < SITTING_MIN_BOX_ASPECT:
            if debug is not None:
                debug.append(f"reject: box aspect {box_h / box_w:.2f}")
            return False
        return True

    def _is_sitting(self, kp, conf, torso_angle, torso_len, box, frame_h,
                    shoulder_centre, silhouette, debug=None):
        """Torso gate, silhouette gate, both legs, then a height sanity check."""
        if torso_angle > TORSO_FOLDED_MAX:
            if debug is not None:
                debug.append(f"reject: torso {torso_angle:.0f} deg")
            return False

        if not self._silhouette_allows_sitting(silhouette, box, debug):
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

        x1, y1, x2, y2 = box
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
          at_seat_floor - floor plane. THIS is the one that resolves depth.

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
        normalise it by torso_len.
        """
        drift_px, samples = person.hip_drift(now)
        if drift_px is None or samples < STILLNESS_MIN_OBSERVATIONS:
            return None

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

    def classify_posture(self, track, frame_h, person=None, now=None):
        """Returns "sitting", "not sitting", or None.

        None means the frame was unreadable and is deliberately NOT the same
        as "not sitting" - the caller holds the previous verdict rather than
        counting it against the sitting streak. Under segmentation-primary
        tracking, `track.kp is None` (nobody could read a skeleton) lands here
        too, which is exactly right: a half-visible person is present, not
        standing.
        """
        kp, conf, box = track.kp, track.conf, track.box
        if kp is None or conf is None:
            return None

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
                            shoulder_centre, track.silhouette, debug):
            if debug:
                print(f"[{track.id}] SITTING     | " + " | ".join(debug))
            return "sitting"
        if debug:
            print(f"[{track.id}] not sitting | torso={torso_angle:.0f} | "
                  + " | ".join(debug))

        # ---- 2. Scene context, for near-vertical torsos only ----------
        # A straight-legged stander and someone sitting upright look identical
        # by torso angle alone, so gather the independent evidence before
        # settling for "not sitting".
        if torso_angle < TORSO_UPRIGHT_MAX:
            left_bent = self._leg_is_bent(kp, conf, L_HIP, L_KNEE, L_ANKLE,
                                          torso_len, debug)
            right_bent = self._leg_is_bent(kp, conf, R_HIP, R_KNEE, R_ANKLE,
                                           torso_len, debug)
            knees_bent = bool(left_bent or right_bent)

            foot_point = self._foot_point(kp, conf, box, track.silhouette)
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
                    print(f"[{track.id}] SITTING(ctx)| " + " | ".join(debug))
                return "sitting"

        return "not sitting"

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw_skeleton(self, frame, kp, conf, colour=COLOUR_BLUE):
        """Hand-rolled because results.plot() would draw the pose model's own
        boxes back in, and those are precisely what the outline replaces."""
        if kp is None or conf is None:
            return
        pts = [(int(float(kp[i][0])), int(float(kp[i][1])))
               for i in range(len(kp))]
        for a, b in POSE_SKELETON:
            if a < len(conf) and b < len(conf) and conf[a] >= KP_CONF and conf[b] >= KP_CONF:
                cv2.line(frame, pts[a], pts[b], colour, 2, cv2.LINE_AA)
        for i, (px, py) in enumerate(pts):
            if conf[i] >= KP_CONF:
                cv2.circle(frame, (px, py), 3, COLOUR_WHITE, -1)

    def draw_track(self, frame, track, person, position):
        colour = person.outline_colour()

        if track.silhouette is not None:
            track.silhouette.draw(frame, colour)
        elif track.polygon is not None and len(track.polygon) >= 3:
            # Mask too small for statistics but still worth outlining.
            pts = np.round(np.asarray(track.polygon, dtype=np.float32)).astype(np.int32)
            cv2.polylines(frame, [pts], True, colour, MASK_OUTLINE_THICKNESS,
                          cv2.LINE_AA)

        x1, y1, x2, y2 = (int(track.box[0]), int(track.box[1]),
                          int(track.box[2]), int(track.box[3]))
        if DRAW_BOX or track.polygon is None:
            # The box is the fallback boundary: with no mask, drawing nothing
            # would leave the person unmarked entirely.
            cv2.rectangle(frame, (x1, y1), (x2, y2), colour, BOX_THICKNESS)

        if DRAW_SKELETON:
            self.draw_skeleton(frame, track.kp, track.conf)

        if DRAW_FOOT_POINT:
            fp = self._foot_point(track.kp, track.conf, track.box,
                                  track.silhouette)
            cv2.drawMarker(frame, (int(fp[0]), int(fp[1])), COLOUR_AMBER,
                           cv2.MARKER_TILTED_CROSS, 12, 2)

        label = f"id:{track.id} {position if position else 'unknown'}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA)

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

        print(f"\nGROUND_PLANE_IMAGE_POINTS = {self._calib_clicks}")
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

        while True:
            ret, frame = cam.read()
            if not ret:
                break

            if self.is_video_mode():
                self.frame_index += 1
            frame_h = frame.shape[0]
            banners = []

            self.fps = self.get_fps()
            video_time = self.get_video_time() if self.is_video_mode() else None
            now = time.monotonic() if video_time is None else video_time

            # One-off calibration before anything else touches the frame.
            if CALIBRATE_ON_START and not self.ground.ok and not self._calib_clicks:
                self.calibrate_ground_plane(frame)

            # Startup-only furniture detection. Silently a no-op once locked.
            if not self.seats.finalised:
                self.seats.observe(frame)

            tracks = self.gather_tracks(frame)

            for track in tracks:
                person = self.person_posture.get(track.id)
                if person is None:
                    person = Person(track.id)
                    self.person_posture[track.id] = person

                posture = self.classify_posture(track, frame_h,
                                                person=person, now=now)

                # An unreadable frame is not evidence that the person changed
                # posture. Hold the last known state rather than advancing,
                # which would erase the label - and break the sitting streak -
                # on every frame with dodgy or absent keypoints.
                if posture is not None:
                    position = person.manage_person_posture(
                        posture, video_time=video_time)
                else:
                    position = person.current_position   # hold, don't advance

                # --- Evaluate the alert BEFORE drawing --------------------
                # The outline colour depends on alert state, so the latch has
                # to be up to date before anything is rendered.
                if person.alert_prolonged_sitting(video_time=video_time):
                    if not person.sitting_alerted:
                        print(f"Person {track.id} seated over "
                              f"{SITTING_HOLD_SECONDS:.0f}s "
                              f"-----------------------------------------")
                        person.sitting_alerted = True
                if person.sitting_alerted:
                    secs = person.seconds_seated(video_time=video_time)
                    banners.append((f"Person {track.id} seated {secs:.0f}s",
                                    COLOUR_RED))

                self.draw_track(frame, track, person, position)

            # Scene overlays. Drawn after the people so the cached geometry is
            # visible on top - it is what you are checking when tuning.
            self.seats.draw(frame)
            self.draw_ground_plane(frame)

            # Per-model timing. This is the whole justification for the
            # architecture, so it is on screen rather than buried in a log:
            # if seg + pose does not fit your frame budget, you can see it
            # immediately and flip USE_SEGMENTATION to compare.
            cv2.putText(frame, f"FPS: {int(self.fps)}   "
                               f"pose: {self.pose_ms:.0f}ms   "
                               f"seg: {self.seg_ms:.0f}ms",
                        (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        COLOUR_GREEN, 2, cv2.LINE_AA)

            for idx, (text, colour) in enumerate(banners):
                cv2.putText(frame, text, (30, 80 + idx * 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2, cv2.LINE_AA)

            cv2.imshow('frame', frame)

            # Single waitKey per iteration. Calling waitKey(1) at the top of
            # the loop AND waitKey(delay) at the bottom splits keypresses
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
    # Segmentation-primary tracking helps here (masks survive partial
    # occlusion better than skeletons) but does not remove the need.


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