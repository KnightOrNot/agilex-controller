"""Python 3.11 hardware boundary. Importing this module never opens devices.

Reuse existing, tested low-level composition helpers without changing the legacy
workflow. This worker exposes only owner-private IPC, never a TCP pickle service.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import zmq

from .config import AppConfig


class Capture:
    def __init__(self, config: Any, depth: bool, mode: str = "auto") -> None:
        from camera_realsense.stream import ColorStream

        self._source = ColorStream(
            serial=config.serial,
            width=config.width,
            height=config.height,
            fps=config.fps,
            warmup_frames=config.warmup_frames,
            depth_enabled=depth,
            depth_width=config.depth_width,
            depth_height=config.depth_height,
            depth_fps=config.depth_fps,
            mode=mode,
        )
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frames: dict[str, Any] = {}
        self._error: Exception | None = None
        self._depth = depth
        self._thread: threading.Thread | None = None
        try:
            self._source.start()
            self._thread = threading.Thread(target=self._read, daemon=True)
            self._thread.start()
            deadline = time.monotonic() + config.startup_timeout_s
            while time.monotonic() < deadline:
                with self._lock:
                    ready = "color" in self._frames and (
                        not depth or "depth" in self._frames
                    )
                if self._error:
                    raise self._error
                if ready:
                    return
                time.sleep(0.02)
            raise TimeoutError("RGB-D camera startup timed out")
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        try:
            while not self._stop.is_set():
                frame = self._source.read(timeout_s=0.2)
                if frame is not None:
                    with self._lock:
                        self._frames[frame.stream] = frame
        except Exception as exc:
            self._error = exc

    def snapshot(self) -> dict:
        if self._error:
            raise RuntimeError(f"camera failed: {self._error}") from self._error
        with self._lock:
            frames = dict(self._frames)
        result = {}
        for name, frame in frames.items():
            result[name] = dict(vars(frame))
        return result

    @property
    def metadata(self) -> dict:
        return dict(self._source.metadata)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._source.close()


class Hardware:
    def __init__(self, project: Path, app: AppConfig) -> None:
        self._stack = contextlib.ExitStack()
        self.robot = None
        self.leader = None
        self.camera = None
        self.server = None
        self.ready = False
        self.app = app
        from agilex_controller.configuration import load_config

        config = load_config(project, project / app.hardware_config)
        self.config = replace(config, robot=replace(config.robot, hz=app.control_hz))

    def start(self) -> None:
        from agilex_controller.control import move_js
        from agilex_controller.gello import GelloLeader
        from agilex_controller.robot_client import RobotClient
        from agilex_controller.workflow import (
            SDKServer,
            application_lock,
            preflight,
            wait_for_server,
        )

        self._stack.enter_context(application_lock())
        config = self.config
        # CAN configuration must already have been completed by installation.
        initial = preflight(config, existing_server=False, skip_can_setup=True)
        if self.app.camera_enabled:
            self.camera = Capture(
                config.camera, self.app.depth_enabled, self.app.camera_mode
            )
        self.server = SDKServer(config)
        wait_for_server(config, self.server)
        self.ready = True
        self.robot = RobotClient(
            config.robot.host, config.robot.port, config.safety.request_timeout_s
        )
        for target in (np.zeros(6), initial[:6] * config.gello.follower_signs):
            move_js(
                self.robot,
                target,
                gripper=float(initial[6]),
                step_rad=config.safety.transition_step_rad,
                period=1 / self.app.control_hz,
            )
        self.leader = GelloLeader(config.gello, np.concatenate((initial[:6], [0.0])))
        observations = self.robot.get_observations()
        self.leader.align_to(observations["joint_positions"], observations)
        self._previous = observations["joint_positions"].copy()

    def call(self, method: str, args: dict) -> Any:
        if method == "status":
            return {
                "ready": True,
                "camera": self.camera.metadata if self.camera else None,
                "simulated": False,
            }
        if method == "observation":
            start = time.monotonic_ns()
            positions = self.robot.get_joint_state()
            return {
                "positions": positions,
                "timestamp_ns": (start + time.monotonic_ns()) // 2,
                "request_started_ns": start,
                "request_finished_ns": time.monotonic_ns(),
            }
        if method == "action":
            positions = self.leader.act({})
            return {"positions": positions, "timestamp_ns": time.monotonic_ns()}
        if method == "command":
            positions = np.asarray(args["positions"], dtype=np.float64)
            if positions.shape != (7,) or not np.all(np.isfinite(positions)):
                raise ValueError("command must contain seven finite values")
            if not 0 <= positions[-1] <= 1:
                raise ValueError("gripper outside [0, 1]")
            delta = np.max(np.abs(positions[:6] - self._previous[:6]))
            if delta > self.config.safety.max_command_step_rad:
                raise RuntimeError("command exceeds configured joint step limit")
            self.robot.command_joint_state(positions)
            self._previous = positions.copy()
            return positions
        if method == "frames":
            return self.camera.snapshot() if self.camera else {}
        raise ValueError(f"unknown bridge method: {method}")

    def close(self) -> None:
        from agilex_controller.workflow import _shutdown

        errors = _shutdown(
            self.config,
            self.robot,
            self.leader,
            self.server,
            self.ready,
            None,
            camera=self.camera,
        )
        self._stack.close()
        if errors:
            raise RuntimeError("; ".join(errors))


class Simulation:
    """Deterministic synthetic devices; no physical device imports or access."""

    def __init__(self, app: AppConfig) -> None:
        self.app = app
        self.positions = np.zeros(7)
        self.started = time.monotonic()

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def call(self, method: str, args: dict) -> Any:
        now = time.monotonic_ns()
        if method == "status":
            return {
                "ready": True,
                "simulated": True,
                "camera": {
                    "width": 64,
                    "height": 48,
                    "depth": {"width": 64, "height": 48, "depth_units_m": 0.001},
                }
                if self.app.camera_enabled
                else None,
            }
        if method == "action":
            positions = np.zeros(7)
            positions[:6] = np.sin(time.monotonic() - self.started) * 0.1
            positions[-1] = 0.5
            return {"positions": positions, "timestamp_ns": now}
        if method == "command":
            self.positions = np.asarray(args["positions"])
            return self.positions
        if method == "observation":
            return {
                "positions": self.positions,
                "timestamp_ns": now,
                "request_started_ns": now,
                "request_finished_ns": now,
            }
        if method == "frames":
            if not self.app.camera_enabled:
                return {}
            number = int((time.monotonic() - self.started) * 30)
            result = {}
            images = {"color": np.full((48, 64, 3), number % 256, np.uint8)}
            if self.app.depth_enabled:
                images["depth"] = np.full((48, 64), 1000, np.uint16)
            for name, image in images.items():
                result[name] = {
                    "image": image,
                    "timestamp_ns": now,
                    "received_time_ns": now,
                    "frame_number": number,
                    "clock_uncertainty_ns": 0,
                    "clock_offset_ns": 0,
                    "sdk_timestamp_ms": now / 1e6,
                    "sdk_timestamp_domain": "simulation",
                    "stream": name,
                }
            return result
        raise ValueError(method)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--motion-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.endpoint.startswith("ipc://"):
        parser.error("only owner-private ipc:// endpoints are supported")
    if not args.simulate and not args.motion_confirmed:
        parser.error("physical initialization requires explicit motion confirmation")
    app = AppConfig.load(args.config)
    hardware = Simulation(app) if args.simulate else Hardware(args.project, app)
    stop = threading.Event()

    def interrupt(_number: int, _frame: Any) -> None:
        stop.set()
        raise KeyboardInterrupt

    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, interrupt)
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.setsockopt(zmq.LINGER, 0)
    try:
        hardware.start()
        socket.bind(args.endpoint)
        os.chmod(args.endpoint.removeprefix("ipc://"), 0o600)
        last_command = time.monotonic()
        while not stop.is_set():
            if time.monotonic() - last_command > app.watchdog_s:
                raise TimeoutError("control heartbeat expired; stopping hardware")
            if not socket.poll(20):
                continue
            request = socket.recv_pyobj()
            try:
                result = hardware.call(request["method"], request["args"])
                if request["method"] == "command":
                    last_command = time.monotonic()
                socket.send_pyobj({"ok": True, "result": result})
            except Exception as exc:
                socket.send_pyobj({"ok": False, "error": str(exc)})
                raise
    except KeyboardInterrupt:
        pass
    finally:
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, signal.SIG_IGN)
        try:
            hardware.close()
        finally:
            socket.close()
            context.term()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
