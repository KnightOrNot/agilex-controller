# Repository Guidelines

## Project Structure & Responsibilities

- `src/agilex_controller/` owns configuration, client composition, SDK subprocess lifecycle, JS positioning, following, and raw RGB-D recording.
- `config/default.toml` contains application defaults and installation-specific GELLO calibration. Pass calibration through `DynamixelRobotConfig`; do not patch the library's port map for this installation.
- `agilex-gello-software/`, `agilex-sdk-python/`, `lerobot-converter/`, and `camera-realsense/` are independent Git submodules. Keep robot hardware access in SDK, camera acquisition in its library, and timestamp matching/conversion in converter.
- GELLO preserves upstream `gello/`, tools, and configs; local adaptations belong in its `src/`. Its pinned DynamixelSDK submodule is a required uv source. Run its offline upstream audit after changes.
- `scripts/` contains five Shell entry points: setup and four thin controller wrappers for legacy/camera following and recording. New camera wrappers enable capture and preview; keep the legacy defaults camera-free.
- `tests/` covers controller behavior; `docs/` contains architecture, installation, CLI, configuration, and troubleshooting. Preserve hardware reference assets.
- `data/raw/` is immutable input; `data/lerobot/` is regenerated output. Neither belongs in Git.

Camera owns reusable acquisition and SDK-to-host clock mapping; controller owns lifecycle and raw persistence; converter owns timestamp matching and LeRobot output. Preserve native Z16 depth and calibration. The robot SDK hardware layer remains unchanged; its standalone CLI/server defaults now load the SDK TOML.

## Build, Test, and Development Commands

Use Python 3.11 for controller/GELLO/SDK/camera development and 3.12 for converter. Controller installs GELLO and camera as local editable dependencies; SDK and converter use their own interpreters.

- `./scripts/setup.sh --skip-system --skip-submodules`: synchronize environments while preserving local submodule work.
- `./scripts/setup.sh --check-only`: inspect installation without hardware access.
- `uv run --frozen agilex-controller --help`: inspect commands.
- `uv run --frozen pytest`: run hardware-free regressions and the real converter round trip when its environment exists.
- `uv run --frozen ruff check src tests` and `uv run --frozen ruff format --check src tests`: validate controller style.
- `uv build`: build distributions.
- `bash -n scripts/*.sh`: validate shell syntax.

## Coding & Testing Guidelines

Use four-space indentation, annotated public interfaces, snake_case functions/modules, and PascalCase classes. Test files use `test_*.py`; no coverage threshold is configured. Mock hardware, but exercise real local ZMQ and raw compatibility. Test errors, interruption, initialization failures, and cleanup order. Real hardware verification requires the documented setup and operator confirmation.

Preserve upstream style in GELLO; avoid unrelated formatting. Run its pytest and existing CI lint from its directory.

## Commits & Pull Requests

Prefer concise imperative messages with conventional prefixes. Independent GELLO and submodule checkouts do not synchronize automatically. Publish tested submodule commits before updating parent gitlinks. PRs should state behavior, affected repositories, checks, hardware-validation status, and relevant issues. Update usage/configuration documentation alongside behavior changes.

## Independent LeRobot / LeLab Collection

All current development uses `dev`, based on remote main at `de53db9`.
Keep the original `src/agilex_controller/`, `config/default.toml`, and five Shell
entry points unchanged for this migration. New application code belongs in
`src/agilex_data_collection/`; `agilex-adapters/` is a separate Git submodule and
also develops on `dev`.

The 3.11 `agilex-data-collection` entry bootstraps a separate 3.12 environment in
`agilex-adapters/.venv`. Adapters implement LeRobot Robot/Teleoperator protocols;
the application owns web UI, worker lifecycle, control and persistence. The 3.11
worker reuses existing low-level hardware helpers without invoking the old
workflow, shares its hardware lock, and uses owner-private Unix IPC with a command
watchdog. Do not expose pickle IPC over TCP or run competing control loops.

Read `docs/data-collection.md` before changes. Run root regressions plus
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
timing audit, plus the official LeLab read-only dataset browser. LeLab motion,
SO101 calibration, training, upload and deletion APIs are intentionally unavailable.
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
from config/data_collection.toml (auto by default); legacy controller profiles
remain unchanged. Read docs/reference/submodule-config.md and the camera config
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
but failed JS zero arrival: J3 remained +1.032 degrees, exceeding 1 degree both
at startup and cleanup. The user explicitly chose to retain 1 degree; do not
relax it, subtract an offset, change motion mode or recalibrate automatically.
Read-only motor diagnostics found all joints enabled, fresh feedback (~3.6 ms),
no reported motor/arm faults, J3 +1.032 degrees and CAN UP at 1 Mbit/s with zero
reported bus errors. These facts do not identify the physical cause.

New app positioning logs stage, six-axis start/final feedback, residuals, observed
range and successful command count without adding RPCs. The worker reports primary
and cleanup errors separately; the browser must prefer structured diagnostics over
buffered cleanup messages. Startup and exit use the app's same 1-degree setting.
Only the operator performed motion; agent checks were read-only or simulated.
Pending: operator-supervised motion-response investigation from the new logs.

The operator's subsequent session `20261020_121535_49fee27a` passed startup zero
(J3 residual 0.921 degrees), GELLO alignment and exit zero within 1 degree. Its
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
   confirmation, backend guard and 1-degree positioning acceptance.
5. **Implemented; final regression, packaging and visual/hardware review pending:** improve camera preview: show actual FPS/resolution/mode beneath it,
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

### Mandatory Stop Checkpoint — Quota Exhausted

The user explicitly reported no remaining allowance and requested this checkpoint.
Implementation is stopped. A subsequent "continue" resumed checkpoint documentation only;
do not resume optimization until the user explicitly authorizes it with renewed
allowance. All edits remain uncommitted on `dev`; do not commit or push implicitly.

**Step 5 implementation now present:**

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
  are implemented. Fixed deadlines avoid cumulative drift; old display frames are
  dropped rather than replayed. The original JPEG endpoint remains compatible.
- Homepage displays actual browser presentation FPS, observed/target sample FPS,
  selected profile dimensions/FPS/mode. Native WebGL in `pointcloud.js` implements
  pointer orbit, wheel zoom and double-click reset; it has no CDN dependencies.
  Compact UI has a visible phase/saved-episode badge and foreground error summary.
  The latest badge/error-summary edit has NOT yet been re-tested.

**Checks actually completed during this optimization:**

- 36 targeted root tests passed: CLI/config/CAN/worker (30) and preview geometry,
  distortion rejection, transfer limits, immutable input (6).
- 8 targeted web/script tests passed: navigation, HTTP confirmation, RGB/depth/
  RGB-D/cloud WebSockets and cross-origin rejection, plus browser script execution
  under Node with fake DOM/network (not an actual rendered browser).
- The extended Node script test subsequently passed independently, exercising mode
  changes, cloud payload handling, status polls preserving the stream, metadata
  display and connection closure on stop. `node --check pointcloud.js` passed.
- Ruff passed before the final small badge/error-summary edit; run again.
- A real isolated `--simulate --port 18081` server delivered 91 frames per mode:
  RGB 30.16, depth 30.00, RGB-D 29.83, cloud 29.99 FPS at a 30 FPS target, after
  correcting deadline drift. These are WebSocket delivery rates using 64x48
  simulation, NOT full-resolution hardware or browser-render FPS measurements.
- Read-only saved camera metadata confirms D455F USB 3.2 selected 640x360@90,
  startup probe ~89.97 FPS per stream, rectified depth intrinsics and native units.
  No physical camera or robot was started by the agent for this optimization.

**Incomplete work / next authorized session:**

1. Run full root and adapter/app regressions, Ruff/format and builds after all
   preview changes. Earlier full 108-root/24-app results are a baseline only.
   Verify `pointcloud.js` is included in the wheel and served with JavaScript MIME.
2. Actual browser screenshot/WebGL mouse interaction was not verified: CUA reported
   IAB unavailable and no browsers. Do not claim visual QA passed. Check responsive
   layout, RGB decoding throughput, cloud rotation/zoom/reset, navigation return,
   mode switching, session errors, stop/restart and multiple-tab cleanup.
3. Check full-resolution RealSense preview/record throughput and timing under
   operator supervision; verify CAN startup/sudo behavior on real hardware. Keep
   1-degree arrival acceptance. Simulation is insufficient for these claims.
4. Finish preview documentation in `docs/data-collection.md` and quickstart. The
   attempted preview-section patch failed to match and made no changes. CAN auto
   setup, compact UI and return-navigation documentation edits DID apply earlier.
   CHANGELOG has earlier fixes but needs the current optimization summary.
5. Consider tests for unsupported/missing depth, WebSocket capacity/disconnect,
   fresh-frame caching across restarts and viewer behavior under load. Check depth
   versus RGB resolution labels if their profiles differ. Ensure preview errors
   remain visible while raw status details are collapsed.

**Local resources:** only the agent-created simulation server at port 18081 may be
stopped during checkpoint cleanup (SIGTERM sent after checking its exact PID and
arguments). User's service at port 8000 must not be stopped
or restarted. Simulation was stopped through its own API after throughput tests;
no record/save was requested. Test runs created synthetic raw manifests under
`data/raw/app/`; do not confuse them with operator data or delete immutable raw.
