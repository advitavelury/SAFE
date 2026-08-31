import numpy as np
from dataclasses import dataclass


@dataclass
class FrameContext:
    """Per-frame data shared with every detector.

    Lives in its own module (rather than in detection.py) so that detectors can
    import it for type hinting without importing the module that imports them.
    """
    frame: np.ndarray
    frame_time: float 
    occupancy: int
