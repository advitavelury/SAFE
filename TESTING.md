# SAFE Testing Plan and Report

## Local video-feed integration - 14 October 2026

- Frontend-only integration on `front-end`: reuses the existing `backend/routes.py` and `backend/streamers.py` without modifying any backend implementation file.
- Frontend: 33 tests passed, including 12 stream tests covering fragmented/coalesced multipart frames, continuous feeds over 1000 frames/40 MiB, authentication, cancellation, idle timeouts, malformed responses, size limits and decoder errors.
- Production frontend build passed with the existing large-bundle warning. `git diff --check` passed.
- Chrome integration checks passed for admin/operator roles at 1440px and 390px. The real backend `setup_routes` and `FrameStreamer` ran on loopback port 8000 with injected test-only identities and moving synthetic frames. The browser used the real Vite proxy and viewer. Pixel checks confirmed changing frames; disconnect cleared the canvas; reconnect resumed frames. Access revocation ended both roles' streams and cleared the last frame. Screenshots were inspected for mobile and desktop layout.
- The temporary test backend was stopped afterward. No camera, detector model, service-account credentials or production Firebase data were used. Real staff accounts and the intended input source still need a live smoke test. Current `backend/main.py` selects recorded-video mode.
- Existing event fixtures also exercise metadata/snapshot review separately; the viewer integration does not add recording or Firebase frame uploads. Full historical detector tests and accuracy evaluation remain outside this frontend change.
- `npm audit` reports 9 advisories in the existing Firebase/build-tool dependency tree (8 high, 1 moderate). Neither new multipart dependency is flagged; existing locked versions were not changed. Dependency upgrades need a separate review. Keep the development servers loopback-only.

## Events dashboard migration - 14 October 2026

- Work is on `front-end`, based on `main` at `dbb4760`. No backend implementation changes were made.
- Frontend: 21 tests passed, covering the backend event schema, red/amber severity, open/closed status, timestamps, staff approval and authenticated event requests.
- Firestore emulator: 6 tests passed in `demo-safe-roles`, including the real dashboard query (`events`, descending `timestamp`, limit 50), admin/operator reads, denial for unapproved users, denied browser writes, legacy-collection denial and deactivation.
- Backend authorization: all 15 tests passed after adding the already-required `alert_level` to the existing mocked event. No production credentials or camera were used.
- Production frontend build passed with the existing bundle-size warning.
- Isolated Chrome checks passed for admin/operator roles at 1440px and 390px: event list, filters, snapshot rendering, admin completion, staff read-only controls, permission-error messaging and no clip/incident API requests. A mobile table overflow was corrected. These checks used synthetic data and mocked authentication/API responses, with external production requests blocked.
- After explicit approval, these Firestore rules were published to `safe-ddacb` through Firebase Console on 14 October 2026 at 10:43 am Melbourne time; the active rules version was verified in the console. The CLI attempt was denied and made no deployment. Existing cloud records and roles were not modified. Real staff login, event snapshots and completion still require live verification with the local backend running.
- Camera-feed integration, detector accuracy and the full historical Python detector test suite are outside this frontend migration's verification scope. Earlier reports below describe previous code versions.

## Auth verification update - 8 October 2026

- Re-ran 15 backend authorization tests, 8 Firebase configuration tests and 20 frontend tests; all passed. The frontend production build passed with the existing large-bundle warning.
- Staff-profile failures now distinguish permission errors, connectivity failures and expired authentication using safe error messages. Tests cover fail-closed access and ignoring stale callbacks.
- The local frontend now uses `safe-ddacb`. The user reports reaching the dashboard and seeing the administrator label, but administrator edits remain unresolved and are not verified end to end. Automated checks do not establish live Firebase permissions or backend integration.
- Real environment files and service-account credentials are not included in Git. Firestore rules must be published separately.

## Backend authentication - 6 October 2026

- Scope: the team's pulled FastAPI/event implementation, with server-side Firebase ID-token verification and active `admin`/`operator` profiles. The discarded FastAPI/pacing stash was not restored.
- Added 15 isolated tests covering token verification, revocation/disabled users, missing/unsupported staff profiles, anonymous denial, role changes, verification outages, all protected routes, read-only operators, admin-only completion/deletion, server-derived completion identity, missing events, and active-stream revocation. All 15 passed without Firebase network calls or camera capture.
- The `Event` response model was moved unchanged into `event_types.py` so the route/auth tests can run without loading Firebase credentials or detector models. Production event storage and detection logic are unchanged.
- The existing full Python suite was checked before edits and failed to import both detector test modules (`attempted relative import beyond top-level package`). This pre-existing issue remains outside the auth-only scope.
- At this test run, live verification was pending: the matching backend service-account file was unavailable and the frontend project configuration still needed alignment. See the 8 October update for later frontend verification. No credentials, Firebase accounts, roles, deployed rules, cloud records or storage were modified by these tests. Earlier verification sections describe historical versions, not the current pulled backend.

## Admin editing and operator read-only checks - 1 October 2026

- Permissions-only commit: 17 frontend tests passed; production build passed with the existing large-bundle warning.
- Firestore emulator: 8 permission tests passed against a demo-only project. Tests use real SDK transactions, not just mocked UI permissions.
- Permissions-only commit: 32 Python tests run, 31 passed and the existing pacing placeholder skipped, including checks for operator camera viewing without start/stop permission and administrator demotion. Unfinished pacing work is excluded from this commit.
- Permission checks cover approved admin/operator reads, unauthenticated and disabled denial, operator write denial, immutable detector evidence and audit entries, matching atomic review records, forged actor rejection, role demotion and stale resolution rejection.
- No production accounts were created or given new roles by these tests. Operator visual testing still needs a separate signed-in operator session; operator denial was verified in the emulator and backend tests.
- Published the rules to `safe-1426e` after approval and read the active ruleset back to confirm it matches the tested source. A clearly labelled TEST ONLY note saved through the live admin dashboard on the existing synthetic incident, with the acting admin UID and server timestamp visible in response history. No real incident assessment was recorded.
- Earlier sections below describe previous read-only behavior; this section supersedes those permission limitations.

Run frontend checks from `front-end` with `npm test` and `npm run build`.
Run rules checks from the repository root with Java 17 installed:

```bash
npx firebase-tools@13.35.1 emulators:exec --only firestore --project demo-safe-roles --config firebase.emulator.json "npm --prefix front-end run test:rules"
```

Use only the `demo-safe-roles` project for these tests; the emulator clears its test database between cases. Firebase CLI 13 is used here for compatibility with the local Java 17 installation.

## Local playback verification - 1 October 2026

- Python: 30 tests run, 29 passed, 1 pacing placeholder skipped.
- Frontend: 12 existing regression tests passed; production build passed.
- Added checks for pre/post-alert buffering, wall-time resampling, partial clips,
  restart availability, duplicate triggers, bounded concurrent recording,
  encoding failures, storage limits, safe IDs, authenticated access, revocation,
  and partial-content video responses.
- The real encoder produced a decodable MP4. A synthetic, clearly labelled
  15-second clip played in Chrome; pause and Alert seeking to 5 seconds worked.
  The player was inspected at desktop and 390-pixel mobile width.
- Only local clips are implemented. Cloud uploads and billing changes were not
  performed. A real detected incident's recording still needs a consented manual
  end-to-end test; the synthetic fixture does not validate detector accuracy.

## Integration verification - 1 October 2026

After pulling the team's detector refactor and new dashboard, the tests were
migrated to the shared `detection` package. Current results:

- Python: 18 tests run, 17 passed, 1 pacing placeholder skipped.
- Frontend: 12 tests passed, including the team's demo event-transition tests.
- React production build passed, with a bundle-size warning.
- Approved staff login, Firestore test-incident display, and a 960 x 540 live
  MacBook camera image with YOLO overlays were verified in Chrome.
- The cloud test record is explicitly labelled TEST ONLY. This is connection
  evidence, not evidence of real fall-detection accuracy.

Coverage now includes detector state timing, alert-latch deduplication,
Firestore payloads/write failures, camera endpoint access, staff revocation and
session races, incident adapters, and local calendar dates. Live incident
acknowledgement/resolution remains disabled; event-transition tests cover the
isolated demo data model only. No clinical or real-world accuracy claim is made.

Run the current commands in README.md to reproduce the automated checks.

## Historical test plan and report

The sections below retain the earlier plan and report. References to the old
standalone distress script, observation-count reset logic, and keyboard
acknowledgement are historical; the current sitting detector uses a sustained
non-sitting duration. Current results and scope above supersede those claims.

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

### Live / Video source toggle verification (14 October 2026)

- `npm test` in `front-end`: 38 tests passed, including source-control requests, invalid responses, cancellation, and generation-scoped streams.
- `python -B -m unittest discover -s tests -p test_video_source.py`: 12 tests passed. Covers idle startup, camera release before switching, stop during loading, fresh replay sessions, video EOF, missing video/camera failures, staff authorization and stale streams.
- `python -B -m unittest discover -s tests -p test_staff_auth.py`: 15 tests passed. Existing admin event permissions remain unchanged.
- `npm run build`: passed, with the existing large-bundle warning.
- Browser checks: admin/operator fixtures at 1440 px and 390 px; moving canvas, Live/Video switching, Stop clearing frames, EOF/Replay, source generation through the real Vite proxy, access revocation, and no horizontal overflow or page errors. These checks used synthetic inputs and fake staff accounts, with no Firebase writes.
- Real-input smoke check: the existing YOLO `VideoMode` processed the first 20 frames of the bundled video, tracked two people, produced annotated frames, released the video capture, and made no OpenCV GUI calls. Firebase and settings were stubbed during this check. This does not verify the complete fall sequence or cloud event creation.
- The dashboard launcher started successfully with the configured local credentials; unauthenticated source requests returned 401. The actual webcam and end-to-end event persistence still require a manual check.

Run the dashboard launcher, select Video, wait for a detector event, then switch to Live and check the intended webcam. Stop should release the camera; Replay should restart the video. Both sources use the existing shared Firebase event pipeline, so manual testing can create real demo events. Earlier detector test results in this document are historical, not a claim that the full current detector suite was rerun.

- Unit tests prove the logic behaves as expected for controlled inputs, but they do not prove real-world detection accuracy.
- Camera position, lighting, occlusion, body visibility, and model confidence can all affect real detection results.
- Current thresholds are prototype/demo values and must not be treated as clinically validated.
- All alerts require human review before action.
