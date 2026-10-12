"""Shared saved-media redaction. Raw frames must never be persisted."""
import cv2
import numpy as np


def redact_recording_frame(frame, results):
    # Hide untracked people/background instead of relying on face detection there.
    safe = np.zeros_like(frame)
    if not results or results[0].keypoints is None:
        return safe
    result = results[0]
    boxes = result.boxes.xyxy.cpu().numpy()
    points = result.keypoints.xy.cpu().numpy()
    confidence = result.keypoints.conf
    if confidence is None:
        return safe
    confidence = confidence.cpu().numpy()
    return redact_pose_frame(frame, boxes, points, confidence)


def redact_pose_frame(frame, boxes, points, confidence):
    """Redact all observed people; uncertain people and background stay hidden."""
    safe = np.zeros_like(frame)
    height, width = frame.shape[:2]
    regions = []
    masks = []
    for box, kp, conf in zip(boxes, points, confidence):
        if not np.isfinite(box).all():
            continue
        x1, y1, x2, y2 = np.rint(box).astype(int)
        x1, x2 = np.clip([x1, x2], 0, width)
        y1, y2 = np.clip([y1, y2], 0, height)
        if x2 <= x1 or y2 <= y1:
            continue
        # Require observed face AND shoulder landmarks. Inferred head positions
        # alone are not sufficient to expose the rest of a recorded person.
        face = [kp[i] for i in (0, 1, 2) if conf[i] >= 0.5 and np.isfinite(kp[i]).all()]
        if (not face or not all(x1 <= p[0] < x2 and y1 <= p[1] < y2 for p in face)
                or not all(conf[i] >= 0.5 and np.isfinite(kp[i]).all() for i in (5, 6))):
            masks.append((x1, y1, x2, y2))
            continue
        head = np.array(face + [kp[5], kp[6]])
        margin = max(16, int(np.linalg.norm(kp[5] - kp[6]) * 0.6))
        hx1 = max(0, int(head[:, 0].min()) - margin)
        hy1 = max(0, int(head[:, 1].min()) - margin)
        hx2 = min(width, int(head[:, 0].max()) + margin)
        hy2 = min(height, int(head[:, 1].max()) + margin)
        if hx2 <= hx1 or hy2 <= hy1:
            masks.append((x1, y1, x2, y2))
            continue
        safe[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        regions.append((hx1, hy1, hx2, hy2))

    # Redact after compositing ALL people so an overlapping box cannot restore
    # someone else's face. Very coarse pixelation precedes the blur.
    for x1, y1, x2, y2 in regions:
        region = safe[y1:y2, x1:x2]
        coarse = cv2.resize(region, (3, 3), interpolation=cv2.INTER_AREA)
        coarse = cv2.resize(coarse, (x2-x1, y2-y1), interpolation=cv2.INTER_NEAREST)
        safe[y1:y2, x1:x2] = cv2.GaussianBlur(coarse, (31, 31), 0)
    for x1, y1, x2, y2 in masks:
        safe[y1:y2, x1:x2] = 0
    return safe
