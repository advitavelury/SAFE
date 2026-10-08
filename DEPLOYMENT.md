# SAFE dashboard on Vercel

## Scope

Deploy the `deployment` branch with Vercel's project root set to `front-end`.
This is a dashboard deployment, not a hosted YOLO or camera server. Staff use
the shared URL and their approved Firebase login; they do not install Node or
configure Firebase on their computers. Nothing in this branch automatically
publishes Firebase rules, provisions users, or deploys a Vercel project.

The dashboard reads the existing `incidents` collection and its `reviews`
subcollections. The current Python backend writes a different `events` schema.
Do not change the collection variable to `events`: an adapter, matching review
workflow and rules are still needed to integrate those records. Admin writes
must be tested against the deployed rules before treating this as operational.

## Vercel setup

1. In Vercel, choose Add New Project and import `advitavelury/SAFE`.
2. Select `deployment` as the source branch for this dashboard deployment.
   If the import screen defaults to `main`, change the project's Production
   Branch to `deployment` under Settings -> Environments -> Production before
   sharing the production URL. Create a deployment from `deployment` using the
   Deployments page if needed; verify its commit before promoting or sharing.
3. Set Root Directory to `front-end`. Framework: Vite. Install: `npm ci`.
   Build: `npm test && npm run build`. Output: `dist`.
   The checked-in `front-end/vercel.json` provides the framework/build settings
   and response security headers; Root Directory is a Vercel project setting.
4. Add the public web configuration below for Production. For branch previews,
   set the corresponding Preview variables deliberately. A preview using the
   same project can read/write the same records as production when an approved
   admin signs in; use test incidents, never real resident data, for validation.
5. Deploy and inspect the build logs. Missing Firebase fields, a wrong project,
   an incompatible collection or an insecure media origin fail the build with
   a setup error. Redeploy after changing environment variables: Vite embeds
   the public configuration at build time.
6. Test the generated HTTPS URL in a separate browser/device. If Vercel's
   deployment protection asks for a Vercel account, use the project's intended
   production access settings or explicitly grant preview access. Firebase
   staff authentication and database rules must remain enabled either way.

## Environment variables

Use Firebase Console -> safe-ddacb -> Project settings -> Your apps -> Web app.
These are public web configuration values, not Admin SDK credentials.

| Variable | Value |
| --- | --- |
| `VITE_FIREBASE_API_KEY` | Web app `apiKey` |
| `VITE_FIREBASE_AUTH_DOMAIN` | `safe-ddacb.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | `safe-ddacb` |
| `VITE_FIREBASE_STORAGE_BUCKET` | `safe-ddacb.firebasestorage.app` |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Web app `messagingSenderId` |
| `VITE_FIREBASE_APP_ID` | Web app `appId` |
| `VITE_FIREBASE_INCIDENTS_COLLECTION` | `incidents` |
| `VITE_MEDIA_API_ORIGIN` | Leave unset for the initial deployment |

Never put service-account JSON, private keys, passwords, or Firebase ID tokens
in any `VITE_` variable. All `VITE_` values are browser-visible. The Python
backend's `FIREBASE_SERVICE_ACCOUNT` does not belong in this static frontend.

## Firebase checks

- Keep Email/Password sign-in enabled in the existing project.
- Each staff account must have a matching `users/{UID}` document containing
  boolean `active: true` and role exactly `admin` or `operator`.
- Publish the complete root `firestore.rules`, not just the profile rule.
  Review any console-only changes first rather than overwriting them blindly.
- Add the intended deployment domain to Firebase Authentication's authorized
  domains when using domain-dependent auth flows such as redirects or email
  action links. Keep `authDomain` set to the Firebase value above; do not replace
  it with the Vercel URL merely because the frontend is hosted there.
- Do not enable public database reads/writes to make deployment work.

## Camera and playback

With no `VITE_MEDIA_API_ORIGIN`, production builds do not poll camera/clip APIs.
They show an unavailable state and hide ineffective media controls. Firebase
sign-in, incident filters and authorized reviews do not depend on that service.
Development (`npm run dev`) retains the existing localhost Vite proxy.

Only configure an HTTPS origin after a compatible service exists. Use a bare
origin such as `https://camera.example.com`, not `/video_feed`, an API path,
localhost, or a URL containing credentials. The client adds these paths:

- `GET /api/camera/status`, returning the existing zone/state contract.
- `GET /api/camera/frame`, returning an authenticated image snapshot.
- `POST /api/camera/start` and `/api/camera/stop`, restricted to admins.
- `GET /api/incidents/{id}/clip`, returning recording metadata.
- `GET /api/incidents/{id}/clip/file`, returning the recording bytes.

The current FastAPI `/events` and `/video_feed` routes do not implement this
contract. Merely exposing that server or adding CORS will not make it compatible.
The next integration task must adapt these clients or provide matching endpoints,
validate Firebase bearer tokens, allow only the intended frontend origins for
CORS (including Authorization preflights), and enforce roles on the server.
The client sends bearer tokens only to the configured service and rejects
redirects. Keep the camera machine running; deploying React does not grant a
cloud server access to its webcam. Never expose an unauthenticated camera tunnel.

## Verification checklist

- Fresh browser shows staff sign-in, never incident data before approval.
- Active admin and operator accounts both load authorized incident records.
- Admin can acknowledge/add a note/resolve a designated test incident, and the
  change persists after refresh with a matching review entry.
- Operator cannot perform those writes, including through a direct request.
- Inactive/unapproved users cannot view the dashboard or read records.
- Default production dashboard makes no `/api/camera` or clip requests.
- Missing configuration fails the build rather than deploying a broken login.
- Test on desktop and mobile. Check browser console/network for errors.

Local unit tests and a successful build are not proof of deployed permissions
or end-to-end camera support. Settings still contain browser-only draft values.

## Local verification - 8 October 2026

- All 26 frontend unit tests passed; production build passed with the existing
  large JavaScript bundle warning.
- A build with an intentionally missing Firebase API key failed with the
  expected setup error. No real environment files were modified by that check.
- Playwright with installed Chrome verified the production sign-in screen at
  1440px and 390px widths: no horizontal overflow, JavaScript exceptions or
  media requests. Screenshots were inspected.
- An isolated production-mode fixture rendered the real camera and playback
  components with a simulated admin session, without Firebase credentials.
  Both unavailable messages appeared; no media polling or ineffective controls
  remained at either viewport. This is not a live authenticated dashboard test.
- No Vercel release, Firebase rule publication or remote-camera test was run.

## References

- [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite)
- [Vercel project configuration](https://vercel.com/docs/project-configuration)
- [Vite environment variables](https://vite.dev/guide/env-and-mode)
