# SAFE dashboard

React/Vite dashboard for the team's `safe-ddacb` Firebase project.

## Run locally

1. Copy `.env.example` to `.env` if you do not already have one. Fill in the team's public Firebase web configuration.
2. Publish the repository's `firestore.rules` to `safe-ddacb`. The rules allow active admin/operator accounts to read `events`; browser writes are denied. Publishing is a separate administrator action, not part of `npm run dev`.
3. Use an Authentication account with a `users/{uid}` profile containing boolean `active: true` and `role: "admin"` or `"operator"`.

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173. Metadata is read directly from Firestore, so listing events does not need the Python backend. No private service-account key belongs in this frontend.

For snapshots and admin completion, run `python -m backend.main` from the repository root with the backend virtual environment and `FIREBASE_SERVICE_ACCOUNT` configured. See the root README for setup. Vite forwards `/api/events/...` to the existing FastAPI `/events/...` routes on port 8000.

## Event contract

- Collection: `events`, ordered by `timestamp` descending, latest 50 records.
- Types: `fall`, `sitting distress`, `isolation distress`, `wandering distress`.
- Alert level: `red` or `amber`, taken from the stored event rather than inferred from its type.
- Status: `open` or `closed`; completion records `completed_by` and `completed_at`.
- Evidence: `image_path` points to a JPEG snapshot. The authenticated backend returns a temporary signed image URL for review.
- Admins can mark an open event complete through the backend. Operators can view metadata and snapshots but cannot complete events.
- Unknown/missing values are shown as unavailable, not invented timestamps, severities or confirmed outcomes.

The dashboard no longer reads or writes `incidents`, its `reviews` subcollection, or the old clip endpoints. Existing cloud data is not deleted. `VITE_FIREBASE_INCIDENTS_COLLECTION` is ignored and can be removed from local environment files.

## Local video feed

Run the existing Python backend in a separate terminal, then open the dashboard's Monitor page. The viewer connects automatically for approved admins and operators:

`backend/main.py` -> existing `FrameStreamer` -> `/video_feed` (port 8000) -> Vite `/api/video-feed` -> React viewer (port 5173).

The request includes the signed-in user's Firebase bearer token. The backend still controls access and rechecks it during streaming. No token goes into a URL. The frontend parses the MJPEG response and displays annotated JPEG frames; it does not run another detector or request the browser's webcam.

- The feed shows whichever source the backend is running. Currently `backend/main.py` selects a recorded test video (`video_mode = True`); its existing `CameraMode` path is used when that flag is false. No backend source selection or detection logic was changed for this integration.
- Disconnect/reconnect affects only this viewer, not the Python camera/detector. If the feed stops or sends no complete frames for 30 seconds, the last image is cleared and a reconnect control appears.
- The feed has no per-frame source timestamp. A connected stream does not prove the input is a live camera or that the detector is progressing.
- This proxy is for `npm run dev` on the same computer as Python. It does not connect a deployed Vercel app to a teammate's laptop.
- Streaming does not upload the frames to Firebase. The existing backend remains responsible for event snapshots. Streamed frames are not promised to have face blur.

Browser settings remain draft preferences; they do not configure the detector.

## Verify

```bash
npm test
npm run build
```

From the repository root, with Java 17:

```bash
npx firebase-tools@13.35.1 emulators:exec --only firestore --project demo-safe-roles --config firebase.emulator.json "npm --prefix front-end run test:rules"
```

The rules tests clear only the local demo emulator. Never point them at the production project.
