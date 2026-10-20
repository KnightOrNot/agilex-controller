# Repository Guidelines

## Project Structure & Responsibilities

- `src/agilex_controller/` owns configuration, client composition, SDK subprocess lifecycle, JS positioning, following, and raw RGB-D recording.
- `src/agilex_data_collection/` owns the parallel browser collection app, hardware worker, preview encoding and LeLab integration. Both entries are first-class and commonly used.
- `config/default.toml` is the single application config: controller sections plus the `[collection]` table for the browser app. It contains installation-specific GELLO calibration. Pass calibration through `DynamixelRobotConfig`; do not patch the library's port map for this installation.
- `agilex-gello-software/`, `agilex-sdk-python/`, `lerobot-converter/`, `camera-realsense/`, and `agilex-adapters/` are independent Git submodules. Keep robot hardware access in SDK, camera acquisition in its library, timestamp matching/conversion in converter, and LeRobot device protocols in adapters.
- GELLO preserves upstream `gello/`, tools, and configs; local adaptations belong in its `src/`. Its pinned DynamixelSDK submodule is a required uv source. Run its offline upstream audit after changes.
- `scripts/` contains five Shell entry points: setup and four thin controller wrappers for legacy/camera following and recording. New camera wrappers enable capture and preview; keep the legacy defaults camera-free.
- `tests/` covers controller behavior; `docs/` contains architecture, installation, CLI, configuration, and troubleshooting. Preserve hardware reference assets.
- `data/raw/` is immutable input; `data/lerobot/` is regenerated output. Neither belongs in Git.

Camera owns reusable acquisition and SDK-to-host clock mapping; controller owns lifecycle and raw persistence; converter owns timestamp matching and LeRobot output. Preserve native Z16 depth and calibration. The robot SDK hardware layer remains unchanged; its standalone CLI/server defaults now load the SDK TOML.

## Build, Test, and Development Commands

Use Python 3.11 for controller/GELLO/SDK/camera development and 3.12 for converter and the browser collection app. Controller installs GELLO and camera as local editable dependencies; SDK, converter and adapters use their own interpreters.

- `./scripts/setup.sh --skip-system --skip-submodules`: synchronize environments while preserving local submodule work.
- `./scripts/setup.sh --check-only`: inspect installation without hardware access.
- `uv run --frozen agilex-controller --help`: inspect commands.
- `uv run agilex-data-collection setup` and `serve --simulate`: prepare and run the browser app without hardware.
- `uv run --frozen pytest`: run hardware-free regressions and the real converter round trip when its environment exists.
- `uv run --frozen ruff check src tests` and `uv run --frozen ruff format --check src tests`: validate controller style.
- `uv build`: build distributions.
- `bash -n scripts/*.sh`: validate shell syntax.

## Coding & Testing Guidelines

Use four-space indentation, annotated public interfaces, snake_case functions/modules, and PascalCase classes. Test files use `test_*.py`; no coverage threshold is configured. Mock hardware, but exercise real local ZMQ and raw compatibility. Test errors, interruption, initialization failures, and cleanup order. Real hardware verification requires the documented setup and operator confirmation.

Preserve upstream style in GELLO; avoid unrelated formatting. Run its pytest and existing CI lint from its directory.

## Commits & Pull Requests

Prefer concise imperative messages with conventional prefixes. Independent GELLO and submodule checkouts do not synchronize automatically. Publish tested submodule commits before updating parent gitlinks. PRs should state behavior, affected repositories, checks, hardware-validation status, and relevant issues. Update usage/configuration documentation alongside behavior changes.

## Parallel Controller and Browser Collection

All current development uses `dev`, based on remote main at `de53db9`.
`agilex-controller` (CLI follow/record/raw/convert) and
`agilex-data-collection` (browser LeRobot/LeLab collection) are two parallel,
commonly used entry points. Both are documented in `README.md`; there are no
separate collection manuals. New application code belongs in
`src/agilex_data_collection/`; `agilex-adapters/` is a separate Git submodule and
also develops on `dev`. Both entries read the single `config/default.toml`;
the browser app uses its `[collection]` table and only ignores it in the legacy
loader, not the other way around.

The 3.11 `agilex-data-collection` entry bootstraps a separate 3.12 environment in
`agilex-adapters/.venv`. Adapters implement LeRobot Robot/Teleoperator protocols;
the application owns web UI, worker lifecycle, control and persistence. The 3.11
worker reuses existing low-level hardware helpers without invoking the old
workflow, shares its hardware lock, and uses owner-private Unix IPC with a command
watchdog. Do not expose pickle IPC over TCP or run competing control loops.

Read `README.md` and `docs/index.md` before changes. Run root regressions plus
`uv run --project agilex-adapters --extra app pytest agilex-adapters/tests -q`.
Simulation must not access physical hardware. Report actual hardware verification
separately. The new raw app format is independent of legacy converter input;
preserve native Z16, calibration and monotonic timing provenance.

The user now requires an immediate checkpoint here and no further implementation once
their five-hour AI allowance reaches 15% (replaces the previous 10%). This quota is not exposed to the agent;
honor any user notification, recording completed work, checks, failures and TODOs.

### Current Implementation Checkpoint

Implemented an independent browser panel for follow/record/save/discard/stop,
LeRobot RGB video and meter-depth output, immutable sampled RGB/Z16 inputs and
timing audit, plus the official LeLab dataset browser. LeLab browsing, local
merge (POST `/datasets/merge`), HF upload (POST `/upload-dataset`), dataset info
and HF login are exposed; local dataset deletion is exposed with an
active-session guard and no Hub-deletion option. Motion, SO101 calibration,
training/inference and Hub deletion remain intentionally unavailable. The
embedded page disables unimplemented controls and direct unimplemented SPA
paths redirect to `/dataset-browser`; `/jobs` intentionally stays 404.
LeRobot is pinned to the matching PyPI 0.6.0 release; LeLab is pinned to
`9b5afaee33baa1d773e499937564f3831d25de22`. Keep the explicit nested extras closure
in the uv override: omitting it loses dataset dependencies; the upstream Git
LeRobot source conflicts with the CPU torch index.

Verified: 91 controller tests, 21 adapter/application tests (including real RGB-D
save/discard/readback and write-failure cleanup), Ruff, both builds, actual CLI
setup/start and HTTP smoke checks. Heavy dataset imports run before hardware
startup to avoid first-record GIL stalls. Browser routing carries LeLab's supported
`?api=` override so localhost/127.0.0.1 and custom ports work without CORS patches.

Pending: operator-supervised physical GELLO/PiPER-X/RealSense validation, sustained
full-resolution throughput and timestamp-quality measurement. No physical motion
was performed. Camera/configuration changes are recorded in local `dev` commits
across the controller and five submodules, as authorized by the user. Remote
publication still requires authorization.

## Submodule Configuration and Camera Profiles

All five first-party submodules now expose `config/default.toml`; use each
repository's local configuration loader, not the parent TOML implicitly. Four
new loaders support partial overrides; camera retains its full-file selection
contract. Packaged default TOML links point at the one repository source and
are materialized into wheels; validate wheel imports when changing packaging.
Keep upstream nested submodules and GELLO native YAML tools unchanged.

Camera performance defaults prefer 640x360@90, then 60, then baseline-resolution
30 FPS, probing each stream's actual received rate before exposing frames.
`ColorStream` callers that explicitly supply a profile keep manual semantics
unless they explicitly select a mode. The independent app passes camera_mode
from `[collection]` in `config/default.toml` (auto by default); legacy controller
profiles remain unchanged. Read docs/reference/submodule-config.md and the camera config
reference. Do not switch profiles in an active recorded stream or lose native
Z16, timestamp provenance or final-profile calibration. Physical throughput
validation remains pending; this session found no connected RealSense device.

Latest camera/configuration validation: 298 tests passed across controller (91),
camera (64), SDK (65), GELLO (29), converter (28) and adapters (21). Camera and
SDK Pyright, per-repository lint, GELLO offline upstream audit and distribution
builds passed. All five wheels were extracted outside the checkout and loaded
their materialized defaults, matching the repository TOML. No camera capture,
CAN motion or remote push was performed for this update.

### Physical Startup Investigation (2026-10-20)

The operator's session `20261020_121045_811fe47f` passed CAN/camera initialization
but failed JS zero arrival: J3 remained +1.032 degrees, exceeding the then-1-degree
tolerance at startup and cleanup. Read-only motor diagnostics found all joints
enabled, fresh feedback (~3.6 ms), no reported motor/arm faults, J3 +1.032 degrees
and CAN UP at 1 Mbit/s with zero reported bus errors. The user initially chose to
retain 1 degree and to avoid offsets, motion-mode changes and automatic
recalibration.

Session `20261020_153551_6f98d01b` failed again with J3 at 1.015 degrees. The SDK
`limits` output shows J3's nominal range is -170..0 degrees, so its zero position
is the upper limit. At rest the joint output reported +1.015 degrees, the motor
side +0.516 degrees, with -7.6 N*m holding torque, enabled, and no fault bits. The
~0.5-degree difference is output-side compliance/backlash under load at the
limit. The user then explicitly authorized raising `position_tolerance_deg` to
**1.1 degrees**; this supersedes the earlier 1-degree choice. Still do not subtract
an offset, change motion mode or recalibrate automatically.

New app positioning logs stage, six-axis start/final feedback, residuals, observed
range and successful command count without adding RPCs. The worker reports primary
and cleanup errors separately; the browser must prefer structured diagnostics over
buffered cleanup messages. Startup and exit use the same configured tolerance
(now 1.1 degrees). Only the operator performed motion; agent checks were read-only
or simulated. Pending: operator-supervised motion-response investigation.

The operator's subsequent session `20261020_121535_49fee27a` passed startup zero
(J3 residual 0.921 degrees), GELLO alignment and exit zero within the then-1-degree
tolerance. Its
first saved episode contains 513 frames at 30 FPS. The operator explicitly
reported pressing Ctrl+C; do not infer a save-time GIL stall from that session's
heartbeat timeout alone. Repeatability of the earlier 1.032-degree residual is
still unverified. Latest checks: 108 root tests and 22 adapter/app tests passed,
Ruff and the root build passed. Test flock files are isolated in pytest temporary
directories so simulations do not contend with the live operator's hardware lock;
production old/new mutual exclusion remains unchanged. Changes are uncommitted.

## Collection UI Optimization Roadmap (2026-10-20)

Work incrementally on `dev`, preserving the old controller workflow. Stop new
implementation immediately when the user reports 15% of the five-hour allowance
remaining; record completed work, checks, failures and TODOs here. Remaining quota
is not available through agent tools; never claim to monitor it automatically.

Requested work, in order:

1. **Implemented, mock-verified:** configure CAN when starting the new collection server, using the
   SDK's existing script and hardware TOML interface/bitrate. Run in the terminal
   where sudo can prompt; preserve the shared hardware lock and skip completely
   for simulation. Environment installation must remain hardware-free.
2. **Implemented:** remove the unused local-dataset-list link from the collection UI.
3. **Implemented, HTTP-verified:** provide a reliable route from the official LeLab browser back to
   collection, without modifying the upstream LeLab frontend.
4. **Implemented; visual review pending:** make collection compact and attractive; remove the long startup
   warning paragraph requested by the user. Preserve the explicit unchecked motion
   confirmation, backend guard and configured positioning acceptance
   (`position_tolerance_deg`, now 1.1 degrees).
5. **Implemented; simulation browser, regression and packaging verified; hardware review pending:** improve camera preview: show actual FPS/resolution/mode beneath it,
   target dataset FPS rather than the current 1 Hz status refresh, offer multiple
   RGB/depth views and an interactive 3D point cloud with mouse view manipulation.
   Keep native Z16, calibration and timestamp provenance; preview must not delay
   control or recording. Distinguish measured preview FPS, capture FPS and dataset
   FPS. Use calibrated deprojection/extrinsics for point cloud, not guessed depth.

Baseline: 108 root tests and 24 adapter/app tests passed; Ruff and builds passed.
Confirmed UI 409 was caused by an unchecked motion confirmation. The UI now gates
start on confirmation/task/status, prevents duplicate start submissions and reports
Chinese reasons. Previous fixes remain uncommitted; do not push or commit unless
requested. No new hardware motion is authorized by this optimization task.

Steps 1–4 checkpoint: `serve` configures CAN using the selected app/hardware TOML
under the existing lock before exec; simulation and setup skip it, failure prevents
server startup. No live CAN configuration was run by the agent. `/dataset-browser`
wraps the unchanged official `/edit-dataset` UI with a permanent return link.
Only the unused UI list link was removed; `/datasets` remains for official LeLab.
Compact UI keeps confirmation and hides raw status in expandable details. Targeted
checks: 30 entry/config/worker tests and 3 web/script tests passed.

### Step 5 Checkpoint — Preview Optimization

An earlier allowance-exhausted checkpoint stopped implementation. The user later
explicitly authorized completion of the remaining optimization work. Step 5 is now
implemented and verified in simulation and a real headless browser; only physical
hardware review remains. Do not push unless the user requests it.

**Step 5 implementation:**

- `preview.py` provides display-only depth colors, side-by-side native RGB/depth,
  and depth-camera XYZ deprojection. Native Z16 and captured arrays are unchanged.
  Point clouds require supported rectified intrinsics with zero distortion; reject
  unsupported calibration. Colors encode depth, not RGB texture: no extrinsic RGB
  projection is performed. Output is little-endian float32 XYZ meters, max 20000
  points. TOML adds `preview_depth_max_m=3.0`, `preview_cloud_stride=4`.
- Session publishes immutable latest frame references, camera metadata, per-session
  generation/sequence and observed sampling FPS. Encoding/calculation run outside
  the control thread. Generation guards prevent cross-session cached frames.
- `/api/preview/ws?mode=rgb|depth|rgbd|cloud` streams metadata plus JPEG/XYZ, targeting
  dataset FPS; status polling remains 1 Hz. Same-origin check and two-viewer limit
  are implemented; the slot is claimed before the accept await so concurrent
  handshakes cannot exceed the limit, and disconnects release it. Fixed deadlines
  avoid cumulative drift; old display frames are dropped rather than replayed.
  The original JPEG endpoint remains compatible.
- Homepage displays actual browser presentation FPS, observed/target sample FPS,
  measured capture FPS from startup probing (profile fallback), and mode-correct
  dimensions: `depth`/`cloud` report native depth dimensions and depth FPS, `rgbd`
  reports both streams separately on a side-by-side image.
  The FPS clock starts after the first decode so WebGL shader setup cannot depress
  the first reading. Native WebGL in `pointcloud.js` implements pointer orbit,
  wheel zoom and double-click reset; it has no CDN dependencies. Compact UI has a
  visible phase/saved-episode badge and foreground error summary (retested).

**Checks completed for the finished optimization:**

- Full root suite: 118 passed. Full adapter/application suite: 32 passed. Ruff
  check and format verification passed in both repositories. Root and adapter
  distributions built successfully.
- `pointcloud.js` is present in the built root wheel, imports outside the checkout,
  and `/collection-assets/pointcloud.js` is served with a JavaScript MIME type.
- Headless Firefox (WebDriver/geckodriver) against an isolated `--simulate` server
  rendered the real page. RGB, depth, RGB + depth and WebGL cloud modes each
  delivered ~30 FPS at 64x48; RGB + depth labeled both streams; cloud showed 192
  points, and synthetic drag/zoom/double-click changed the rendered view. Stop
  changed the page to `已结束` and the preview to `预览未运行`. Screenshots are
  temporary `/tmp` artifacts, not repository files. This was Firefox with software
  WebGL at simulation resolution, not physical hardware or full-resolution QA.
- New tests cover missing depth errors, two-viewer capacity and slot release,
  viewer asset MIME, frame/generation invalidation on session restart, mode-correct
  resolution/FPS labels, and the extended Node control harness.
- Earlier measurements remain valid: isolated simulation delivered ~30 FPS per
  WebSocket mode after deadline correction, and read-only saved metadata confirms
  D455F USB 3.2, 640x360@90 selection, rectified depth intrinsics and native units.
- `README.md`, `docs/index.md` and CHANGELOG document preview modes,
  FPS/dimension labels, point-cloud calibration rules, limits and errors.

**Remaining — operator-authorized hardware only:**

1. Measure full-resolution RealSense preview/record throughput and timing; verify
   CAN startup/sudo behavior on real hardware. Keep the configured arrival
   acceptance (1.1 degrees after the user's 2026-10-20 decision). Simulation and
   headless browser checks do not prove physical safety, timing or sustained
   throughput.
2. Review responsive layout on the operator's display and long-running multiple-tab
   behavior under a real camera stream.

**Local resources:** agent-created simulation servers on ports 18081/18082 and
geckodriver were stopped. The user's port-8000 service (PID 36352) was alive before
agent background-task cleanup and was gone afterwards. It was not targeted
directly, but process-group termination may have affected it; verify and restart
only under operator authorization. Synthetic session artifacts may exist under
`data/raw/app/` and `data/lerobot/app/`; do not confuse them with operator data or
delete immutable raw.

### LeLab Dataset Merge, Upload & Delete (2026-10-20)

The user chose to keep `/jobs` at its expected 404, leave LeLab's top navigation
in English, disable all unimplemented feature controls, and implement the
Browse dataset **Merge**, **Upload** and local **Delete** actions.

Implemented in `src/agilex_data_collection/runtime.py`:

- Official POST routes are proxied: `/datasets/merge`, `/upload-dataset`,
  `/dataset-info` and `/hf-auth/login`. Merge writes a new `local/<name>` under
  `data/lerobot/app` without touching sources; upload delegates to LeLab's
  `push_to_hub` flow and requires operator HF authentication. `GET /jobs` and
  `/jobs/hub` remain 404 by choice.
- `/delete-dataset` is an application-owned route (not a blind proxy): it accepts
  only local deletion, returns a structured 400 when `delete_from_hub` is set,
  404 for an unknown dataset and 409 when the dataset belongs to an active
  session. The official handler performs the guarded `rmtree` inside the
  configured cache root.
- LeRobot freezes `HF_LEROBOT_HOME` at import. `create_app` also rebinds
  `lerobot.datasets.dataset_metadata.HF_LEROBOT_HOME` to the configured data
  root, so upload, delete and dataset-info address local datasets instead of
  trying the Hub.
- `/dataset-browser` injects a policy into the same-origin LeLab iframe (with a
  MutationObserver for React re-renders): Back/Back to Home, Skip Upload,
  Record more, Create new dataset and the guided-tour trigger are disabled.
  The Hub-deletion checkbox is disabled, while Merge/Upload/Delete, dataset
  selection, episode playback and the upload form stay enabled. A `pushState`/
  `replaceState` shim rewrites unimplemented routes to `/edit-dataset`, so the
  post-delete callback returns to the dataset list instead of LeLab home. A
  `fetch` wrapper also reloads `/edit-dataset` after a successful
  `/delete-dataset`, so the official React picker refetches and no longer shows
  the removed name; failed deletes do not reload.
  Unimplemented SPA paths (`/recording`, `/teleoperation`, `/training`,
  `/training/{id}`, `/inference`, `/calibration`) redirect server-side to
  `/dataset-browser`.

Verified: 118 root tests and 41 adapter/application tests passed; Ruff and both
builds passed; the wrapper policy runs under Node with fake DOM (including
history rewriting and post-delete reload). Headless Firefox confirmed disabled
controls, an enabled Delete button/dialog, a real merge modal that enables only
after selecting a second dataset and entering a name, an upload page whose
dataset summary loads through `/dataset-info` with the Upload action enabled,
and a delete followed by a picker reload that exposed only the remaining
dataset. No actual Hugging
Face upload was performed (it would publish data externally); upload was tested
with a monkeypatched `push_to_hub`. Merge and local delete were exercised through
the real official handlers using synthetic probe datasets, not operator data.
Documentation and CHANGELOG updated.

### Collection UI Information Cleanup (2026-10-20)

The user asked to remove developer-facing information from all collection pages,
while explicitly choosing to keep: preview FPS/resolution/capture statistics,
all LeLab dataset metadata (ROBOT/CAMERAS/FPS/Repository ID on the dataset page),
disabled controls/Jobs sidebar/welcome tour, and upload tags/private fields.

Implemented: the home page no longer renders the raw status JSON ("会话详情" and
`<pre id="status">` are gone); the upload page hides the Repository ID row and the
"About HuggingFace Hub Upload" block while retaining the dataset summary, tags,
private toggle and Upload action; the merge dialog hides the internal
"Saved locally as local/<name>" hint. Hidden nodes are re-hidden by the existing
MutationObserver. Headless Firefox verified the cleaned home, dataset, merge and
upload pages with a synthetic dataset. Tests: 118 root and 41 adapter/application
passed; Ruff and builds passed. Changes remain uncommitted.

### Documentation and Configuration Consolidation (2026-10-20)

The user declared `agilex-controller` and `agilex-data-collection` two parallel,
equally used entry points rather than a primary project plus extension. The
consolidation is documentation-first, with the minimum code needed for one config
file:

- `README.md` now covers both entries end to end (install, config, CLI workflow,
  browser collection, preview, JS tolerance, data, LeLab, troubleshooting).
  `docs/data-collection.md` and `docs/data-collection-quickstart.md` were deleted;
  their useful content moved into README, `docs/index.md`, `docs/installation.md`,
  `docs/reference/{config,cli,errors}.md` and `docs/reference/submodule-config.md`.
- `CHANGELOG.md` was reduced to a concise per-version summary (`0.1.0` and the
  initial `0.0.0` development line) instead of a long unreleased list.
- `config/data_collection.toml` was removed. Collection settings now live in
  `config/default.toml` under `[collection]`; an empty
  `[collection].hardware_config` means `[robot]`/`[gello]`/`[camera]`/`[paths]`
  are read from that same file, so a copied experiment TOML stays self-contained.
  `AppConfig.load` reads the `[collection]` table when present and still accepts
  a standalone flat TOML (existing tests and custom minimal files). The legacy
  loader reserves but ignores `[collection]`; no other controller section changed.
- Default config paths in `agilex_data_collection/__init__.py` and `runtime.py`
  now resolve to `config/default.toml`.
- `agilex-adapters/README.md` and `CONTRIBUTING.md` links were updated to the new
  documentation; the submodule README edit leaves that submodule dirty until a
  separate commit is requested.

Checks: targeted configuration/collection tests passed before the documentation
pass; run the full root suite, adapter/app suite, Ruff and builds after any further
edit. No code path, hardware behavior or dataset format changed. Changes remain
uncommitted; do not push unless requested.
