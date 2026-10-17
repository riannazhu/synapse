# Synapse frontend — Track C

React + TypeScript + Vite. This is a browser-local prototype connected to Track
B's fictional data, not the authenticated production API. No model key is used
or needed in the frontend. Keep Gemini keys in the root server-only .env.

## Run

Use Node 22.18+ (or newer supported Node 24/26) and npm:

```bash
cd web
npm install
npm run dev
```

Open the Local URL printed by Vite, normally http://127.0.0.1:5173.

```bash
npm test          # 15 domain, geometry, and mock persistence checks
npm run build    # TypeScript check + production bundle
npm run test:e2e # browser flows; requires installed Google Chrome
```

The Playwright config uses your installed Chrome, starts its own local dev
server on port 5181 (separate from your preview), and stops it at completion.
Five browser checks cover the core flows and 3D gestures. The screenshot test writes a desktop image
to /tmp/synapse-track-c-desktop.png. It uses fresh test browser contexts, not
your normal Chrome profile. It makes no model API calls.

## Implemented prototype

- Responsive dashboard, journal, map, and reflection surfaces.
- Perspective 3D brain with two hemispheres, cortical contours, a cerebellum,
  brainstem, glowing topic anchors and curved co-mention fibers. Only actual
  fixture topics/edges appear; no additional decorative evidence is invented.
- Keyboard-operable topics and edges, count/share list alternative, period
  filters, synchronized comparison, fixed coordinates, and source highlights.
- Journal search, local creation/edit/delete, revisions, stale-evidence removal.
- 800 ms draft autosave with serialized writes and flush before commit/close.
  Draft conflicts preserve text; local storage errors do not report success.
- Write/chat/voice/handwriting composer. Scripted chat drafts include user
  statements only. Voice supports microphone permission, record, pause/resume,
  stop, playback and file fallback. Images support upload/camera selection,
  reordering, removal and preview rotation. Crop/retake stays in the camera app.
- Explicit review checkbox for appended sample extraction or conversation text.
- Reflection/check-up and recap shells with clear sample labeling. They are not
  Track D recommendation/report generation or persisted feedback.

Saved text and drafts use this browser's localStorage. Recordings/photos and
conversation messages are temporary and are not attached or uploaded. Switching
capture modes closes that capture component; its unsaved media is discarded.
New/edited approved entries are marked analysis unavailable until A is connected;
we do not pretend arbitrary new writing has been analyzed by Track B.

## 3D brain controls

- Drag with a mouse or one finger to orbit the brain.
- Two-finger trackpad scroll pans; shift-drag or right-drag also pans.
- Trackpad pinch zooms; the +/− buttons work with every input device.
- Two fingers on a touchscreen pan/pinch. Double-click or the percentage button
  resets the complete view.
- Focus the map: arrow keys rotate, shift-arrow keys pan, +/− zoom, Home resets.

The brain is a procedural illustrative model, not an anatomical assignment of
journal topics to brain regions. brain.ts contains actual x/y/z geometry and
perspective projection. NeuronMap renders it on a high-DPI canvas with accessible
HTML topic/edge buttons following the projected coordinates. The anatomy is a
surface scaffold; only journal co-mentions produce evidence-bearing fibers.
Drawing is requested on interaction/data/resize, with no perpetual animation.
Camera state and topic anchors remain stable when changing date filters.
The List view remains available for exact counts and shares.

## Backend boundary and remaining work

src/state/api.ts is the mock boundary. Replace it with A's authenticated /api/v1
entry/draft/commit/upload/job/graph/evidence calls. The small aggregation in
model.ts is for offline fixture behavior; production graphs must come from B
through A, not a second browser-owned journal interpretation.

The seed imports fixtures/demo_journal.json and fixtures/generated/graph.json
from the parent repository. Regenerate them with python3 -m server.demo when
needed. The frontend parity test checks the fixture against Python's graph.

Still required: real authentication/login and account isolation; versioned server
draft persistence and richer conflict merge/reload; private attachment upload,
extraction states/retry and job polling; server-backed history/chat; reviewed
block inclusion and media retention; goal confirmations; persisted check-up
feedback/snoozes and full Wrapped. There is no hosted deployment in this change.

Mock storage checks stale versions across tabs, but localStorage is not a
transactional database. Authentication, atomic checks, idempotency and deletion
invalidation remain A's responsibility. Fixture source offsets are Unicode
code points; highlighting uses Array.from instead of raw JavaScript offsets.
