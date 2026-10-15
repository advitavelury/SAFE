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

For detection, snapshots and admin completion, run `python -m backend.dashboard` from the repository root with the backend virtual environment and `FIREBASE_SERVICE_ACCOUNT` configured. See the root README for setup. Vite forwards `/api/events/...` to the existing FastAPI `/events/...` routes on port 8000.

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

Run `python -m backend.dashboard` in a separate terminal, then open Monitor. Choose **Live** or **Video** to start detection. Both approved admins and operators can control this shared source:

`backend/dashboard.py` -> existing `CameraMode` / `VideoMode` -> existing `FrameStreamer` -> `/video_feed` (port 8000) -> Vite `/api/video-feed` -> React viewer (port 5173).

The request includes the signed-in user's Firebase bearer token. The backend still controls access and rechecks it during streaming. No token goes into a URL. The frontend parses the MJPEG response and displays annotated JPEG frames; it does not run another detector or request the browser's webcam.

- Live opens the backend computer's default camera. Set `SAFE_CAMERA_INDEX` before starting Python if index 0 is not the intended desktop camera. This is not the webcam on a separate remote viewer's device.
- Video processes the bundled `Final_pitch_1.mp4`, which is identical to the supplied `fall.mp4`. The displayed frames include the team's detection overlays, not just raw MP4 playback. No additional 72 MB copy or browser upload is needed.
- Stop releases the source. Switching restarts tracking with a fresh detector session; all connected viewers follow the shared source. At the end of the video, use Replay to run it again. There is no automatic loop.
- Reconnect only reconnects this viewer. If the feed stops or sends no complete frames for 30 seconds, the last image is cleared. Changing source also clears old frames and invalidates old stream sessions.
- Both modes can save detected events and snapshots to the same Firebase project, including on replay. The detector logic, thresholds and event schema are unchanged.
- The original `python -m backend.main` launcher is preserved but does not provide the source toggle. Stop it before using the dashboard launcher on port 8000.
- The feed has no per-frame source timestamp. A connected stream does not prove the input is a live camera or that the detector is progressing.
- This proxy is for `npm run dev` on the same computer as Python. It does not connect a deployed Vercel app to a teammate's laptop.
- Streaming does not upload the frames to Firebase. The existing backend remains responsible for event snapshots. Streamed frames are not promised to have face blur.

## Demo thresholds in seconds

With the Python backend running, sign in as an admin and open **Settings**. Prolonged sitting and isolation are editable in **seconds**, loaded from the existing backend settings API. Set prolonged sitting to `30` and click **Save thresholds** for the class demo. Leave isolation unchanged unless you also want a shorter isolation demo.

Saving uses the authenticated `PATCH /admin/detector-settings` endpoint. The existing service persists the values in `settings/detectors` and queues them for the active detector. Only changed duration fields are sent; normal hours, sitting break duration and warning fraction are preserved. Operators cannot access this admin-only endpoint. Old browser-only minute preferences are ignored, not migrated into production settings.

For a fresh demonstration, save first, then stop and restart Live or Video so existing tracked sitting time and outstanding-event latches do not carry over. With the default warning fraction of 0.5, a 30-second sitting threshold gives amber at 15 seconds and red at 30 seconds of detected sitting. Video uses source-video time, so slow processing can take longer than 30 wall-clock seconds. Camera visibility and pose classification still affect results. Restore your intended thresholds after the demo; saved settings are shared and persist beyond this browser.

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
