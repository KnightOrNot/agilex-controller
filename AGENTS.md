# Repository Guidelines

## Project Structure & Responsibilities

- `src/agilex_controller/` owns configuration, client composition, SDK subprocess lifecycle, JS positioning, following, and raw RGB-D recording.
- `config/default.toml` contains application defaults and installation-specific GELLO calibration. Pass calibration through `DynamixelRobotConfig`; do not patch the library's port map for this installation.
- `agilex-gello-software/`, `agilex-sdk-python/`, `lerobot-converter/`, and `camera-realsense/` are independent Git submodules. Keep robot hardware access in SDK, camera acquisition in its library, and timestamp matching/conversion in converter.
- GELLO preserves upstream `gello/`, tools, and configs; local adaptations belong in its `src/`. Its pinned DynamixelSDK submodule is a required uv source. Run its offline upstream audit after changes.
- `scripts/` contains five Shell entry points: setup and four thin controller wrappers for legacy/camera following and recording. New camera wrappers enable capture and preview; keep the legacy defaults camera-free.
- `tests/` covers controller behavior; `docs/` contains architecture, installation, CLI, configuration, and troubleshooting. Preserve hardware reference assets.
- `data/raw/` is immutable input; `data/lerobot/` is regenerated output. Neither belongs in Git.

Camera owns reusable acquisition and SDK-to-host clock mapping; controller owns lifecycle and raw persistence; converter owns timestamp matching and LeRobot output. Preserve native Z16 depth and calibration. The robot SDK remains unchanged.

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

The user requires an immediate checkpoint here and no further implementation once
their five-hour AI allowance reaches 10%. This quota is not exposed to the agent;
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

Verified: 89 controller tests, 12 adapter/application tests (including real RGB-D
save/discard/readback and write-failure cleanup), Ruff, both builds, actual CLI
setup/start and HTTP smoke checks. Heavy dataset imports run before hardware
startup to avoid first-record GIL stalls. Browser routing carries LeLab's supported
`?api=` override so localhost/127.0.0.1 and custom ports work without CORS patches.

Pending: operator-supervised physical GELLO/PiPER-X/RealSense validation, sustained
full-resolution throughput and timestamp-quality measurement. No physical motion
was performed. Changes remain uncommitted in both `dev` checkouts; do not publish
or update the parent gitlink to unpublished child work without authorization.
