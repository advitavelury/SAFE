import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
BG_COLOR = (255, 255, 255)  # white, BGR
BG_ALPHA = 0.4               # 0 = invisible, 1 = fully opaque
BG_PADDING = 4


def draw_label(frame, text, origin, font_scale, color, thickness):
    """Draw `text` at `origin` (bottom-left of the text, same convention as
    cv2.putText) on a semi-transparent white rectangle sized to fit it, so
    labels stay readable over busy video without fully blocking it out."""
    (text_w, text_h), baseline = cv2.getTextSize(text, FONT, font_scale, thickness)
    x, y = origin
    x1 = max(x - BG_PADDING, 0)
    y1 = max(y - text_h - BG_PADDING, 0)
    x2 = min(x + text_w + BG_PADDING, frame.shape[1])
    y2 = min(y + baseline + BG_PADDING, frame.shape[0])

    roi = frame[y1:y2, x1:x2]
    if roi.size > 0:
        bg = np.full_like(roi, BG_COLOR)
        cv2.addWeighted(bg, BG_ALPHA, roi, 1 - BG_ALPHA, 0, dst=roi)

    cv2.putText(frame, text, (x, y), FONT, font_scale, color, thickness, cv2.LINE_AA)


def draw_box(frame, box_coords, color, thickness=2):
    """Draw a rectangle outline around box_coords = (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = box_coords
    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness)
