# Browser webcams and the laptop demo detector

## Available without backend setup

Approved admins and operators can use **Connect webcam** on the Monitor page.
The browser asks for permission and displays their own camera. Camera selection
appears after permission is granted. No microphone is requested. No frame leaves
the device in preview mode, and no clips or screenshots are saved.

Stop, page navigation, access revocation, sign-out and hiding the tab release the
camera. Returning to the page does not restart it automatically. A browser
permission prompt cannot be cancelled programmatically; if it resolves after
Stop, its stream is immediately released.

## Laptop detection setup

This is a controlled single-camera demo, not unattended aged-care monitoring.
The laptop must remain awake and online. Only an approved administrator can
start detection, upload frames or stop their detection session. Operators can
preview their own camera but cannot initiate incident-producing monitoring.

1. Obtain a replacement Firebase Admin service-account JSON for `safe-ddacb`.
   Keep it outside the repository. Supply its path through
   `FIREBASE_SERVICE_ACCOUNT`; never paste its contents into chat, source code,
   or Vercel. Console access alone does not authenticate the Python process.
2. From the SAFE repository, with the existing Python dependencies installed,
   set the credential file path in the terminal, then start the new service:

   ```sh
   export SAFE_WEB_ORIGINS=https://safe-dashboard-avelury04-4128.vercel.app
   .venv/bin/python -m uvicorn backend.browser_camera_api:create_app --factory --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
   ```

   Set `FIREBASE_SERVICE_ACCOUNT` to the actual saved file before running this
   command. This entry point does not open the laptop camera or an OpenCV window.
   It uses the existing YOLO model and detector thresholds without changing
   prolonged-sitting behaviour. Use one worker: tracking state is in memory.
3. Provide an HTTPS tunnel to `http://127.0.0.1:8001` using your approved tunnel
   service. Do not disable Firebase authorization or enable wildcard CORS.
   All ingestion routes require a Firebase bearer token and an active admin
   profile; the endpoint URL is not a credential. Keep the tunnel running for
   the demonstration and shut it down afterward.
4. Test the backend and CORS using the exact production frontend origin.
   Add the tunnel's bare HTTPS origin as Vercel Production environment variable
   `VITE_BROWSER_DETECTOR_ORIGIN`, then redeploy the frontend. Do not use a route,
   `localhost`, or `VITE_MEDIA_API_ORIGIN`. A changing tunnel URL requires another
   frontend build. No Admin SDK key belongs in Vercel for this architecture.
5. Sign in as an admin, connect the webcam, then explicitly select **Start
   detection**. This starts transmitting reduced-resolution JPEG frames to the
   laptop. Stop detection keeps preview running; Stop webcam stops both.

## Contract and safeguards

- `POST /api/browser-camera/sessions`: create one exclusive demo session.
- `POST /api/browser-camera/sessions/{id}/frames`: JPEG input, JPEG overlay output.
- `DELETE /api/browser-camera/sessions/{id}`: end the owner's session.
- Session creation/deletion perform fresh Firebase token, revocation and active
  admin checks. Frame uploads reuse a successful check for the exact same token
  for at most one second, never beyond the token's expiration. Role changes,
  account disablement or revocation can therefore take up to one extra second
  to apply during streaming. Failed checks are never cached, and the cache holds
  at most one token's authorization result. Session ownership is checked on every
  frame, including cache hits.
- Session IDs are random and ownership is checked separately. Another admin
  cannot read or submit to someone else's session. Only one session is supported
  on the laptop, and idle sessions become unavailable after 15 seconds.
- Requests are sequential with no frame backlog. JPEG payloads are capped at
  500 KB and dimensions at 1280 x 720 before decoding. The browser captures at
  most 640 x 480 for inference. Actual performance depends on laptop hardware.
- The live camera view stays separate from returned detection frames. Select
  **Detection frames** to inspect the latest bounding boxes and pose overlays.
  The displayed detection FPS measures completed frame round trips, not webcam
  FPS. Uploads are capped at approximately 10 FPS; slow requests start the next
  capture immediately instead of adding a fixed 100 ms pause.
- No audio, raw frame persistence, Firebase Storage uploads or video recording.
- Recognised events write timestamped `incidents` documents using the dashboard
  schema, with session-scoped person references and `recordingAvailable: false`.
- The detector suppresses duplicate events for an already-alerted track, but
  permits a later fall to create a separate incident after a lower-priority alert.
  Dashboard resolution does not reset this browser session's
  tracking state; restart detection for a new controlled test.
- Fall timing permits a direct standing-to-lying transition when sampled frames
  miss the descent. First appearing already lying down still does not establish
  a fall. Unreliable shoulder/hip landmarks show `Fall: pose unclear` on processed
  frames; do not treat missing pose evidence as a negative fall assessment.
- A missing backend or failed incident write stops the upload loop and displays
  an error. The frontend never labels a local-only preview as active detection.

## Verification boundaries

Unit tests cover lifecycle, auth, session ownership/expiry, CORS, payload limits,
malformed frames and metadata mapping. Browser tests use simulated video and
stubbed API responses, not residents, real Firebase credentials or a live tunnel.
Live Firebase writes, real-device accuracy, the tunnel and multi-device use must
be verified after credential setup. Fall and distress alerts are prototype
signals, not medical diagnoses or a safety guarantee.

### Fall regression checks (11 October 2026)

Unit regressions cover direct standing-to-lying transitions, horizontal versus
seated poses, missing-pose diagnostics, and fall escalation after another alert.
An offline run of the three bundled clips used the real model with a mock event
writer, without Firebase writes. At 10 sampled FPS, `Fall test.mp4` produced a
fall at 2.6 seconds; neither other clip produced a fall. At 2 sampled FPS, none
of the three produced a fall. One AVI also reported decoder corruption. These
are limited diagnostic checks, not an accuracy evaluation or a claim that the
prototype reliably detects falls. Camera framing, tracking continuity, valid
pose landmarks and processed frame rate remain important limitations.
