"""Independent collection entry point; legacy controller remains unchanged."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LeRobot / LeLab AgileX collection")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "setup", help="install the separate Python 3.12 app environment"
    )
    setup.add_argument("--python", default="3.12.14", help="runtime interpreter")
    serve = commands.add_parser("serve", help="start the collection web app")
    serve.add_argument("--simulate", action="store_true", help="never open hardware")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    adapters = project / "agilex-adapters"
    if not (adapters / "pyproject.toml").is_file():
        parser.error("--project must point to the controller checkout with submodules")
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv is required")
    if args.command == "setup":
        return subprocess.call(
            [
                uv,
                "sync",
                "--frozen",
                "--project",
                str(adapters),
                "--python",
                args.python,
                "--extra",
                "app",
            ]
        )
    python = adapters / ".venv/bin/python"
    if not python.is_file():
        parser.error("run agilex-data-collection setup first")
    command = [
        str(python),
        "-m",
        "agilex_data_collection.runtime",
        "--project",
        str(project),
        "--port",
        str(args.port),
    ]
    if args.simulate:
        command.append("--simulate")
    if args.config:
        command.extend(["--config", str(args.config.resolve())])
    # Only this subprocess sees the new source package in its 3.12 environment.
    env = {**os.environ, "PYTHONPATH": str(project / "src")}
    os.execve(python, command, env)
    return 0
