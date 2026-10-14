"""Bounded ZMQ RPC client for the unchanged agilex-sdk-python wire protocol."""

from __future__ import annotations

import pickle
from typing import Any

import numpy as np
import zmq


class RobotClient:
    """One owner per socket; after a timeout the client must be closed."""

    def __init__(
        self, host: str = "127.0.0.1", port: int = 6001, timeout_s: float = 2.0
    ) -> None:
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.setsockopt(zmq.SNDTIMEO, max(1, int(timeout_s * 1000)))
        self._socket.setsockopt(zmq.RCVTIMEO, max(1, int(timeout_s * 1000)))
        self._socket.connect(f"tcp://{host}:{port}")
        self._failed = False
        self._closed = False

    def _request(self, method: str, **args: Any) -> Any:
        if self._failed or self._closed:
            raise RuntimeError("robot client is closed or unusable after a timeout")
        try:
            self._socket.send(pickle.dumps({"method": method, "args": args}))
            reply = pickle.loads(self._socket.recv())
        except zmq.Again as exc:
            self._failed = True
            raise RuntimeError(f"robot RPC timed out: {method}") from exc
        if isinstance(reply, dict) and "error" in reply:
            raise RuntimeError(f"PiPER-X server rejected {method}: {reply['error']}")
        return reply

    def num_dofs(self) -> int:
        return int(self._request("num_dofs"))

    def get_joint_state(self) -> np.ndarray:
        return self._vector(self._request("get_joint_state"), "joint_positions")

    def command_joint_state(self, joint_state: np.ndarray) -> None:
        command = self._vector(joint_state, "command")
        if not 0 <= command[6] <= 1:
            raise ValueError("command gripper must be within [0, 1]")
        self._request("command_joint_state", joint_state=command)

    def get_observations(self) -> dict[str, Any]:
        value = self._request("get_observations")
        if not isinstance(value, dict):
            raise RuntimeError("robot observations must be a mapping")
        for key in ("joint_positions", "joint_velocities", "ee_pos_quat"):
            value[key] = self._vector(value.get(key), key)
        gripper = np.asarray(value.get("gripper_position"), dtype=np.float64)
        if gripper.shape != () or not np.isfinite(gripper):
            raise RuntimeError("gripper_position must be a finite scalar")
        if not 0 <= float(gripper) <= 1 or not 0 <= value["joint_positions"][6] <= 1:
            raise RuntimeError("robot gripper feedback must be within [0, 1]")
        return value

    @staticmethod
    def _vector(value: Any, name: str) -> np.ndarray:
        array = np.asarray(value, dtype=np.float64)
        if array.shape != (7,) or not np.all(np.isfinite(array)):
            raise RuntimeError(f"{name} must be a finite seven-element vector")
        return array

    def close(self) -> None:
        if not self._closed:
            self._socket.close(linger=0)
            self._context.term()
            self._closed = True

    def __enter__(self) -> RobotClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
