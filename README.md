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

## Vercel deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the `deployment` branch, exact Vercel
settings, public environment variables, Firebase checks and current limitations.
The first deployment hosts the dashboard only; camera and playback remain
unavailable until a compatible authenticated HTTPS media service is connected.

## Firebase setup

1. Use the team's `safe-ddacb` Firebase project and register a Firebase web app in it.
2. Enable Email/Password in Authentication. Anonymous sign-in is not used.
3. Create a staff account, then a Firestore document at `users/UID` with `active: true` (boolean) and `role: "admin"` or `"operator"`.
4. Copy `front-end/.env.example` to `front-end/.env` and fill in the complete web app configuration from `safe-ddacb`. Do not mix its project ID with API keys/app IDs from the former `safe-1426e` project. Restart Vite after changing environment values.
5. Download a private Admin SDK JSON file for `safe-ddacb` and keep it outside Git (for example, in the ignored `.secrets/` directory). Set the shell environment variable `FIREBASE_SERVICE_ACCOUNT` to its path. Alternatively, the existing default filename `backend/safe-ddacb-firebase-adminsdk-fbsvc-7c69c74b63.json` remains supported. The backend rejects keys from a different project. It does not load `backend/.env` automatically.
6. Publish the included Firestore rules for the dashboard through the Firebase console, or using the Firebase CLI:

```bash
firebase deploy --only firestore:rules --project YOUR_PROJECT_ID
```

Never commit real environment files or service-account keys. Example files contain placeholders only. The Admin SDK bypasses client rules, so its credentials must remain on the trusted backend.

Approved `admin` accounts can review the dashboard's incident records and complete/delete events through the backend; approved `operator` accounts have read-only access. Use the Authentication account's exact UID for the `users/UID` document in `safe-ddacb`. Accounts and profiles in the former project do not automatically transfer. Draft browser settings do not configure the Python detectors.

The API requires a Firebase ID token in `Authorization: Bearer <id-token>` for `/auth/me`, `/events`, `/events/{id}` and `/video_feed`. It verifies the token with revocation/disabled-user checks and reads `users/{uid}` from the backend's Firebase project. Missing/invalid tokens return 401, unapproved users and forbidden writes return 403, and verification outages return 503. Profiles must have boolean `active: true` and exactly `admin` or `operator`; anonymous accounts are rejected. Tokens and Firestore profiles are checked on each API request, and ongoing streams recheck access approximately every five seconds. Failed checks end the stream.

Event completion uses the verified admin UID. A legacy `completed_by` request field is accepted but ignored, and the body can be omitted. Roles cannot be changed through these endpoints. `/auth/me` returns the verified UID and role for connection checks. This follows [Firebase's server-side ID token verification flow](https://firebase.google.com/docs/auth/admin/verify-id-tokens).

## Run the backend

From the repository root, with the Python environment activated:

```bash
FIREBASE_SERVICE_ACCOUNT="/absolute/path/to/your-service-account.json" python -m backend.main
```

Choose the input in `backend/main.py` before starting:

- For the default webcam, set `video_mode = False`.
- For a recording, set `video_mode = True` and update `video_footage_path` to an existing video. The current checkout selects video mode and refers to a developer-local test file.

The API runs at http://127.0.0.1:8000. Open http://127.0.0.1:8000/docs and use **Authorize** with a Firebase ID token to try the event endpoints. A bare `/video_feed` URL or `<img>` has no bearer header and is intentionally rejected; never put tokens in URLs. The backend opens a local OpenCV window as well. Keep this prototype loopback-only; a remote deployment needs HTTPS and an authenticated streaming client.

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

Install test dependencies with `pip install -r requirements-dev.txt`. Auth-only checks can run without a camera, service-account file or Firebase network calls:

```bash
python -B -m unittest discover -s tests -p test_staff_auth.py -v
```

The pulled detector tests currently fail on package imports inconsistent with `backend.detection`; this auth-only change leaves those tests and the detector logic untouched. Unit tests do not establish real-video accuracy or clinical suitability.

## Limitations and next steps

- Connect the dashboard to the event API and video feed; its existing incident schema and camera API differ from the remaining backend.
- Browser sign-in requires matching `safe-ddacb` web configuration, approved staff profiles, and published Firestore rules. Protected backend API access additionally requires a matching backend service-account file. Auth changes do not connect the remaining dashboard/API workflows.
- Settings are draft browser preferences, not live detector configuration.
- Video clip recording, face blur, and SMS/audio delivery are not implemented in the remaining backend.
- Detection thresholds and geometry remain those supplied by the team; no accuracy claims are made.
- Real deployment requires consent, privacy/retention controls, realistic validation, and human review.

## Team

Advita, Zoe, Shadrach, Phuc, and Filbert.
