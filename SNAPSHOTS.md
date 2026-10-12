# Red-incident snapshots

The browser detection backend can automatically save one redacted JPEG when it
creates a new **red** incident. Amber alerts and ordinary camera frames are not
saved. This is separate from the opt-in local video recorder.

## Enable on the backend

Set `SAFE_SNAPSHOTS_ENABLED=true` in the Python backend's environment and restart
the backend. The default is off. The existing Firebase Admin credential and
`safe-ddacb.firebasestorage.app` bucket are used. Never put the Admin key in Vercel.
No Firebase rules, billing settings or bucket permissions are changed by this code.

The existing bucket must support uploads. Firebase Cloud Storage requires the
Blaze plan; storage and operations count toward the project's existing usage.
Do not enable billing automatically to resolve a failed upload.

## Where to find a snapshot

- Firebase Console -> Storage -> Files -> `incident-snapshots/{incidentId}.jpg`.
- Firestore -> `incidents/{incidentId}` -> `snapshot`: status, capture timestamp,
  bucket, object path, byte count and redaction flag after a successful upload.
- Status is `pending`, `ready`, or `failed`. If the status update fails after an
  upload, the document can stay pending; check the matching object in Storage.

Images are not embedded in Firestore, given public URLs, or displayed in the
dashboard by this feature. Existing approved staff can still read incident/clip
details; recorded-video playback and download remain admin-only.

## Privacy and failure handling

- Redaction happens in memory before JPEG encoding or upload. The shared clip
  redactor pixelates/blurs observed heads, masks uncertain people and hides the
  background. This is not a guarantee of anonymity; use consenting participants.
- Snapshots are at most 640 x 360 and 160 KB, with no audio or source-file metadata.
- A redaction/encoding failure never falls back to saving the raw frame.
- Incident metadata is saved first. Snapshot upload/status-update failures do not
  discard the incident or stop detection. Uploads run in the existing event worker.
- Object creation refuses overwrites, uses a bounded request with no automatic
  retries, and does not create public ACLs or Firebase download tokens.
- Keep Storage client rules deny-all for this backend-only path. The existing
  service account writes via Admin SDK; project members can inspect through Console.
- Snapshots persist until explicitly deleted. The local clip's 24-hour cleanup
  does not remove cloud snapshots. Agree a cloud retention policy before real use.
- No old incidents are backfilled. One snapshot is created per new incident, not
  per video frame; existing track deduplication/escalation rules still apply.

## Validation

Run `python -m unittest discover -s tests` and `npm test --prefix front-end`.
Tests mock Storage/Firestore and cover JPEG redaction, missing landmarks, size
limits, red-only uploads, disabled mode, linking, failures and duplicate alerts.
A live storage write must be separately verified; unit tests do not prove bucket
permissions or billing readiness.
