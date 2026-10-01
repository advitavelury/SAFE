# SAFE dashboard

React, Vite, Tailwind, lucide-react, and Firebase. The team's Monitor, Incidents, and Settings layout is connected to approved staff sessions and Firestore.

## Setup

Copy `.env.example` to `.env` and fill in Firebase web configuration. Create an approved staff account and deploy the root Firestore rules as described in the root README.

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Run `.venv/bin/python backend/video_server.py --camera 0` separately from the repository root. Sign in and click Start camera. Vite proxies authenticated camera requests to `127.0.0.1:5001`.

## Data boundaries

- `StaffAccess.jsx` and `staffAccess.js`: email/password session and active staff profile checks.
- `feeds.js`: latest 50 Firestore incidents with explicit loading/error states.
- `incidentAdapter.js`: maps backend records to the team's dashboard event shape.
- `admin.js`: live read-only events; the old local demo adapter is retained separately, never used as an error fallback.
- `LiveCameraStage.jsx`: local annotated camera frames.
- `IncidentPlayback.jsx`: authenticated local MP4 playback in Review, with recording/processing/unavailable/error states and an Alert seek button. New incident clips are stored by the Python camera server, not uploaded to Firebase.
- `CameraStage.jsx`: retained mock, not used by the live dashboard.

The published rules deny browser incident writes. Acknowledgement and resolution controls are therefore hidden for live records. Settings remain browser-only draft preferences. Both admin and operator roles currently have read-only incident access.

Past events without recordings show unavailable. Keep the local camera server running to play clips stored on this Mac. Recordings have no audio or face blur; use consented prototype testing only.

## Verify

```bash
node --test tests/*.test.js tests/*.test.mjs
npm run build
```

Tests do not replace a real approved-staff login, camera check, or Firebase rules validation.
