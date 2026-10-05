# SAFE

**Smart Assisted Fall and Emergency**

SAFE is a FIT3161 / FIT3162 computer-vision prototype for camera-observable distress events in aged-care environments. It is decision support, not a medical device or a clinically validated emergency system.

## Current implementation

- Shared YOLO pose and ByteTrack pipeline for fall, prolonged sitting, isolation, and movement outside normal hours.
- The team's React dashboard with Monitor, incident filtering/detail, and draft settings views.
- Firebase email/password login with active staff approval.
- FastAPI event endpoints backed by Firestore, with event images in Firebase Storage.
- Local camera/video processing with YOLO overlays and a `/video_feed` stream.
- The dashboard still uses its separate Firestore incident schema; integration with the events API remains to be completed.
- Pacing is not implemented; unusual-hours movement is not pacing.

## Repository

```text
backend/
  detection/
    detection.py           Shared camera/video pipeline
    detectors/             Fall, sitting, isolation, wandering
    person.py              Per-track state
  main.py                  Local detector and FastAPI entry point
  event.py                 Event persistence and completion
  event_types.py           Event type and status enums
  firebase_config.py       Firebase Admin and Storage configuration
  routes.py                Event and video-feed endpoints
  streamers.py             Video streaming
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
5. Configure the backend using `backend/firebase_config.py`: place your private Admin SDK JSON file beside it and set the filename and Storage bucket to match your project. The current backend does not load `backend/.env`.
6. Publish the included Firestore rules for the dashboard through the Firebase console, or using the Firebase CLI:

```bash
firebase deploy --only firestore:rules --project YOUR_PROJECT_ID
```

Never commit real environment files or service-account keys. Example files contain placeholders only. The Admin SDK bypasses client rules, so its credentials must remain on the trusted backend.

Approved `admin` accounts can review the dashboard's incident records; approved `operator` accounts have read-only access. Use the Authentication account's exact UID for the `users/UID` document. Draft browser settings do not configure the Python detectors.

## Run the backend

From the repository root, with the Python environment activated:

```bash
python -m backend.main
```

Choose the input in `backend/main.py` before starting:

- For the default webcam, set `video_mode = False`.
- For a recording, set `video_mode = True` and update `video_footage_path` to an existing video. The current checkout selects video mode and refers to a developer-local test file.

The API runs at http://127.0.0.1:8000. Open http://127.0.0.1:8000/docs to try the event endpoints, or http://127.0.0.1:8000/video_feed to view the stream. The backend opens a local OpenCV window as well.

## Run the dashboard

In another terminal:

```bash
cd front-end
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173 and sign in. The dashboard's camera controls and incident video playback are not connected to the remaining backend. Its incident feed still reads the `incidents` collection by default, while the backend writes `events`; frontend integration is needed before newly detected events appear there. Dashboard review actions do not currently call the backend completion endpoint.

## Event records and API

The backend stores event metadata in Firestore's `events` collection and annotated JPEG images in Firebase Storage. Each record contains `person_id`, `event_type`, `status`, `timestamp`, and `image_path`. Completion adds `completed_by` and `completed_at`. The document ID is returned as `id`, and event reads generate an image URL valid for one hour.

Event types are `fall`, `sitting distress`, `isolation distress`, and `wandering distress`. Status is `open` or `closed`. The detector tracks one outstanding event per person in the current session.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/events` | List events |
| GET | `/events/{event_id}` | Read one event |
| POST | `/events/{event_id}/complete` | Complete an event |
| DELETE | `/events/{event_id}` | Delete an event and its image |

For completion, send `Content-Type: application/json` with a body such as:

```json
{"completed_by": "Staff 1"}
```

Event creation and image uploads currently run synchronously in the detection loop. Local incident video recording is not provided by the remaining backend.

## Tests

```bash
python -m unittest discover -s tests -v
cd front-end
node --test tests/*.test.js tests/*.test.mjs
npm run build
```

The Python suite still contains tests for removed camera-server, incident-publisher, and recording modules; these need to be removed or updated before the full suite can pass. Detector tests also need package imports consistent with `backend.detection`. Unit tests do not establish real-video accuracy or clinical suitability.

## Limitations and next steps

- Connect the dashboard to the event API and video feed; its existing incident schema and camera API differ from the remaining backend.
- The current FastAPI routes do not enforce the dashboard's staff authentication or roles.
- Settings are draft browser preferences, not live detector configuration.
- Video clip recording, face blur, and SMS/audio delivery are not implemented in the remaining backend.
- Detection thresholds and geometry remain those supplied by the team; no accuracy claims are made.
- Real deployment requires consent, privacy/retention controls, realistic validation, and human review.

## Team

Advita, Zoe, Shadrach, Phuc, and Filbert.
