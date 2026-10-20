"""Startup and cleanup diagnostics shared by the 3.11 and 3.12 processes."""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

ERROR_PREFIX = "AGILEX_WORKER_ERROR: "


def report_worker_error(error: Exception, cleanup_error: Exception | None) -> None:
    """Keep the primary traceback and report cleanup failure separately."""
    traceback.print_exception(error, file=sys.stderr)
    if cleanup_error is not None and cleanup_error is not error:
        print("Additional hardware cleanup failure:", file=sys.stderr)
        traceback.print_exception(cleanup_error, file=sys.stderr)
    print(
        ERROR_PREFIX
        + json.dumps(
            {
                "error": f"{type(error).__name__}: {error}",
                "cleanup_error": str(cleanup_error)
                if cleanup_error is not None and cleanup_error is not error
                else None,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
        flush=True,
    )


def worker_failure(log: Path, returncode: int) -> RuntimeError:
    """Prefer structured errors or tracebacks over buffered cleanup messages."""
    lines: list[str] = []
    try:
        with log.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 16384))
            lines = stream.read().decode("utf-8", errors="replace").strip().splitlines()
    except OSError:
        pass
    detail = lines[-1] if lines else "inspect session log"
    for line in reversed(lines):
        if not line.startswith(ERROR_PREFIX):
            continue
        try:
            payload = json.loads(line.removeprefix(ERROR_PREFIX))
            detail = payload["error"]
            if payload.get("cleanup_error"):
                detail += f"; cleanup: {payload['cleanup_error']}"
            break
        except (ValueError, KeyError, TypeError):
            continue
    else:
        # Compatibility with existing worker logs and failures before main().
        exceptions = [line for line in lines if re.match(r"^[A-Za-z_][\w.]*: ", line)]
        if exceptions:
            detail = exceptions[0]
            if exceptions[-1] != detail:
                detail += f"; also: {exceptions[-1]}"
    return RuntimeError(f"hardware worker failed ({returncode}): {detail}; see {log}")
