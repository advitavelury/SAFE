# SAFE Testing Plan and Report

This document records the current testing strategy, test plan, and test report for SAFE.

SAFE is a student project prototype for camera-observable distress-event detection in aged-care environments. Testing focuses on verifying detector logic, reducing false alerts, and documenting what is currently working versus what still needs validation.

## Testing Strategy

SAFE uses a mixed testing strategy:

- **Automated unit tests** for small logic units such as posture-state transitions, alert timers, and alert acknowledgement.
- **Manual video testing** using stored fall and sitting footage.
- **Manual webcam testing** for early usability and feasibility checks.
- **Future integration testing** between detection events and the React dashboard.
- **Future acceptance testing** against realistic aged-care workflow expectations.

The current automated tests do not run YOLO, load model files, open webcams, or play videos. They test the detector state logic directly so that tests are fast, repeatable, and suitable for regression testing.

## Testing Objectives

The main objectives are to:

- Detect logic bugs early during development.
- Confirm that fall alerts only trigger after the expected posture sequence and hold time.
- Confirm that prolonged sitting alerts trigger only after the sitting threshold is reached.
- Confirm that short noisy posture changes do not incorrectly reset alert timers.
- Keep tests independent from hardware, camera access, and video-file availability.
- Provide clear evidence for sprint reviews, sign-off, and project reporting.

## Test Scope

### In Scope

- Fall state transitions.
- Fall alert timing.
- Fall recovery grace period.
- Prolonged sitting alert timing.
- Prolonged sitting reset behaviour.
- Alert acknowledgement.
- Bounding-box colour state for active alerts.
- Placeholder coverage for pacing until the pacing detector is implemented.

### Out of Scope for Current Unit Tests

- YOLO model accuracy.
- OpenCV window rendering.
- Webcam access.
- Video playback.
- Full dashboard integration.
- Clinical validation.

These items require integration, system, or acceptance testing rather than unit testing.

## Test Levels

| Test level | Purpose | Current status |
|---|---|---|
| Unit testing | Test small functions/classes independently | Implemented for fall and prolonged sitting logic |
| Integration testing | Test detection events flowing into logs/dashboard | Planned |
| System testing | Test full camera/video workflow end-to-end | Manual testing in progress |
| Acceptance testing | Validate whether the prototype supports aged-care staff workflow | Planned |

## Automated Unit Test Command

Run from the project root:

```bash
python3 -m unittest discover -s tests -v
```

## Current Unit Test Report

Test run date: **2026-08-27**

Tester: **Advita / SAFE development team**

Command:

```bash
python3 -m unittest discover -s tests -v
```

Result summary:

- Tests run: 8
- Passed: 7
- Skipped: 1
- Failed: 0

The skipped test is for pacing detection. It is intentionally skipped because pacing has not yet been implemented as a separate testable module.

## Current Test Cases

| Test case | Type | Expected result | Current result |
|---|---|---|---|
| First-seen lying posture does not trigger fall | Unit | A person already lying down when tracking starts should not immediately alert as a fall | Pass |
| Standing to falling to lying triggers after hold time | Unit | Fall alert becomes true only after the lying-down hold threshold is reached | Pass |
| Fall recovery grace clears fall state | Unit | Person must remain upright for the recovery grace period before fall state clears | Pass |
| Prolonged sitting triggers after hold time | Unit | Sitting alert becomes true after the sitting threshold is reached | Pass |
| Sitting timer survives short non-sitting noise | Unit | A few noisy standing frames should not reset the sitting timer | Pass |
| Sitting timer resets after enough non-sitting observations | Unit | Repeated non-sitting frames should reset the sitting streak | Pass |
| Acknowledge clears alert latches | Unit | Manual acknowledgement clears fall and sitting alert states | Pass |
| Pacing alerts after repeated direction changes | Unit | Pacing should alert after repeated movement/direction-change evidence | Skipped until implemented |

## Manual Test Evidence to Record

For each video or webcam test, record:

- Test ID.
- Date.
- Tester.
- Input source, such as webcam or file name.
- Distress event being tested.
- Threshold settings.
- Expected result.
- Actual result.
- Pass/fail outcome.
- Notes on false positives, false negatives, lighting, body visibility, and camera angle.

Suggested manual test table:

| Test ID | Date | Tester | Input source | Event | Expected result | Actual result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|---|
| FT-001 | [enter date] | [enter name] | Fall test video | Fall | Alert after lying-down hold time | [enter result] | [pass/fail] | [notes] |
| ST-001 | [enter date] | [enter name] | Sitting test video | Prolonged sitting | Alert after sitting threshold | [enter result] | [pass/fail] | [notes] |
| PT-001 | [enter date] | [enter name] | Webcam/video | Pacing | Alert after repeated pacing movement | [enter result] | [pass/fail] | [notes] |
| WT-001 | [enter date] | [enter name] | Webcam/video | Wandering | Alert during configured unusual-hours window | [enter result] | [pass/fail] | [notes] |

## Planned Test Improvements

- Add a dedicated pacing detector module with unit tests for movement range, repeated travel, and direction changes.
- Add a wandering detector module with unit tests for time-window logic.
- Add integration tests for event objects sent from backend detection to the frontend dashboard.
- Add dashboard tests for displaying event type, timestamp, status, and acknowledgement state.
- Add regression tests whenever detector thresholds are changed.

## Testing Limitations

- Unit tests prove the logic behaves as expected for controlled inputs, but they do not prove real-world detection accuracy.
- Camera position, lighting, occlusion, body visibility, and model confidence can all affect real detection results.
- Current thresholds are prototype/demo values and must not be treated as clinically validated.
- All alerts require human review before action.
