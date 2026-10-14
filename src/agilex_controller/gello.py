"""Compose the upstream GELLO API with installation-specific calibration."""

from __future__ import annotations

import contextlib
import sys
from typing import Any

import numpy as np

from .configuration import GelloConfig


def device_config(config: GelloConfig) -> Any:
    from agilex_gello_software.agents.gello_agent import DynamixelRobotConfig

    return DynamixelRobotConfig(
        joint_ids=config.joint_ids,
        joint_offsets=config.joint_offsets,
        joint_signs=config.joint_signs,
        gripper_config=config.gripper_config,
    )


def read_once(config: GelloConfig) -> np.ndarray:
    """Read physical encoders without allowing the driver's fake fallback."""
    from agilex_gello_software.dynamixel.driver import DynamixelDriver

    with contextlib.redirect_stdout(sys.stderr):
        driver = DynamixelDriver(
            (*config.joint_ids, config.gripper_config[0]),
            port=config.port,
            use_fake_fallback=False,
        )
        try:
            offsets = np.asarray((*config.joint_offsets, 0.0), dtype=np.float64)
            signs = np.asarray((*config.joint_signs, 1), dtype=np.float64)
            joints = (driver.get_joints() - offsets) * signs
            _, opened, closed = config.gripper_config
            endpoints = np.deg2rad((opened, closed))
            joints[-1] = np.clip(
                (joints[-1] - endpoints[0]) / (endpoints[1] - endpoints[0]), 0, 1
            )
            if joints.shape != (7,) or not np.all(np.isfinite(joints)):
                raise RuntimeError("GELLO must return seven finite joint values")
            return joints.copy()
        finally:
            driver.close()


class GelloLeader:
    """PiPER-X integration mapping around an unchanged GelloAgent.act API."""

    def __init__(
        self,
        config: GelloConfig,
        start_joints: np.ndarray,
        *,
        relative_alignment: bool = False,
    ) -> None:
        from agilex_gello_software.agents.gello_agent import GelloAgent

        self._agent = GelloAgent(
            port=config.port,
            dynamixel_config=device_config(config),
            start_joints=start_joints,
        )
        self._signs = np.asarray(config.follower_signs, dtype=np.float64)
        self._relative = relative_alignment
        self._leader_origin: np.ndarray | None = None
        self._follower_origin: np.ndarray | None = None

    def _read(self, observations: dict[str, Any]) -> np.ndarray:
        state = np.asarray(self._agent.act(observations), dtype=np.float64)
        if state.shape != (7,) or not np.all(np.isfinite(state)):
            raise RuntimeError("GELLO must return seven finite joint values")
        if not 0 <= state[6] <= 1:
            raise RuntimeError("GELLO gripper must be within [0, 1]")
        return state.copy()

    def align_to(self, follower: np.ndarray, observations: dict[str, Any]) -> None:
        self._leader_origin = self._read(observations)
        self._follower_origin = follower.copy()

    def act(self, observations: dict[str, Any]) -> np.ndarray:
        if self._leader_origin is None or self._follower_origin is None:
            raise RuntimeError("GELLO leader must be aligned before control starts")
        state = self._read(observations)
        if self._relative:
            arm = (
                self._follower_origin[:6]
                + (state[:6] - self._leader_origin[:6]) * self._signs
            )
        else:
            arm = state[:6] * self._signs
        # Preserve the established application's direct 0..1 gripper mapping.
        return np.concatenate((arm, state[6:7]))

    def close(self) -> None:
        self._agent.close()
