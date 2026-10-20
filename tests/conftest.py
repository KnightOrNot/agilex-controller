from __future__ import annotations

import pickle
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import zmq

from agilex_controller.configuration import ControllerConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_workflow_lock(tmp_path, monkeypatch):
    """Exercise real flock semantics without contending with an operator session."""
    from agilex_controller import workflow

    def isolated_path(*args, **kwargs):
        path = Path(*args, **kwargs)
        if path == Path("/tmp/start_gello_follow.lock"):
            return tmp_path / "workflow.lock"
        return path

    monkeypatch.setattr(workflow, "Path", isolated_path)


@pytest.fixture
def config(tmp_path):
    value = ControllerConfig(root=ROOT)
    return replace(
        value,
        robot=replace(value.robot, hz=1000.0),
        recording=replace(value.recording, convert=False),
        safety=replace(value.safety, request_timeout_s=0.1, startup_timeout_s=0.3),
        paths=replace(value.paths, raw_data_root=str(tmp_path / "raw")),
    )


@pytest.fixture
def robot_server():
    """Actual SDK wire protocol over local ZMQ, with no CAN/device access."""
    context = zmq.Context()
    ready = threading.Event()
    stop = threading.Event()
    state = {"commands": [], "requests": [], "position": np.zeros(7), "error": None}

    def serve():
        with context.socket(zmq.REP) as socket:
            socket.setsockopt(zmq.LINGER, 0)
            state["port"] = socket.bind_to_random_port("tcp://127.0.0.1")
            ready.set()
            while not stop.is_set():
                if not socket.poll(20):
                    continue
                request = pickle.loads(socket.recv())
                method = request["method"]
                state["requests"].append(method)
                if state["error"]:
                    result = {"error": state["error"]}
                elif method == "num_dofs":
                    result = 7
                elif method == "command_joint_state":
                    command = request["args"]["joint_state"]
                    state["commands"].append(command.copy())
                    state["position"] = command.copy()
                    result = None
                elif method == "get_joint_state":
                    result = state["position"].copy()
                elif method == "get_observations":
                    result = {
                        "joint_positions": state["position"].copy(),
                        "joint_velocities": np.zeros(7),
                        "ee_pos_quat": np.array([0, 0, 0.2, 0, 0, 0, 1]),
                        "gripper_position": np.array(state["position"][6]),
                    }
                else:
                    result = {"error": "unknown method"}
                socket.send(pickle.dumps(result))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(2)
    try:
        yield state
    finally:
        stop.set()
        thread.join(timeout=2)
        context.term()
        assert not thread.is_alive()
