"""Independent collection entry point; legacy controller remains unchanged."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def configure_can(project: Path, app_path: Path) -> None:
    """Prepare CAN in the terminal, before starting the web server."""
    from agilex_controller.configuration import load_config
    from agilex_controller.workflow import application_lock

    from .config import AppConfig

    app = AppConfig.load(app_path)
    config = load_config(project, project / app.hardware_config)
    script = config.path("sdk_project") / "scripts/config_can.sh"
    if not script.is_file():
        raise FileNotFoundError(f"CAN configuration script not found: {script}")
    # Refuse to reconfigure a bus owned by a live old/new collection session.
    with application_lock():
        print(
            f"配置 CAN：{config.robot.can_interface} / "
            f"{config.robot.can_bitrate} bit/s",
            flush=True,
        )
        subprocess.run(
            [str(script), config.robot.can_interface, str(config.robot.can_bitrate)],
            cwd=project,
            check=True,
        )


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
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in [1, 65535]")
    if not args.simulate:
        try:
            configure_can(
                project,
                (args.config or project / "config/data_collection.toml").resolve(),
            )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            parser.error(f"CAN 配置失败：{exc}")
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
