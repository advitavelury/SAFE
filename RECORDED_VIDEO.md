# Local red-event recordings

This feature extends the browser-camera demo. It does not enable Firebase Storage,
change Firestore rules, or deploy itself to Vercel. Existing incidents cannot
retroactively acquire a video.

## What is recorded

- Recording defaults OFF on the backend and in the dashboard. Approved staff
  must explicitly select **Record red events locally** before Start detection.
- Only red fall/distress events trigger a clip. Amber events remain metadata-only.
- The buffer holds up to 3 seconds before and 5 seconds after the event, at up to
  5 sampled FPS, 640 x 360 with letterboxing. Slow incoming video is not made more
  accurate by recording it. Missing spans become black, not extended freeze-frames.
- Frames are redacted BEFORE the in-memory buffer. No raw frame files, raw video,
  microphone audio, or cloud video copies are created by this recording path.
- The saved result is H.264 MP4. Encoding runs off the detection thread, with at
  most four capturing/queued clips and one encoder worker. Capacity/encoder errors
  appear as recording errors; the incident itself remains in Firestore.
- Stop, navigation, tab hiding and session expiry can produce a partial clip.
  Idle sessions are closed after about 15-17 seconds without frames. A process
  crash loses buffered footage; only completed files survive a restart.

## Privacy boundaries

The recording hides everything outside detected person boxes. For EVERY detected
person, observed face and shoulder landmarks define a generously padded head
region, which is coarsely pixelated and blurred. Without sufficiently confident
face/shoulder landmarks, the entire person box is blacked out. Redaction happens
after compositing all person boxes, so overlap cannot restore an earlier face.
If redaction raises an error, that raw frame never enters the buffer.

This is a prototype privacy filter, NOT a guarantee of anonymity. A missed or
incorrect detection, particularly a bystander within another person's box, may
still leave identifying content. Clothing, body shape and context may identify
someone even with a hidden face. Real footage needs frame-by-frame review with
consenting participants. Do not test with residents until privacy is validated.
The live webcam preview and processed detection view are NOT redacted; the saved
recording is a separate output. Firebase receives incident metadata, not footage.

## Run locally

The simplest teammate setup is the [README quick start](README.md#teammate-quick-start):
`python scripts/run_demo.py --service-account "/absolute/path/to/key.json" --record`.
It starts both services with matching local origins. The separate-terminal commands
below are the equivalent manual configuration.

From the repository root on this branch, using your existing compatible Python
environment:

```sh
python -m pip install -r requirements.txt
export FIREBASE_SERVICE_ACCOUNT="/absolute/path/to/your-private-service-account.json"
export SAFE_RECORDINGS_ENABLED=true
export SAFE_RECORDINGS_DIR="/absolute/private/path/to/safe-recordings"
export SAFE_WEB_ORIGINS="http://127.0.0.1:5174"
python -m uvicorn backend.browser_camera_api:create_app --factory --host 127.0.0.1 --port 8012 --workers 1
```

Replace both file paths with actual locations. Never commit the credential or
clips, place clips in a frontend/public directory, or expose the recording folder
with a static-file server. `imageio-ffmpeg` provides the encoder binary.

In a second terminal, start the frontend with your normal public Firebase web
configuration and the local backend origin:

```sh
cd front-end
VITE_BROWSER_DETECTOR_ORIGIN=http://127.0.0.1:8012 npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Sign in as approved staff (admin or operator), connect the camera, check the recording checkbox,
then Start detection. After a red event, leave detection running for at least five
more seconds for the follow-up. An **admin** can open **Incidents -> Review**. The player polls
while the clip finishes; **Alert** jumps to the event position. Both roles can run
their own monitoring/recording session, but only admins can play clips. Operators
can read incident and clip details, not the video. Incident edits and detector settings
also remain admin-only.

Vercel must be deployed from code containing this feature to show these controls.
For a remote demo, run this backend behind the approved authenticated HTTPS tunnel,
allow the exact dashboard origin and set Vercel's `VITE_BROWSER_DETECTOR_ORIGIN`
to that tunnel before rebuilding. No private key belongs in Vercel. Moving to a
different laptop does not move old local clips automatically.

## Storage and access

- MP4 and metadata files use private permissions in a private folder (0700/0600
  on POSIX). `backend/recordings/` is already gitignored; custom paths must remain
  outside Git. Local disk encryption/OS account security are still necessary.
- Retention is 24 hours, with a 250 MiB rolling completed-video limit. Oldest clips
  are removed first. Cleanup runs on startup, save/read and approximately every
  minute while the backend runs. When it is off, expired files remain until the
  next startup. Firestore incident records are not deleted by clip cleanup.
- Playback resolves an incident ID to a managed local path. Clip metadata requires
  a fresh verified Firebase token and active staff profile. MP4 requests additionally
  require the admin role;
  no query-token URLs, public file links, or wildcard CORS are used. Responses are
  no-store. A role change closes the dashboard player and releases its blob URL.
  Previously downloaded footage cannot be recalled from a device.
- Readiness comes from the clip API. Firestore recording flags are updated on
  completion when available; failed flag synchronization is logged and does not
  expose raw data or prevent local playback.

## Validation checklist

Automated tests cover pre/post buffering, red-only triggers, redaction-before-
buffering, missing face landmarks, overlap, partial clips, encoder failure,
retention, capacity, restart, safe paths, admin-only playback and frontend errors.
An offline run of the bundled fall video produced an actual playable H.264 clip
with no audio, using mock database writes. Desktop/mobile browser checks covered
playback, seek-to-alert, loading, denied access and object-URL cleanup.

Still required before claiming privacy works on real recordings:

1. Use consenting teammates and safe prerecorded/staged footage, not deliberate
   real falls. Test front/side/back views, movement, partial visibility and multiple
   overlapping people, including someone the detector might miss.
2. Inspect EVERY frame of the saved MP4, not just the preview or thumbnail. Record
   any exposed face, fallback black frame and wrong box/landmark association.
3. Inspect the recording folder and confirm only redacted MP4/JSON files exist.
   Confirm no raw source or intermediate frame is written or uploaded.
4. Check admin playback, operator clip details with video denied, denied/revoked accounts, stopping mid-clip,
   browser tab hiding, network interruptions and retention cleanup.

Passing the code tests or seeing a red alert alone does not satisfy this checklist.

### Branch verification, 12 October 2026

82 backend tests and 41 frontend tests passed; one pre-existing pacing placeholder
was skipped. The frontend production build passed. All 19 frames of the generated
3.8-second sample MP4 were inspected as a contact sheet. Several frames, including
part of the fall transition, are fully concealed by the privacy fallback. This is
a deliberate conservative behaviour, but its effect on review usefulness still
needs evaluation with consenting teammates. The sample is partial because the
bundled source ends before the five-second follow-up completes. These checks did
not upload video or create test incidents in Firebase.
