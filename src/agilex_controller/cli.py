"""Public application commands; --help never opens hardware."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument(
        "--project-root",
        type=Path,
        help="controller checkout (default: installed source checkout)",
    )
    common.add_argument(
        "--config",
        type=Path,
        help="TOML file; CLI overrides file, then built-in defaults",
    )
    parser = argparse.ArgumentParser(
        prog="agilex-controller",
        parents=[common],
        description="PiPER-X/GELLO control and raw collection",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser(
        "read", parents=[common], help="read physical GELLO once"
    )
    read.add_argument("--gello-port", default=argparse.SUPPRESS)
    read.add_argument("--json", action="store_true")
    commands.add_parser(
        "config", parents=[common], help="print effective configuration"
    )
    status = commands.add_parser("status", parents=[common], help="read SDK arm status")
    status.add_argument("--can-interface", default=argparse.SUPPRESS)
    status.add_argument("--sdk-project", default=argparse.SUPPRESS)
    for name in ("follow", "record"):
        aliases = ["follow-record"] if name == "record" else []
        command = commands.add_parser(
            name,
            aliases=aliases,
            parents=[common],
            help=f"managed following{' and raw recording' if aliases else ''}",
        )
        command.add_argument("--gello-port", default=argparse.SUPPRESS)
        command.add_argument("--host", "--hostname", default=argparse.SUPPRESS)
        command.add_argument(
            "--port", "--robot-port", type=int, default=argparse.SUPPRESS
        )
        command.add_argument("--hz", type=float, default=argparse.SUPPRESS)
        command.add_argument("--can-interface", default=argparse.SUPPRESS)
        command.add_argument("--can-bitrate", type=int, default=argparse.SUPPRESS)
        command.add_argument("--sdk-project", default=argparse.SUPPRESS)
        command.add_argument(
            "--joint-signs", nargs=6, type=int, default=argparse.SUPPRESS
        )
        for option in (
            "max-start-error-rad",
            "transition-step-rad",
            "max-command-step-rad",
            "request-timeout-s",
            "startup-timeout-s",
        ):
            command.add_argument(f"--{option}", type=float, default=argparse.SUPPRESS)
        command.add_argument(
            "--yes", action="store_true", help="confirm planned motion"
        )
        command.add_argument("--skip-can-setup", action="store_true")
        command.add_argument(
            "--existing-server",
            action="store_true",
            help="connect to a server you manage; skip local CAN/status/start/stop",
        )
        if name == "record":
            for option in (
                "raw-data-root",
                "lerobot-data-root",
                "converter-project",
                "task",
            ):
                command.add_argument(f"--{option}", default=argparse.SUPPRESS)
            command.add_argument("--dataset-fps", type=int, default=argparse.SUPPRESS)
            command.add_argument(
                "--record-queue-size", type=int, default=argparse.SUPPRESS
            )
            command.add_argument(
                "--start-recording",
                action=argparse.BooleanOptionalAction,
                default=argparse.SUPPRESS,
            )
            command.add_argument(
                "--skip-conversion",
                dest="convert",
                action="store_false",
                default=argparse.SUPPRESS,
            )
    move = commands.add_parser(
        "movejs", parents=[common], help="position via an existing JS service"
    )
    move.add_argument("--host", "--hostname", default=argparse.SUPPRESS)
    move.add_argument("--port", "--robot-port", type=int, default=argparse.SUPPRESS)
    move.add_argument("--request-timeout-s", type=float, default=argparse.SUPPRESS)
    move.add_argument("--joints", nargs=6, type=float, default=[0.0] * 6)
    move.add_argument("--gripper", type=float)
    move.add_argument("--step-rad", type=float, default=0.02)
    move.add_argument("--period", type=float, default=0.02)
    move.add_argument("--tolerance-deg", type=float, default=1.0)
    convert = commands.add_parser(
        "convert", parents=[common], help="run converter in its Python 3.12 environment"
    )
    convert.add_argument("session", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--converter-project", default=argparse.SUPPRESS)
    convert.add_argument(
        "--fps", dest="dataset_fps", type=int, default=argparse.SUPPRESS
    )
    convert.add_argument("--repo-id")
    convert.add_argument("--without-velocity", action="store_true")
    convert.add_argument("--without-ee-pose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        parser.print_help()
        return 0
    args = parser.parse_args(arguments)
    from .configuration import load_config

    try:
        config = load_config(
            getattr(args, "project_root", None),
            getattr(args, "config", None),
            vars(args),
        )
        if args.command == "config":
            print(json.dumps(asdict(config), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "read":
            from .gello import read_once
            from .workflow import application_lock

            with application_lock():
                state = read_once(config.gello)
            if args.json:
                print(
                    json.dumps(
                        {"joints_rad": state[:6].tolist(), "gripper": float(state[6])}
                    )
                )
            else:
                print(f"GELLO joints_rad={state[:6].tolist()}, gripper={state[6]:.6f}")
            return 0
        if args.command == "status":
            from .workflow import project_command

            return subprocess.run(
                [
                    *project_command(
                        config.path("sdk_project"), "agilex_sdk_python.cli"
                    ),
                    "status",
                    "--channel",
                    config.robot.can_interface,
                    "--wait",
                    "1.0",
                ],
                check=False,
                timeout=10,
            ).returncode
        if args.command == "convert":
            from .workflow import convert_session

            extra = ["--repo-id", args.repo_id] if args.repo_id else []
            for name in ("without_velocity", "without_ee_pose"):
                if getattr(args, name):
                    extra.append("--" + name.replace("_", "-"))
            return convert_session(
                config, args.session.resolve(), args.output.resolve(), extra
            )
        if args.command == "movejs":
            import numpy as np

            from .control import move_js
            from .robot_client import RobotClient
            from .workflow import application_lock

            for name in ("step_rad", "period", "tolerance_deg"):
                value = getattr(args, name)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(
                        f"--{name.replace('_', '-')} must be positive and finite"
                    )
            if args.step_rad > 0.05:
                raise ValueError("--step-rad must be at most 0.05")
            if not all(math.isfinite(x) for x in args.joints):
                raise ValueError("joint targets must be finite")
            if args.gripper is not None and (
                not math.isfinite(args.gripper) or not 0 <= args.gripper <= 1
            ):
                raise ValueError("--gripper must be within [0, 1]")
            with (
                application_lock(),
                RobotClient(
                    config.robot.host,
                    config.robot.port,
                    config.safety.request_timeout_s,
                ) as robot,
            ):
                move_js(
                    robot,
                    np.asarray(args.joints),
                    gripper=args.gripper,
                    step_rad=args.step_rad,
                    period=args.period,
                    tolerance_deg=args.tolerance_deg,
                )
            return 0
        from .workflow import run_workflow

        return run_workflow(
            config,
            record=args.command in ("record", "follow-record"),
            assume_yes=args.yes,
            existing_server=args.existing_server,
            skip_can_setup=args.skip_can_setup,
        )
    except KeyboardInterrupt:
        print("\n操作已中止。", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"agilex-controller: {exc}", file=sys.stderr)
        return 1
