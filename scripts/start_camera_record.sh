#!/usr/bin/env bash
set -Eeuo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$root_dir" --frozen agilex-controller \
    --project-root "$root_dir" record --camera --camera-preview "$@"
