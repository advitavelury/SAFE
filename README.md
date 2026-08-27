# SAFE

**Smart Assisted Fall and Emergency**

SAFE is a computer-vision prototype for detecting possible distress events in aged-care environments. The project uses YOLO-based person detection and pose tracking to monitor posture and movement cues from a standard camera feed, then display visual alerts when a resident may need staff attention.

This is a decision-support prototype for FIT3161 / FIT3162. It is not a medical device and should not be used as a clinical diagnostic system.

## Project Focus

The project explores practical, camera-observable distress events that could occur in aged-care homes:

- Fall detection
- Prolonged sitting or inactivity
- Pacing or repeated movement patterns
- Wandering at unusual hours
- Dashboard-based alert and incident logging

The current implementation is focused on YOLO-based fall detection and prolonged sitting detection. Pacing, wandering, and dashboard integration are planned next-stage features.

## Current Features

### Fall Detection

- Uses YOLO pose tracking to detect people in the frame.
- Tracks each person with ByteTrack IDs.
- Classifies posture as standing, falling, or lying down.
- Confirms a fall only after the person remains lying down for a sustained period.
- Uses recovery grace logic so one noisy frame does not immediately cancel a fall state.
- Draws skeletons, bounding boxes, posture labels, FPS, and fall alerts on the video frame.

### Prolonged Sitting Detection

- Uses YOLO pose keypoints to classify sitting posture.
- Tracks how long each person has remained seated.
- Raises an alert after the sitting threshold is exceeded.
- Uses repeated observations so one bad frame does not reset the sitting timer.
- Supports manual acknowledgement of alerts by pressing `a`.

### Prototype Support

- Supports video-file testing through `VideoMode`.
- Supports webcam input through `CameraMode`.
- Includes sample testing footage for fall and sitting detection.
- Includes YOLO model weights and ByteTrack configuration in `backend/detection`.

## Tech Stack

- Python
- OpenCV
- Ultralytics YOLO
- YOLO pose model
- ByteTrack
- NumPy
- MediaPipe prototype scripts

## Repository Structure

```text
SAFE/
├── README.md
└── backend/
    └── detection/
        ├── bytetrack.yaml
        ├── yolo26n-pose.pt
        ├── yolov8n.pt
        ├── pose_landmarker_lite.task
        ├── fall detection/
        │   ├── yolo_detection.py
        │   ├── MediaPipe&Yolo.py
        │   └── testing footage/
        │       └── Fall test.mp4
        └── distress detection/
            ├── yolo_detection.py
            ├── MediaPipe&Yolo.py
            └── sitting testing footage/
                ├── Test_1.avi
                ├── Test_2.avi
                ├── Test_3.avi
                ├── Test_4.avi
                └── Test_5.avi
```

## Setup

Clone the repository:

```bash
git clone https://github.com/advitavelury/SAFE.git
cd SAFE
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install ultralytics opencv-python numpy mediapipe
```

If OpenCV window display fails on your machine, try:

```bash
pip install opencv-contrib-python
```

## Running the Project

Because some folders contain spaces, keep the file paths in quotes.

Run the YOLO fall-detection demo:

```bash
python "backend/detection/fall detection/yolo_detection.py"
```

Run the YOLO distress-detection demo:

```bash
python "backend/detection/distress detection/yolo_detection.py"
```

By default, the scripts currently run against included test footage. To test with a webcam, use the existing `CameraMode` class in the relevant script instead of `VideoMode`.

Example:

```python
if __name__ == "__main__":
    detector = CameraMode()
    detector.run()
```

## Keyboard Controls

When running video mode:

- `q` quits the demo.
- `space` pauses or resumes playback.
- `n` advances one frame while paused.
- `a` acknowledges open alerts in the distress-detection script.

## Running Tests

The unit tests focus on detector state logic instead of loading YOLO models, webcams, or video files. See [TESTING.md](TESTING.md) for the testing strategy, test plan, current test report, and manual test-log template.

Run all tests from the project root:

```bash
python3 -m unittest discover -s tests -v
```

Current test coverage includes:

- Fall state transitions and alert timing.
- Fall recovery grace period.
- Prolonged sitting alert timing.
- Prolonged sitting reset behaviour after repeated non-sitting observations.
- Alert acknowledgement and bounding-box alert colour state.
- Pacing test placeholder, currently skipped until pacing is implemented as a testable module.

## Detection Notes

The fall detector uses posture and time-based logic:

- A person is tracked frame-by-frame using YOLO and ByteTrack.
- Pose keypoints are used to estimate torso angle and body posture.
- A fall is only alerted after an upright-to-lying transition persists long enough.
- Bounding boxes and alert banners stay visible while the alert is active.

The prolonged sitting detector uses seated posture geometry:

- Hip, knee, shoulder, and ankle keypoints are compared.
- Sitting is detected using knee-drop and corroborating body geometry checks.
- The sitting timer is not reset by a single unreadable or noisy frame.

Current thresholds are tuned for prototype testing. Real aged-care use would require longer thresholds, clinical input, privacy review, and proper validation.

## Project Scope

SAFE focuses on events that can reasonably be observed using a camera. The project does not claim to detect medical conditions such as dehydration, stroke, heart rate changes, oxygen levels, or breathing difficulty.

The goal is to support staff awareness by surfacing possible incidents that may need human review.

## Planned Work

- Add pacing detection using person movement history and direction changes.
- Add wandering-at-unusual-hours detection using configurable time windows.
- Add structured incident/event logs.
- Connect detection events to a React dashboard.
- Add configurable thresholds for demo and testing scenarios.
- Add unit tests for posture state, sitting timers, and movement-event logic.
- Improve README and test documentation as features mature.

## Privacy and Safety Considerations

SAFE is intended for a controlled student-project environment. Before any real deployment, the system would need:

- Consent and ethics review.
- Clear data-retention rules.
- Restricted staff-only access.
- Face blurring or masking where appropriate.
- Validation against realistic aged-care scenarios.
- Human review of every alert before action is taken.

## Team

FIT3161 / FIT3162 group project.

Team members:

- Advita
- Zoe
- Shadrach
- Phuc
- Filbert

Add student IDs and group number here if required for submission.
