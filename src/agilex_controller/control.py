"""Following and recording loops, independent of hardware construction."""

from __future__ import annotations

import os
import select
import sys
import termios
import time
import tty
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any

import numpy as np

from .configuration import ControllerConfig
from .gello import GelloLeader
from .recording import RawEpisodeRecorder, RecordingError
from .robot_client import RobotClient


class RobotEnv:
    """Monotonic-rate command/feedback cycle; hardware ownership stays in SDK."""

    def __init__(self, robot: RobotClient, control_rate_hz: float) -> None:
        self.robot = robot
        self._period = 1 / control_rate_hz
        self._last = time.monotonic()

    def get_obs(self) -> dict[str, Any]:
        return self.robot.get_observations()

    def step(self, command: np.ndarray) -> dict[str, Any]:
        self.robot.command_joint_state(command)
        remaining = self._last + self._period - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.monotonic()
        return self.get_obs()


def align_to_leader(
    env: RobotEnv,
    leader: GelloLeader,
    config: ControllerConfig,
    *,
    check_health: Callable[[], None] | None = None,
) -> dict[str, Any]:
    observations = env.get_obs()
    current = observations["joint_positions"]
    leader.align_to(current, observations)
    target = leader.act(observations)
    errors = np.abs(target[:6] - current[:6])
    worst = int(np.argmax(errors))
    if errors[worst] > config.safety.max_start_error_rad:
        raise RuntimeError(
            f"startup refused: J{worst + 1} differs by {errors[worst]:.3f} rad "
            f"(limit {config.safety.max_start_error_rad:.3f})"
        )
    steps = max(
        1, int(np.ceil(float(np.max(errors)) / config.safety.transition_step_rad))
    )
    for arm in np.linspace(current[:6], target[:6], steps + 1)[1:]:
        if check_health is not None:
            check_health()
        observations = env.step(np.concatenate((arm, target[6:7])))
    return observations


def limit_arm_command(
    command: np.ndarray, current: np.ndarray, max_step_rad: float
) -> np.ndarray:
    result = command.copy()
    delta = command[:6] - current[:6]
    largest = float(np.max(np.abs(delta)))
    if largest > max_step_rad:
        result[:6] = current[:6] + delta * (max_step_rad / largest)
    return result


def _sample_from_cycle(
    *,
    command: np.ndarray,
    observations: dict[str, Any],
    command_time_ns: int,
    observation_time_ns: int,
    wall_time_ns: int,
    control_period_ns: int,
) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "command_time_ns": command_time_ns,
        "observation_time_ns": observation_time_ns,
        "wall_time_ns": wall_time_ns,
        "control_period_ns": control_period_ns,
    }
    for key, value in (
        ("action", command),
        *(
            (key, observations[key])
            for key in ("joint_positions", "joint_velocities", "ee_pos_quat")
        ),
    ):
        array = np.asarray(value, dtype=np.float64)
        if array.shape != (7,) or not np.all(np.isfinite(array)):
            raise RecordingError(f"{key} must be a finite seven-element vector")
        sample[key] = array.tolist()
    gripper = float(observations["gripper_position"])
    if not np.isfinite(gripper):
        raise RecordingError("gripper_position must be finite")
    sample["gripper_position"] = gripper
    return sample


class RecordingKeyboard:
    """Nonblocking single-key input; preserve normal Ctrl+C signal handling."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._original: Any = None

    def __enter__(self) -> RecordingKeyboard:
        if sys.stdin.isatty():
            self._fd = sys.stdin.fileno()
            self._original = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        else:
            print("标准输入不是终端；R/S/D 按键不可用。", file=sys.stderr)
        return self

    def __exit__(self, *_args: object) -> None:
        if self._fd is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original)

    def poll(self) -> str | None:
        if self._fd is None:
            return None
        readable, _, _ = select.select([self._fd], [], [], 0)
        return (
            os.read(self._fd, 1).decode(errors="ignore").lower() if readable else None
        )


def handle_recording_key(key: str | None, recorder: RawEpisodeRecorder) -> None:
    if key == "r" and not recorder.is_recording:
        print(f"[记录] 开始：{recorder.start_episode()}")
    elif key == "s" and recorder.is_recording:
        print(f"[记录] 已保存：{recorder.save_episode()}")
    elif key == "d" and recorder.is_recording:
        recorder.discard_episode()
        print("[记录] 已丢弃当前 episode")
    elif key == "p":
        print(
            f"[记录] active={recorder.is_recording}, episode={recorder.episode_index}"
        )
    elif key == "h":
        print("R=开始 S=保存 D=丢弃 P=状态 H=帮助 Ctrl+C=退出并回零")


def run_loop(
    robot: RobotClient,
    leader: GelloLeader,
    config: ControllerConfig,
    recorder: RawEpisodeRecorder | None = None,
    *,
    defer_interrupts: Callable[[], AbstractContextManager[None]] = nullcontext,
    camera: Any = None,
) -> None:
    env = RobotEnv(robot, config.robot.hz)
    if camera is not None:
        camera.check_health()
    observations = align_to_leader(
        env,
        leader,
        config,
        **({"check_health": camera.check_health} if camera is not None else {}),
    )
    if recorder is not None and config.recording.start_recording:
        with defer_interrupts():
            recorder.start_episode()
    print("GELLO 跟随已启动；Ctrl+C 停止并安全回零。")
    previous: int | None = None
    with RecordingKeyboard() if recorder is not None else nullcontext() as keyboard:
        while True:
            if camera is not None:
                camera.check_health()
            if recorder is not None:
                key = keyboard.poll()
                # Do not interrupt Thread.start between allocation and launch.
                if key == "r":
                    with defer_interrupts():
                        handle_recording_key(key, recorder)
                else:
                    handle_recording_key(key, recorder)
            command = limit_arm_command(
                leader.act(observations),
                observations["joint_positions"],
                config.safety.max_command_step_rad,
            )
            command_time_ns = time.monotonic_ns()
            wall_time_ns = time.time_ns()
            observations = env.step(command)
            observation_time_ns = time.monotonic_ns()
            if recorder is not None and recorder.is_recording:
                recorder.add_sample(
                    _sample_from_cycle(
                        command=command,
                        observations=observations,
                        command_time_ns=command_time_ns,
                        observation_time_ns=observation_time_ns,
                        wall_time_ns=wall_time_ns,
                        control_period_ns=0
                        if previous is None
                        else command_time_ns - previous,
                    )
                )
            previous = command_time_ns


def move_js(
    robot: RobotClient,
    target: np.ndarray,
    *,
    gripper: float | None = None,
    step_rad: float = 0.02,
    period: float = 0.02,
    tolerance_deg: float = 1.0,
    check_health: Callable[[], None] | None = None,
) -> None:
    """Small-step JS positioning and feedback verification, without mode resets."""
    if check_health is not None:
        check_health()
    current = robot.get_joint_state()
    gripper = float(current[6]) if gripper is None else gripper
    if target.shape != (6,) or not np.all(np.isfinite(target)):
        raise ValueError("target must contain six finite radians")
    if not np.isfinite(gripper) or not 0 <= gripper <= 1:
        raise ValueError("gripper must be within [0, 1]")
    delta = target - current[:6]
    steps = max(1, int(np.ceil(float(np.max(np.abs(delta))) / step_rad)))
    for fraction in np.linspace(0, 1, steps + 1)[1:]:
        if check_health is not None:
            check_health()
        command = np.concatenate((current[:6] + delta * fraction, [gripper]))
        robot.command_joint_state(command)
        time.sleep(period)
    final_command = np.concatenate((target, [gripper]))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if check_health is not None:
            check_health()
        robot.command_joint_state(final_command)
        time.sleep(period)
        final = robot.get_joint_state()
        errors = np.abs(np.rad2deg(final[:6] - target))
        if float(np.max(errors)) <= tolerance_deg:
            print("PiPER-X JS target reached")
            return
    worst = int(np.argmax(errors))
    raise RuntimeError(
        f"JS positioning failed: J{worst + 1} error={errors[worst]:.3f} deg"
    )
