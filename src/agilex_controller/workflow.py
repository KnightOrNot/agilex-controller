"""Application lifecycle: preflight, SDK subprocess, clients, recording, cleanup."""

from __future__ import annotations

import fcntl
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .configuration import ControllerConfig
from .control import move_js, run_loop
from .gello import GelloLeader, read_once
from .recording import RawEpisodeRecorder
from .robot_client import RobotClient


def project_command(project: Path, module: str) -> list[str]:
    """Explicit interpreter avoids activation and relocated console shebangs."""
    python = project / ".venv/bin/python"
    if not python.is_file():
        raise FileNotFoundError(f"missing {python}; run scripts/setup.sh first")
    return [str(python), "-c", f"from {module} import main; raise SystemExit(main())"]


@contextmanager
def application_lock() -> Iterator[None]:
    # Share the legacy launcher's lock so old/new entry points cannot overlap.
    with Path("/tmp/start_gello_follow.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another PiPER-X/GELLO workflow is running") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Interrupts:
    """Keep newly constructed resources reachable before delivering a stop."""

    def __init__(self) -> None:
        self._depth = 0
        self._pending = False

    def stop(self, _signum: int, _frame: object) -> None:
        if self._depth:
            self._pending = True
        else:
            raise KeyboardInterrupt

    @contextmanager
    def defer(self) -> Iterator[None]:
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if not self._depth and self._pending:
                self._pending = False
                raise KeyboardInterrupt


@contextmanager
def workflow_signals() -> Iterator[Interrupts]:
    """SIGINT and SIGTERM take the same controlled exit path."""
    previous = {}
    interrupts = Interrupts()
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, interrupts.stop)
    try:
        yield interrupts
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def cleanup_signals() -> Iterator[None]:
    previous = {
        number: signal.signal(number, signal.SIG_IGN)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


class SDKServer:
    def __init__(self, config: ControllerConfig) -> None:
        self._log = tempfile.TemporaryFile(mode="w+t")
        robot = config.robot
        command = project_command(
            config.path("sdk_project"), "agilex_sdk_python.gello_server"
        )
        try:
            self.process = subprocess.Popen(
                [
                    *command,
                    "--channel",
                    robot.can_interface,
                    "--host",
                    robot.host,
                    "--port",
                    str(robot.port),
                    "--hz",
                    str(robot.hz),
                ],
                stdout=self._log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except BaseException:
            self._log.close()
            raise

    def check_alive(self) -> None:
        if self.process.poll() is not None:
            self._log.seek(0)
            raise RuntimeError(f"SDK server exited:\n{self._log.read()}")

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                    raise RuntimeError(
                        "SDK server did not stop after SIGTERM"
                    ) from None
        finally:
            self._log.close()


def wait_for_server(config: ControllerConfig, server: SDKServer | None) -> None:
    deadline = time.monotonic() + config.safety.startup_timeout_s
    while time.monotonic() < deadline:
        if server is not None:
            server.check_alive()
        timeout = min(config.safety.request_timeout_s, deadline - time.monotonic())
        with RobotClient(
            config.robot.host, config.robot.port, max(0.001, timeout)
        ) as client:
            try:
                dofs = client.num_dofs()
            except RuntimeError as exc:
                if "timed out" not in str(exc):
                    raise
            else:
                if dofs != 7:
                    raise RuntimeError("PiPER-X must expose six joints and one gripper")
                return
        time.sleep(0.05)
    if server is not None:
        server.check_alive()
    raise RuntimeError("SDK server did not become ready before startup timeout")


def check_feedback(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise RuntimeError("SDK status must be a JSON object")
    joints = state.get("joint_angles_rad")
    fps = state.get("receive_fps")
    if (
        not isinstance(joints, list)
        or len(joints) != 6
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in joints)
        or type(fps) not in (int, float)
        or not math.isfinite(fps)
        or fps <= 0
        or state.get("arm_status") is None
    ):
        raise RuntimeError(
            "PiPER-X has incomplete feedback; check CAN/power/emergency stop"
        )


def preflight(
    config: ControllerConfig, *, existing_server: bool, skip_can_setup: bool
) -> np.ndarray:
    port = Path(config.gello.port)
    if not port.exists() or not os.access(port, os.R_OK | os.W_OK):
        raise RuntimeError(f"GELLO serial port is missing or inaccessible: {port}")
    if not existing_server:
        sdk = config.path("sdk_project")
        command = project_command(sdk, "agilex_sdk_python.cli")
        # Refuse to accidentally attach to an unrelated already-running server.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((config.robot.host, config.robot.port))
            except OSError as exc:
                raise RuntimeError(
                    "cannot bind SDK endpoint; check --host/--port or explicitly "
                    "use --existing-server"
                ) from exc
        if not skip_can_setup:
            subprocess.run(
                [
                    str(sdk / "scripts/config_can.sh"),
                    config.robot.can_interface,
                    str(config.robot.can_bitrate),
                ],
                check=True,
            )
        status = subprocess.run(
            [
                *command,
                "status",
                "--channel",
                config.robot.can_interface,
                "--wait",
                "1.0",
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        )
        if status.stderr:
            print(status.stderr, file=sys.stderr, end="")
        state = json.loads(status.stdout)
        check_feedback(state)
        print(status.stdout, end="")
    return read_once(config.gello)


def convert_session(
    config: ControllerConfig,
    session: Path,
    output: Path,
    extra: list[str] | None = None,
) -> int:
    command = project_command(config.path("converter_project"), "lerobot_converter")
    return subprocess.run(
        [
            *command,
            str(session),
            str(output),
            "--fps",
            str(config.recording.dataset_fps),
            *(extra or []),
        ],
        check=False,
    ).returncode


def _shutdown(
    config: ControllerConfig,
    robot: RobotClient | None,
    leader: GelloLeader | None,
    server: SDKServer | None,
    ready: bool,
    recorder: RawEpisodeRecorder | None,
    camera: Any = None,
) -> list[str]:
    errors: list[str] = []

    def attempt(name: str, action: Any) -> None:
        try:
            action()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"[退出] {name}: {exc}", file=sys.stderr)

    # Close a possibly interrupted REQ exchange, then use a fresh socket for zeroing.
    if robot is not None:
        attempt("关闭跟随客户端", robot.close)
    if leader is not None:
        attempt("关闭 GELLO 串口", leader.close)
    if ready:

        def zero() -> None:
            print("[安全退出] 通过现有 JS 服务分步回零……")
            with RobotClient(
                config.robot.host, config.robot.port, config.safety.request_timeout_s
            ) as client:
                move_js(
                    client,
                    np.zeros(6),
                    step_rad=config.safety.transition_step_rad,
                    period=1 / config.robot.hz,
                )

        attempt("安全回零", zero)
    if server is not None:
        attempt("关闭 SDK 服务", server.close)
    if camera is not None:
        attempt("关闭相机并刷新图像", camera.close)
    # Hardware cleanup precedes potentially slow disk flushing and conversion.
    if recorder is not None:

        def flush() -> None:
            partial = recorder.close_interrupted()
            if partial is not None:
                print(f"[记录] 未完成 episode 已保留：{partial}")

        attempt("刷新原始记录", flush)
    return errors


def run_workflow(
    config: ControllerConfig,
    *,
    record: bool = False,
    assume_yes: bool = False,
    existing_server: bool = False,
    skip_can_setup: bool = False,
) -> int:
    if record and config.recording.convert:
        project_command(config.path("converter_project"), "lerobot_converter")
    session: Path | None = None
    with application_lock(), workflow_signals() as interrupts:
        initial = preflight(
            config, existing_server=existing_server, skip_can_setup=skip_can_setup
        )
        target = initial[:6] * np.asarray(config.gello.follower_signs)
        print(f"GELLO joints (rad): {initial[:6].tolist()}")
        print(f"PiPER-X target (rad): {target.tolist()}, gripper={initial[6]:.6f}")
        if not assume_yes:
            print("下一步将通过 JS 回零，再对齐到上述目标；请确认运动范围安全。")
            try:
                answer = input("输入 yes 继续：").strip()
            except EOFError as exc:
                raise RuntimeError(
                    "motion confirmation needs terminal input; "
                    "use --yes only after confirming the workspace is safe"
                ) from exc
            if answer != "yes":
                print("已取消。")
                return 0
        server: SDKServer | None = None
        robot: RobotClient | None = None
        leader: GelloLeader | None = None
        recorder: RawEpisodeRecorder | None = None
        camera: Any = None
        ready = False
        failure: Exception | None = None
        try:
            if config.camera.enabled:
                from .camera import CameraSession

                print("相机初始化与预热中；就绪后再执行 JS 回零。")
                with interrupts.defer():
                    camera = CameraSession(config.camera)
                print("相机已就绪。")
            if not existing_server:
                with interrupts.defer():
                    server = SDKServer(config)
            wait_for_server(config, server)
            ready = True
            with interrupts.defer():
                robot = RobotClient(
                    config.robot.host,
                    config.robot.port,
                    config.safety.request_timeout_s,
                )
            move_js(
                robot,
                np.zeros(6),
                step_rad=config.safety.transition_step_rad,
                period=1 / config.robot.hz,
                **({"check_health": camera.check_health} if camera is not None else {}),
            )
            move_js(
                robot,
                target,
                gripper=float(initial[6]),
                step_rad=config.safety.transition_step_rad,
                period=1 / config.robot.hz,
                **({"check_health": camera.check_health} if camera is not None else {}),
            )
            with interrupts.defer():
                leader = GelloLeader(config.gello, np.concatenate((initial[:6], [0.0])))
            if record:
                with interrupts.defer():
                    recorder = RawEpisodeRecorder(
                        config.path("raw_data_root"),
                        control_hz=config.robot.hz,
                        joint_signs=list(config.gello.follower_signs),
                        task=config.recording.task,
                        queue_size=config.recording.queue_size,
                        **({"cameras": camera} if camera is not None else {}),
                    )
                session = recorder.session_dir
                print(f"原始数据 session: {session}")
                print("R=开始 S=保存 D=丢弃 P=状态 H=帮助")
            run_loop(
                robot,
                leader,
                config,
                recorder,
                defer_interrupts=interrupts.defer,
                **({"camera": camera} if camera is not None else {}),
            )
        except KeyboardInterrupt:
            print("\n跟随已停止。")
        except Exception as exc:
            failure = exc
        finally:
            with cleanup_signals():
                cleanup_errors = _shutdown(
                    config,
                    robot,
                    leader,
                    server,
                    ready,
                    recorder,
                    **({"camera": camera} if camera is not None else {}),
                )
        if failure is not None:
            raise failure
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))
    if session is not None and config.recording.convert:
        if any((session / "episodes").glob("episode_*.jsonl")):
            output = config.path("lerobot_data_root") / session.name
            print(f"[离线转换] {session} → {output}")
            return convert_session(config, session, output)
        print("[离线转换] 没有已保存 episode，跳过转换。")
    return 0
