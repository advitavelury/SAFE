# SAFE — dashboard foundation

Front-end for the Smart Assisted Fall Emergency monitoring system.
This repo is **UI only**. Detection, video, and persistence live elsewhere.

## Run it

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # -> dist/
```

Requires Node 18+.

## Stack

Vite · React 18 · Tailwind CSS 4 · lucide-react

## Layout

```
src/
  App.jsx              layout + all dashboard state
  theme.js             colour tokens and font stack
  api/feeds.js         <- the only file that knows where data comes from
  data/                mock incidents, zones, pose templates
  components/
    ui.jsx             Panel, SectionTitle, Dot, Toggle, Select
    Calendar.jsx       month grid, incident-tinted days
    AlertCard.jsx      one incident, used in both rails
    CameraStage.jsx    video surface + detection boxes + skeleton/blur overlays
  hooks/               useClock, usePrefersReducedMotion
  utils/date.js        iso, fmtTime, relDay
```

## Connecting the backend

Everything downstream reads from `src/api/feeds.js`. Replace the two hooks,
keep the return shapes, and no component needs to change.

```js
useIncidentFeed()  -> [{ id, type, status, zoneId, ts: Date, note?, responder? }]
useDetectionFeed() -> [{ id, conf, state, pose, box: { x, y, w, h } }]
```

- `type` is one of `fall` | `distress` | `false`
- `state` is one of `normal` | `fall` | `distress`
- `box` values are **percentages of the stage**, not pixels — convert from
  YOLO's normalised xywh by multiplying by 100
- `pose` selects a template in `data/poses.js`; swap for real MediaPipe
  landmarks by replacing the `Skeleton` component's lookup with the
  33-landmark array

The video surface is `StageBackdrop` in `CameraStage.jsx` — a placeholder
drawn in CSS. Replace it with `<video>` or an MJPEG `<img>`; the overlay
layer sits on top and needs no changes.

## Known gaps

- Review and Settings views are stubs — the selector switches state but
  renders the same Monitor layout
- SMS and audio alert toggles are UI-only, no dispatch wired up
- No auth, no routing, no tests
