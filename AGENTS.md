# Repository Guidelines

## Project Structure & Architecture

- `src/agilex_controller/` contains the Python 3.11 controller scaffold. Existing launch scripts still delegate following and raw recording to GELLO.
- `agilex-sdk-python/`, `agilex-gello-software/`, and `lerobot-converter/` are independent Git submodules, each with `src/`, `tests/`, and its own environment.
- `docs/` contains integration instructions, the user manual, and CAN protocol references. GELLO configurations and simulation assets belong to its submodule.
- `data/raw/` holds immutable recordings; `data/lerobot/` holds regenerated datasets. Keep both out of Git.

For the planned refactor, place client composition, lifecycle management, and recording coordination in controller. Keep GELLO input/mapping and robot hardware access in their respective libraries; timestamp alignment and conversion belong to converter. Camera integration is deferred.

## Build, Test, and Development Commands

Run from the repository root unless specified:

- `./setup.sh`: initialize submodules and install system dependencies and Python environments.
- `./setup.sh --check-only`: inspect the existing setup without installation.
- `uv build`: build the controller package.
- `uv run agilex-controller`: run the current scaffold entry point.
- `./start_gello_follow.sh --help` and `./start_data_record.sh --help`: inspect operational arguments.
- `bash -n setup.sh start_gello_follow.sh start_data_record.sh`: validate shell syntax.

Inside each changed submodule, run `uv run --group dev pytest` and `uv run --group dev ruff check .`. Also run `uv run pyright` inside `agilex-sdk-python/`.

Use Python 3.11 for controller/GELLO/SDK development and 3.12 for converter. Invoke converter through its own environment.

## Coding Style & Naming Conventions

Use four-space Python indentation, type annotations for public interfaces, `snake_case` functions/modules, and `PascalCase` classes. Follow local Ruff configuration; GELLO uses an 88-character limit. Quote shell paths and derive repository paths from script locations rather than machine-specific directories.

## Testing Guidelines

Use pytest with `test_*.py` files and `test_*` functions. Add controller tests under `tests/` as functionality develops. No repository-wide coverage threshold is configured. Mock CAN, serial, and ZMQ dependencies; test recording boundaries, interruption handling, and conversion compatibility. Hardware validation is separate: launch scripts move real machinery and require the documented setup and operator confirmation.

## Commit & Pull Request Guidelines

History mixes descriptive messages with `chore:` and `refactor:` prefixes; prefer concise, imperative, scoped descriptions. Commit and publish submodule changes before updating parent gitlinks. PRs should explain behavior changes, affected repositories, validation results, hardware-testing status, and relevant issues. Update usage documentation when commands or architecture change.
