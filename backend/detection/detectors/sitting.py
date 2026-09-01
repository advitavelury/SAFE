"""
Sitting detection, ported onto the shared per-frame pipeline.

=============================================================================
WHAT THIS IS RELATIVE TO THE ORIGINAL sitting_detector.py

The original file ran its own segmentation model as the primary tracker (so
partially-visible people stayed tracked even with no readable pose), matched
pose keypoints onto those tracks, and used the resulting mask for silhouette
geometry and real floor-contact points. It also calibrated a ground-plane
homography and ran a one-off furniture detector, so a near-vertical torso
(upright sitting vs. straight-legged standing - genuinely ambiguous from body
geometry alone) could be resolved with seat/floor/stillness evidence.

None of that fits the interface this codebase's detectors are built around.
Program.run() (detection.py) runs ONE pose model, tracks everyone once per
frame, and hands every detector the same already-tracked Person - keypoints,
box, torso_len/torso_angle already computed - via check_detector(ctx, person),
exactly as FallDetector and IsolationDetector consume it. There is no mask,
no second model, and no per-detector tracking identity to attach scene
geometry to.

So this port keeps the CORE classifier and the timing/alert state machine,
and drops everything that depended on segmentation, the ground plane, or seat
detection:

  KEPT    - primary test: vertical hip->knee drop in units of torso_len.
            This is the load-bearing test and needs nothing but the pose
            keypoints Program already extracts.
  KEPT    - corroborating hip/knee angle tests, gated on limb length so a
            foreshortened limb doesn't contribute a meaningless angle.
  KEPT    - the torso-angle gate that excludes lying down (same leg geometry
            as sitting, different torso), with a box-aspect fallback for the
            rare frame where torso_angle itself couldn't be measured.
  KEPT    - the sustained-observations + sustained-time alert rule, and the
            "None is not the same as not-sitting" rule for unreadable frames.
  DROPPED - segmentation-primary tracking, silhouette/mask statistics, real
            floor-contact points (falls back to nothing - there is no mask to
            fall back to a box FROM here, Program only ever gives us the box).
  DROPPED - ground-plane homography, seat detection, hip-stillness. These
            existed specifically to disambiguate a near-vertical torso via
            scene context; without them that one case just falls through to
            "not sitting" on the leg tests, which is an honest degradation,
            not a silent one - see classify_posture's docstring.

If scene-context disambiguation turns out to matter for real footage, it can
be added back later, but it needs Program's main loop extended to run a
second model and thread scene state through - a bigger change than this file.
=============================================================================
"""

import math
from datetime import timedelta

from person import Person
from frame_context import FrameContext
from overlay import draw_label, draw_box

# COCO keypoint indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

# --- posture classifier thresholds -----------------------------------------

# Torso shorter than this (pixels) makes every ratio below too noisy to trust.
# Same value/reasoning as detection.py's own MIN_TORSO_PX gate on torso_angle.
MIN_TORSO_PX = 8

# PRIMARY test: vertical hip -> knee drop, in units of the person's own torso
# length.
#   standing -> ~1.0-1.2 (knee a full femur below the hip)
#   sitting  -> ~0.0-0.4 (knee at roughly hip height)
# Only an upper bound: a reclining person with their feet up puts the knee
# ABOVE the hip, which is negative, and is still seated.
KNEE_DROP_SEATED_MAX = 0.55

# Corroborating angle tests, used only when the limb projects long enough to
# be trustworthy - a foreshortened limb makes any angle read off it noise.
MIN_SEGMENT_RATIO = 0.30
HIP_BENT_MIN, HIP_BENT_MAX = 25.0, 130.0     # shoulder-hip-knee angle
KNEE_BENT_MIN, KNEE_BENT_MAX = 45.0, 140.0   # hip-knee-ankle angle

# Corroborating femur/tibia ratio: hip->knee vertical drop over hip->ankle
# vertical drop. A seated leg's downward extent comes mostly from the shin
# (thigh roughly level, shin dropping to the floor) so this ratio stays
# small; a standing/extended leg's does not. Vertical-only, same reasoning as
# KNEE_DROP_SEATED_MAX above. Only trusted once shin_len clears
# MIN_SEGMENT_RATIO - that guard already establishes the ankle is far enough
# from the knee for its position to be meaningful, not noise.
FEMUR_TIBIA_SEATED_MAX = 0.49

# Torso gate: sitting has to EXCLUDE lying down, which shares the same leg
# geometry (knee near hip height) but has a horizontal, not vertical, torso.
TORSO_FOLDED_MAX = 75.0

# Box-aspect fallback, used only on the rare frame where torso_angle itself
# could not be measured (torso too short). Weaker than the torso-angle test -
# the box also contains furniture/background, not just the person - but still
# catches an obviously wide/horizontal box.
SITTING_MIN_BOX_ASPECT = 0.75

# --- timing thresholds -------------------------------------------------------

# How long a continuous run of non-sitting reads is tolerated before the
# sitting streak breaks. Pose classification flickers frame-to-frame on
# subtle movement (a shift in the chair, an occluded leg for a moment), so
# this is a REAL-TIME duration, not a frame count - it has to survive that
# flicker regardless of the video's frame rate. A brief dip back to "sitting"
# resets this window (see manage_person_posture), so only a sustained
# minute-plus of genuinely not sitting breaks the streak.
# Unreadable frames (classify_posture -> None) never reach manage_person_posture
# at all, so they don't count either way.
SITTING_BREAK_SECONDS = 60.0

# --- box + label rendering ---------------------------------------------------

# LABEL_Y_OFFSET staggers this detector's per-person label below the box
# midpoint so it doesn't overlap the other detectors' labels - see fall.py,
# wandering.py, isolation.py for their own offsets.
LABEL_FONT_SCALE = 0.5
LABEL_THICKNESS = 1
LABEL_Y_OFFSET = 60
LABEL_COLOR = (0, 128, 0)   # BGR: green
ALERT_COLOR = (0, 0, 255)  # BGR: red (scarlet)

# Graded box outline around a sitting person: unmarked while under the
# warning fraction, amber from the halfway point, scarlet once the full
# threshold is reached (matching alert_sitting_event).
SITTING_WARNING_FRACTION = 0.5   # fraction of threshold_seconds -> amber
BOX_COLOR_WARNING = (0, 165, 255)  # BGR: amber
BOX_COLOR_ALERT = (0, 0, 255)      # BGR: scarlet
BOX_THICKNESS = 2


class SittingDetector():
    def __init__(self, threshold_time: timedelta):
        self.threshold_seconds = threshold_time.total_seconds()

    # ------------------------------------------------------------------
    # Posture classification
    # ------------------------------------------------------------------

    def _leg_looks_seated(self, person: Person, shoulder_centre, hip_i, knee_i,
                          ankle_i, torso_len):
        """Seated geometry for one leg. True / False / None.

        None means "cannot judge this leg this frame" (hip or knee not
        confidently detected) and is deliberately distinct from False, so the
        caller can ignore an unusable leg rather than count it as evidence
        against sitting - in a side-on view, or at a desk, the far/occluded
        leg is unreadable most of the time.
        """
        hip = person._point(hip_i)
        knee = person._point(knee_i)
        if hip is None or knee is None:
            return None

        # ---- PRIMARY: vertical drop, normalised by torso length ----
        knee_drop = (knee[1] - hip[1]) / torso_len
        if knee_drop > KNEE_DROP_SEATED_MAX:
            return False        # knee hangs a femur below the hip -> standing

        # ---- CORROBORATION: only when the thigh projects long enough ----
        thigh_len = math.hypot(knee[0] - hip[0], knee[1] - hip[1])
        if thigh_len < MIN_SEGMENT_RATIO * torso_len:
            return True         # foreshortened - the drop test stands alone

        hip_angle = person._joint_angle(shoulder_centre, hip, knee)
        if hip_angle is not None and not (HIP_BENT_MIN <= hip_angle <= HIP_BENT_MAX):
            return False

        ankle = person._point(ankle_i)
        if ankle is not None:
            shin_len = math.hypot(ankle[0] - knee[0], ankle[1] - knee[1])
            if shin_len >= MIN_SEGMENT_RATIO * torso_len:
                knee_angle = person._joint_angle(hip, knee, ankle)
                if knee_angle is not None and not (KNEE_BENT_MIN <= knee_angle <= KNEE_BENT_MAX):
                    return False

                # hip_ankle_drop <= 0 means the ankle is at or above the hip
                # (e.g. reclining with feet up) - the ratio isn't meaningful
                # there, so it's skipped rather than forced.
                hip_ankle_drop = ankle[1] - hip[1]
                if hip_ankle_drop > 0:
                    femur_tibia_ratio = (knee[1] - hip[1]) / hip_ankle_drop
                    if femur_tibia_ratio > FEMUR_TIBIA_SEATED_MAX:
                        return False

        return True

    def classify_posture(self, person: Person):
        """Returns "sitting", "not sitting", or None.

        None means the frame gave us nothing to classify from - shoulders/
        hips not confidently detected, torso too short to trust, or neither
        leg readable - and is deliberately NOT the same as "not sitting":
        the caller must hold the previous state rather than counting an
        unreadable frame against the sitting streak, exactly like
        FallDetector.classify_posture does for its own postures.
        """
        shoulder_centre = person._midpoint(L_SHOULDER, R_SHOULDER)
        hip_centre = person._midpoint(L_HIP, R_HIP)
        if shoulder_centre is None or hip_centre is None:
            return None

        # Torso length is our scale unit: it is a rigid segment, so it tracks
        # the person's apparent distance from the camera without changing
        # much between postures. detection.py computes it once per frame and
        # shares it across every detector.
        torso_len = person.torso_len
        if torso_len is None or torso_len < MIN_TORSO_PX:
            return None   # too small/foreshortened to trust any ratio below

        x1, y1, x2, y2 = person.box_coords
        box_w, box_h = max(abs(x2 - x1), 1), max(abs(y2 - y1), 1)

        # ---- exclude lying down: same leg geometry, different torso ----
        torso_angle = person.torso_angle   # already computed once per frame
        if torso_angle is not None:
            if torso_angle > TORSO_FOLDED_MAX:
                print(f"Person {person.id} sitting reject: torso angle "
                      f"{torso_angle:.0f} deg (lying)")
                return "not sitting"
        elif box_h / box_w < SITTING_MIN_BOX_ASPECT:
            print(f"Person {person.id} sitting reject: box aspect "
                  f"{box_h / box_w:.2f} (lying)")
            return "not sitting"

        left = self._leg_looks_seated(person, shoulder_centre, L_HIP, L_KNEE,
                                      L_ANKLE, torso_len)
        right = self._leg_looks_seated(person, shoulder_centre, R_HIP, R_KNEE,
                                       R_ANKLE, torso_len)

        # any() rather than all(): a desk, a chair arm, or the person's own
        # body occludes one leg constantly, and when both legs are clean they
        # are near-parallel and agree anyway.
        usable = [v for v in (left, right) if v is not None]
        if not usable:
            return None            # neither leg readable this frame - hold
        if any(usable):
            return "sitting"
        return "not sitting"

    # ------------------------------------------------------------------
    # Timing / alert state machine
    # ------------------------------------------------------------------

    def manage_person_posture(self, posture: str, person: Person, frame_time):
        """Feed one READABLE observation (classify_posture must not have
        returned None). All state that outlives a single frame lives on the
        Person itself - Program already keys people by track id, so there is
        no need for SittingDetector to keep its own id-keyed dict, unlike
        IsolationDetector.

        A "not sitting" read does not immediately drop the streak: it starts
        (or continues) person.non_sitting_since, and sitting_since is only
        cleared once that run of non-sitting reads has lasted
        SITTING_BREAK_SECONDS uninterrupted. A single flicker back to
        "sitting" - a subtle movement misread as standing for a frame or two
        - resets non_sitting_since and the sitting timer just keeps counting
        through it, exactly as if the flicker never happened.
        """
        posture = posture.lower()
        if posture == "sitting":
            person.non_sitting_since = None
            if person.sitting_since is None:
                person.sitting_since = frame_time
        else:
            if person.non_sitting_since is None:
                person.non_sitting_since = frame_time
            elif abs(frame_time - person.non_sitting_since) >= SITTING_BREAK_SECONDS:
                person.sitting_since = None
                person.sitting_alerted = False
        person.sitting_position = posture
        return person.sitting_position

    def alert_sitting_event(self, person: Person, frame_time) -> bool:
        """Has the current sitting streak exceeded the threshold?

        Keyed off sitting_since rather than sitting_position, so an
        unreadable frame or a momentary misclassification does not drop the
        alert - same reasoning as FallDetector.alert_fall_event.
        """
        if person.sitting_since is None:
            return False
        return abs(frame_time - person.sitting_since) >= self.threshold_seconds

    def sitting_box_color(self, person: Person, frame_time):
        """Graded box outline colour for the current sitting streak: None
        (no box) below the warning fraction, amber from the halfway point,
        scarlet once alert_sitting_event's threshold is reached."""
        if person.sitting_since is None:
            return None
        seconds = abs(frame_time - person.sitting_since)
        if seconds >= self.threshold_seconds:
            return BOX_COLOR_ALERT
        if seconds >= self.threshold_seconds * SITTING_WARNING_FRACTION:
            return BOX_COLOR_WARNING
        return None

    def check_detector(self, ctx: FrameContext, person: Person):
        frame = ctx.frame
        frame_time = ctx.frame_time

        posture = self.classify_posture(person=person)
        if posture is None:  # this could happen when the frame could not pick up valid keypoints
            return frame

        position = self.manage_person_posture(posture, person=person,
                                               frame_time=frame_time)
        box_midpoint = person.box_midpoint()
        label_point = (box_midpoint[0], box_midpoint[1] + LABEL_Y_OFFSET)
        draw_label(frame, position, label_point, LABEL_FONT_SCALE, LABEL_COLOR, LABEL_THICKNESS)

        box_color = self.sitting_box_color(person=person, frame_time=frame_time)
        if box_color is not None:
            draw_box(frame, person.box_coords, box_color, BOX_THICKNESS)

        alert = self.alert_sitting_event(person=person, frame_time=frame_time)
        if alert:
            seconds = abs(frame_time - person.sitting_since)
            draw_label(frame, f"Person {person.id} has been sitting for {seconds:.0f}s",
                       (30, 60), LABEL_FONT_SCALE, ALERT_COLOR, LABEL_THICKNESS)
            print(f"Person {person.id} has been sitting for over "
                  f"{self.threshold_seconds:.0f}s =========================")
            person.sitting_alerted = True
        return frame