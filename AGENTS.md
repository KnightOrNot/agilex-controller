# Repository Guidelines

## Project Structure & Responsibilities

- `src/agilex_controller/` owns configuration, client composition, SDK subprocess lifecycle, JS positioning, following, and raw recording.
- `config/default.toml` contains application defaults and installation-specific GELLO calibration. Pass calibration through `DynamixelRobotConfig`; do not patch the library's port map for this installation.
- `agilex-gello-software/`, `agilex-sdk-python/`, and `lerobot-converter/` are independent Git submodules. Keep hardware access in SDK and timestamp alignment/conversion in converter.
- GELLO preserves upstream `gello/`, tools, and configs; local adaptations belong in its `src/`. Its pinned DynamixelSDK submodule is a required uv source. Run its offline upstream audit after changes.
- `scripts/` contains exactly three Shell entry points: setup and two thin controller wrappers.
- `tests/` covers controller behavior; `docs/` contains architecture, installation, CLI, configuration, and troubleshooting. Preserve hardware reference assets.
- `data/raw/` is immutable input; `data/lerobot/` is regenerated output. Neither belongs in Git.

Camera integration is deferred. The SDK remains unchanged for this refactor.

## Build, Test, and Development Commands

Use Python 3.11 for controller/GELLO/SDK development and 3.12 for converter. Controller installs GELLO as a local editable dependency; SDK and converter use their own interpreters.

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
