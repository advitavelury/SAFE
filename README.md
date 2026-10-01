# SAFE

**Smart Assisted Fall and Emergency**

SAFE is a FIT3161 / FIT3162 computer-vision prototype for camera-observable distress events in aged-care environments. It is decision support, not a medical device or a clinically validated emergency system.

## Current implementation

- Shared YOLO pose and ByteTrack pipeline for fall, prolonged sitting, isolation, and movement outside normal hours.
- The team's React dashboard with Monitor, incident filtering/detail, and draft settings views.
- Firebase email/password login with active staff approval.
- Live Firestore incident records, without falling back to sample data when disconnected.
- Authenticated local camera frames with YOLO overlays.
- Pacing is not implemented; unusual-hours movement is not pacing.

## Repository

```text
backend/
  detection/
    detection.py           Shared camera/video pipeline
    detectors/             Fall, sitting, isolation, wandering
    person.py              Per-track state
    firebase_events.py     Incident publishing and alert-latch adapter
  video_server.py          Authenticated dashboard camera API
  main.py                  Team's standalone local stream demo
  routes.py
  streamers.py
front-end/
  src/api/                 Firebase, staff approval, event adapters
  src/components/          Staff login and live camera
  tests/
tests/
firestore.rules
firebase.json
requirements.txt
```

## Install

Python 3.11+ is recommended. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd front-end
npm ci
```

## Firebase setup

1. Create a Firestore database and register a Firebase web app.
2. Enable Email/Password in Authentication. Anonymous sign-in is not used.
3. Create a staff account, then a Firestore document at `users/UID` with `active: true` (boolean) and `role: "admin"` or `"operator"`.
4. Copy `front-end/.env.example` to `front-end/.env` and fill in the web app configuration.
5. Copy `backend/.env.example` to `backend/.env`. Point `FIREBASE_SERVICE_ACCOUNT` at a private Admin SDK key stored outside Git, for example in `.secrets/`.
6. Publish the included Firestore rules through the Firebase console, or using the Firebase CLI:

```bash
firebase deploy --only firestore:rules --project safe-1426e
```

Never commit real environment files or service-account keys. Example files contain placeholders only. The Admin SDK bypasses client rules, so its credentials must remain on the trusted backend.

Approved `admin` accounts can acknowledge incidents, add review notes, resolve them as confirmed or false alarms, and start/stop the shared camera. Approved `operator` accounts can read incidents, watch a running camera, and play available clips, but cannot edit records or control the camera. Draft browser settings are editable only by admins and still do not configure the Python detectors.

Set `users/UID` to `{ active: true, role: "admin" }` or `{ active: true, role: "operator" }` in the Firebase console. Use the Authentication account's exact UID; `active` must be a boolean. Role changes and staff approval are console-only, not editable from the dashboard. Firebase Authentication and a server-confirmed active profile are both required. Camera approval/role changes are rechecked within ten seconds.

Review writes use a Firestore transaction, preserving the original detection type, timestamps and detector note. Every action adds an immutable `incidents/ID/reviews/ID` entry with the acting admin UID and a server timestamp. Rules reject operator writes, missing audit entries, forged actors, changes to detection evidence, incident creation/deletion and edits/deletions of review history. Resolved incidents can receive further notes but cannot be reopened or resolved again. The team's isolated local demo adapter remains available in source, but is not a fallback for live data.

## Run the dashboard and camera

From the repository root:

```bash
.venv/bin/python backend/video_server.py --camera 0 --port 5001
```

In another terminal:

```bash
cd front-end
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173 in Chrome, sign in, and click **Start camera**. Allow Python camera access if prompted. Camera numbers can change when external cameras or iPhone Continuity Camera are connected; use `--camera N` to choose another device.

For a recording, use `--video "path/to/video.mp4"` instead of `--camera`. The browser labels recorded input TEST VIDEO.

The camera API binds to loopback and checks a Firebase bearer token and active staff profile. Approval is rechecked at least every ten seconds. Vite proxies `/api/camera` to port 5001. Frames are displayed at up to five snapshots per second, independently of detector throughput. Capture stops after approximately twenty seconds without frame requests.

The dashboard uses zone A by default; keep `SAFE_ZONE_ID=A` for this single-camera setup. The team's standalone `python backend/main.py` stream on port 8000 is a separate local demo without the staff authentication used by `video_server.py`. Do not expose it publicly or run both programs against the same webcam.

## Incident records

Each rising detector alert latch publishes one document to `incidents`, containing:

- `incidentId`, `type`, `status`
- `zoneId`, `personId`, `note`, `source`
- `ts` and `createdAt` server timestamps, plus ISO fallbacks

Types are `fall`, `prolonged_sitting`, `isolation`, and `wandering`. Older `distress` and `false` records remain displayable. Repeated frames do not publish duplicates while a detector's latch remains set. A new event requires the detector to reset that latch or create a new track.

Firestore contains incident metadata. Incident recordings stay on the local camera server; no footage is uploaded to Firebase Storage. Writes have a bounded timeout; failures are logged without stopping detection, but are not durably queued or retried. The dashboard currently reads the latest 50 incidents, so its counts and filters are not a complete historical report.

## Incident video playback

Open **Incidents**, select **Review**, then use the video controls under
**Incident recording**. The Alert button seeks to the alert timestamp.

While the authenticated camera server is running, new published detector alerts
capture up to 5 seconds before and 10 seconds after the alert. The rolling
pre-alert buffer is held in memory; only triggered incident clips are saved.
Clips use annotated H.264 MP4 video at 5 fps with no audio. Slow detector frames
are repeated to preserve elapsed time rather than speeding up playback.

Recordings are private local files in `backend/recordings/`, excluded from Git.
Only approved staff can fetch them through the authenticated camera API. The
camera server must be running on the Mac that holds the clips; another teammate's
machine will show unavailable for recordings it does not have. Earlier incidents
have no recoverable footage. A labelled synthetic test clip may accompany the
TEST ONLY connection-check record for playback verification.

The recorder handles up to four pending clips and caps saved MP4 storage at 1 GB.
When full it refuses new recordings without deleting old clips. On camera stop,
available footage is saved as a partial clip. Abrupt process termination can lose
in-progress footage. Recording failures appear as unavailable/failed playback;
there is no cloud backup or automatic retry. Clips use the detector's existing
alert latches, so repeated frames do not create repeated recordings.

**Privacy:** recordings include visible faces; face blurring is not implemented.
Use consented prototype testing only, restrict access to the machine, and agree
retention/deletion rules before recording real residents. Stored clips are not
a substitute for clinical incident review.

Encoding uses [FFmpeg](https://ffmpeg.org/ffmpeg.html) through the
`imageio-ffmpeg` dependency. Playback bytes are served by the local authenticated
API, using [Flask conditional file responses](https://flask.palletsprojects.com/en/stable/api/#flask.send_file).

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
cd front-end
node --test tests/*.test.js tests/*.test.mjs
npm run build
```

Tests cover fall/sitting state transitions, event payloads and latches, camera API access, staff approval lifecycle, event adapters, local dates, and the team's demo event transitions. Pacing has one explicitly skipped placeholder. Unit tests do not establish real-video accuracy or clinical suitability.

## Limitations and next steps

- Cloud clip uploads, face blur, and SMS/audio delivery are not implemented.
- Settings are draft browser preferences, not live detector configuration.
- Detection thresholds and geometry remain those supplied by the team; no accuracy claims are made.
- A deployed frontend needs a secured camera backend/reverse proxy; the Vite proxy is for local development only.
- Real deployment requires consent, privacy/retention controls, realistic validation, and human review.

## Team

Advita, Zoe, Shadrach, Phuc, and Filbert.
