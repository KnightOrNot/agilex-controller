import socket
import time

import numpy as np
import pytest

from agilex_controller.robot_client import RobotClient


def test_client_uses_sdk_protocol_and_reports_real_feedback(robot_server):
    with RobotClient(port=robot_server["port"], timeout_s=0.5) as client:
        assert client.num_dofs() == 7
        command = np.array([0.1] * 6 + [0.7])
        client.command_joint_state(command)
        np.testing.assert_allclose(client.get_joint_state(), command)
        np.testing.assert_allclose(
            client.get_observations()["joint_positions"], command
        )
    client.close()


def test_server_error_propagates(robot_server):
    robot_server["error"] = "feedback is stale"
    with RobotClient(port=robot_server["port"], timeout_s=0.5) as client:
        with pytest.raises(RuntimeError, match="feedback is stale"):
            client.command_joint_state(np.zeros(7))
    assert not robot_server["commands"]


def test_timeout_is_bounded_and_socket_is_not_reused():
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        started = time.monotonic()
        with RobotClient(port=port, timeout_s=0.03) as client:
            with pytest.raises(RuntimeError, match="timed out"):
                client.num_dofs()
            with pytest.raises(RuntimeError, match="unusable"):
                client.num_dofs()
        assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("command", [np.zeros(6), np.full(7, np.nan), np.ones(7) * 2])
def test_invalid_command_never_reaches_server(robot_server, command):
    with RobotClient(port=robot_server["port"]) as client:
        with pytest.raises((ValueError, RuntimeError)):
            client.command_joint_state(command)
    assert not robot_server["commands"]
