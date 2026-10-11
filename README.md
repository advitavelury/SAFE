# SAFE

**Smart Assisted Fall and Emergency**

SAFE is a FIT3161 / FIT3162 computer-vision prototype for camera-observable
distress events in aged-care environments. It is decision support, not a medical
device or a clinically validated emergency system.

## Current implementation

- React dashboard with Firebase staff sign-in, incident filtering and review.
- YOLO pose + ByteTrack for falls, prolonged sitting, isolation and movement
  outside normal hours. Pacing is not implemented by the current detector.
- Browser webcam preview, with explicit admin-only upload to a local Python
  detector. Processed frames show bounding boxes, pose and alert states.
- Amber/red incidents are saved asynchronously to the shared Firestore
  `incidents` collection used by the dashboard.
- Optional redacted local MP4 clips for red events, with authenticated playback.
  Amber events are metadata-only. Both backend enablement and the dashboard
  checkbox are required before a red event can trigger recording.
- Admins can acknowledge, annotate and resolve incidents. Operators are read-only
  and cannot start detection. They can preview their camera and review available
  clips. Database rules and backend authorization enforce access, not just labels.

## Teammate quick start

Run BOTH services on your own laptop with the launcher below. You do not need
Vercel or a tunnel for this local demo. The shared deployed website still uses
the backend origin embedded in its last build, not your laptop automatically.

### 1. Pull and install

From your SAFE repository, with any existing work committed or otherwise safely
preserved before changing branches:

```sh
git switch main
git pull --ff-only origin main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix front-end
```

For a new environment, use Python 3.11 and Node.js with npm. The current macOS
checks used an existing Python 3.10 environment, which now emits Firebase SDK
support warnings; a fresh Python 3.11 install still needs a device check.
For PowerShell, use `python` instead
of `python3`, and `.\.venv\Scripts\Activate.ps1` to activate. The launcher uses
the active Python interpreter. Windows camera/encoder behaviour still needs a
teammate-device check. Reuse an existing virtual environment when appropriate;
install the updated requirements after pulling.

### 2. Configure the existing team Firebase project once

- Copy `front-end/.env.example` to `front-end/.env`. Fill in the public web app
  values from **safe-ddacb -> Project settings -> Your apps**, or obtain the same
  public configuration from a teammate. Keep the collection as `incidents`.
- Obtain a valid **safe-ddacb Firebase Admin service-account JSON** securely and
  save it outside the repository. Only the Python backend uses this private file.
  Console access alone does not authenticate a local Python process. Never paste
  the key into chat, frontend code, a `VITE_` variable or Git.
- Use an existing approved staff login in that project. To run detection, its
  `users/{Authentication UID}` profile must contain boolean `active: true` and
  `role: "admin"`. An `operator` can view but not run detection.

You do NOT create another Firebase project/web app, enable paid cloud video
storage, or republish rules just to run the demo. An authorized project admin
manages accounts, approval profiles and the shared rules centrally. Email/password
sign-in and the complete incident/review rules must already be enabled. Do not
mix configuration from the old `safe-1426e` project.

### 3. Start the demo

From the repository root with the virtual environment active:

```sh
python scripts/run_demo.py --service-account "/absolute/path/to/key.json" --record
```

Replace the path with your actual downloaded private JSON. Alternatively set
`FIREBASE_SERVICE_ACCOUNT` in your terminal and omit `--service-account`.
The script does not automatically load `backend/.env`.

The launcher checks local configuration/dependencies, finds free ports, sets the
dashboard's detector URL and the backend's exact CORS origin, and starts both
services. Open the **SAFE dashboard URL printed in the terminal**. Defaults are
127.0.0.1:5173 for React and 127.0.0.1:8001 for detection; occupied ports are skipped.
Use that exact printed URL, not a stale tab, the Vercel link or a LAN IP.

- `--check` validates local setup without starting a server/camera. It does not
  prove the key is authorized by Firebase or that your staff login works.
- Omit `--record` to disable recording. With it, clips go to `~/.safe/recordings`
  unless you supply `--recordings-dir "/private/path/outside/the/repository"`.
- Optional `--frontend-port 5300 --backend-port 8100` changes the starting ports.
- Keep the terminal open. Stop detection in the app, then press Ctrl+C to shut
  down both services. Starting the launcher never opens a camera by itself.

### 4. Check detection and review

1. Sign in as an approved **admin**, open Monitor and select **Connect webcam**.
   Grant permission and select your laptop camera if a phone camera is selected.
2. For a recording test, check **Record red events locally**, then **Start
   detection**. Preview alone does not run YOLO. Only one detector session runs
   on each backend at a time.
3. Select **Detection frames** to inspect pose and alert labels. Keep the full
   person visible. Use safe staged/prerecorded material, not deliberate real falls.
   "Falling" alone is not a confirmed red fall; pose and timing checks must pass.
4. A recognized amber/red event appears in Incidents. After a red event, leave
   detection running for at least five more seconds, then choose **Review** to
   play the saved clip. The player can show processing, partial or unavailable.
5. Check the SAVED clip frame by frame for redaction. Live preview/overlays are
   not face-blurred. Missing reliable landmarks may black out the entire person.

All teammates see the shared Firebase incident metadata. Clips remain on the
laptop that recorded them: another teammate's backend cannot play those files.
Use the recording laptop's dashboard, or a deliberately configured authenticated
HTTPS backend for remote playback. Clips expire after 24 hours and the local store
has a 250 MiB rolling video limit. Old incidents cannot gain a recording retroactively.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Dashboard loads, detection is off | Connect webcam, then explicitly Start detection as an admin. |
| Operator cannot start detection | Expected read-only role; ask the project admin about approved demo access. |
| Firebase permission denied | Correct safe-ddacb account/profile and published rules, not public access rules. |
| Unable to verify staff / start detector | Valid matching service-account file, internet access and backend terminal errors. |
| Webcam preview but no detection frames | Use the launcher URL, keep its terminal open, check browser/API errors. |
| Missing web config | Fill front-end/.env using the same team's public web app values. Restart the launcher. |
| No red clip | Backend --record and dashboard checkbox must both be enabled before the event; amber has no clip. |
| Old clip unavailable | It may be on another laptop, expired, or recorded before this feature existed. |
| No fall alert / low FPS | Inspect Detection frames for full-body pose and tracking continuity; hardware and sampling affect results. |

## Architecture and deployment

```text
Browser webcam -> authenticated JPEG requests -> local FastAPI + YOLO/ByteTrack
                                               -> Firestore incident metadata
                                               -> opt-in redacted local clips
React dashboard <- Firebase staff login + incidents + authenticated clip API
```

The browser path uses `backend.browser_camera_api:create_app` and writes
`incidents`. The older `backend.main` opens an OpenCV camera/video window, uses
`events` plus Firebase Storage snapshots, and currently contains a developer-local
video path. It remains for the team's legacy workflow; it is NOT the entry point
for this browser demo. Changing the dashboard collection to `events` will not
adapt that legacy schema.

- [Browser camera contract and detection limitations](BROWSER_CAMERA.md)
- [Recording behaviour, privacy limitations and validation](RECORDED_VIDEO.md)
- [Vercel setup and remote backend configuration](DEPLOYMENT.md)

Vercel hosts React, not the local webcam/YOLO process. A remote demo requires the
backend laptop to stay awake, an authenticated HTTPS tunnel, an exact allowed
frontend origin and a frontend rebuild with that tunnel URL. Pushing branches
alone does not prove the live Vercel deployment has been updated. Never put the
private Admin key into the static frontend deployment.

Detector thresholds are loaded from Firestore; protected admin API endpoints can
update them. The dashboard's draft preference controls are not a detector-settings
editor. Do not change shared thresholds without coordinating with the team.

## Tests

From the repository root with the virtual environment active:

```sh
python -B -m unittest discover -s tests -v
npm test --prefix front-end
npm run build --prefix front-end
```

Unit tests use mocks for Firebase and do not require a private key. A production
build needs valid public web configuration; its backend origins must be HTTPS,
not local loopback URLs. Leave optional origins blank for a dashboard-only build.
Unit tests and successful startup do not establish real-device accuracy, deployed
permissions or a privacy guarantee. One pre-existing pacing placeholder is skipped.

Integration checks on 12 October 2026: 95 backend tests passed, one placeholder
skipped, 41 frontend tests passed, and the production build passed. The launcher
started both services from a clean Git archive using existing installed dependencies;
desktop/mobile sign-in, the injected backend URL, CORS and unauthenticated rejection
were verified. Simulated-camera browser checks passed. A bundled sample produced a
red fall and a playable redacted MP4 using mocked database writes. No live staff
sign-in, real webcam recording or fresh dependency installation was performed in
these integration checks. The build retains its large-bundle warning.

## Limitations

- This is a single-session laptop demonstration, not unattended care monitoring.
- Falls can be missed with low processed FPS, lost tracks or unclear pose. Limited
  bundled-clip checks are documented, not an accuracy evaluation.
- Face redaction can conceal useful evidence and is not guaranteed anonymity.
  Validate every saved frame using consenting teammates before considering real use.
- No audio capture, cloud clip upload, SMS delivery or automatic emergency response
  is provided by this browser demo.

## Team

Advita, Zoe, Shadrach, Phuc, and Filbert.
