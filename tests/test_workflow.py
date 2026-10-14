from __future__ import annotations

import json
import os
import signal
from dataclasses import replace

import numpy as np
import pytest

from agilex_controller import control, workflow


def install_devices(monkeypatch, config, robot_server, *, stop_signal=signal.SIGINT):
    events = []
    config = replace(config, robot=replace(config.robot, port=robot_server["port"]))

    class Server:
        def __init__(self, _config):
            events.append("server-start")

        def check_alive(self):
            pass

        def close(self):
            np.testing.assert_allclose(robot_server["position"][:6], 0)
            events.append("server-stop")

    class Leader:
        def __init__(self, *_args):
            events.append("leader-start")

        def align_to(self, *_args):
            pass

        def act(self, _observations):
            return np.array([0.01] * 6 + [0.6])

        def close(self):
            events.append("leader-stop")

    class Keyboard:
        def __init__(self):
            self.keys = iter(["r", None, "s", "r", None])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def poll(self):
            try:
                return next(self.keys)
            except StopIteration:
                os.kill(os.getpid(), stop_signal)
                raise AssertionError("signal handler should stop the loop") from None

    monkeypatch.setattr(workflow, "preflight", lambda *_args, **_kw: np.zeros(7))
    monkeypatch.setattr(workflow, "SDKServer", Server)
    monkeypatch.setattr(workflow, "GelloLeader", Leader)
    monkeypatch.setattr(control, "RecordingKeyboard", Keyboard)
    return config, events


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_record_save_interrupt_and_safe_shutdown(
    monkeypatch, config, robot_server, stop_signal
):
    config, events = install_devices(
        monkeypatch, config, robot_server, stop_signal=stop_signal
    )
    assert workflow.run_workflow(config, record=True, assume_yes=True) == 0
    (session,) = config.path("raw_data_root").iterdir()
    saved = session / "episodes/episode_000000.jsonl"
    partial = session / "episodes/episode_000001.jsonl.partial"
    assert saved.is_file() and partial.is_file()
    rows = [json.loads(line) for line in saved.read_text().splitlines()]
    assert len(rows) == 2
    assert [row["sequence"] for row in rows] == [0, 1]
    assert rows[0]["action"] == [0.01] * 6 + [0.6]
    assert rows[0]["joint_positions"] == rows[0]["action"]
    assert events == ["server-start", "leader-start", "leader-stop", "server-stop"]
    np.testing.assert_allclose(robot_server["commands"][-1][:6], 0)


def test_conversion_occurs_after_hardware_cleanup_and_propagates_failure(
    monkeypatch, config, robot_server
):
    config, events = install_devices(monkeypatch, config, robot_server)
    config = replace(config, recording=replace(config.recording, convert=True))

    def convert(_config, session, _output):
        assert events[-1] == "server-stop"
        assert (session / "episodes/episode_000000.jsonl").exists()
        assert (session / "episodes/episode_000001.jsonl.partial").exists()
        events.append("convert")
        return 7

    monkeypatch.setattr(workflow, "convert_session", convert)
    assert workflow.run_workflow(config, record=True, assume_yes=True) == 7
    assert events[-1] == "convert"


def test_leader_initialization_failure_still_zeros_and_stops_server(
    monkeypatch, config, robot_server
):
    config, events = install_devices(monkeypatch, config, robot_server)

    def broken(*_args):
        raise RuntimeError("serial initialization failed")

    monkeypatch.setattr(workflow, "GelloLeader", broken)
    with pytest.raises(RuntimeError, match="serial initialization failed"):
        workflow.run_workflow(config, assume_yes=True)
    assert events == ["server-start", "server-stop"]
    np.testing.assert_allclose(robot_server["commands"][-1][:6], 0)


def test_failed_server_readiness_does_not_send_motion(
    monkeypatch, config, robot_server
):
    config, events = install_devices(monkeypatch, config, robot_server)

    def failed(*_args):
        raise RuntimeError("startup failed")

    monkeypatch.setattr(workflow, "wait_for_server", failed)
    with pytest.raises(RuntimeError, match="startup failed"):
        workflow.run_workflow(config, assume_yes=True)
    assert events == ["server-start", "server-stop"]
    assert not robot_server["commands"]


def test_cancellation_never_starts_server(monkeypatch, config, robot_server):
    config, events = install_devices(monkeypatch, config, robot_server)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    assert workflow.run_workflow(config) == 0
    assert not events and not robot_server["commands"]


def test_existing_server_is_not_started_or_stopped(monkeypatch, config, robot_server):
    config, events = install_devices(monkeypatch, config, robot_server)
    assert (
        workflow.run_workflow(
            config, record=True, assume_yes=True, existing_server=True
        )
        == 0
    )
    assert events == ["leader-start", "leader-stop"]
    np.testing.assert_allclose(robot_server["commands"][-1][:6], 0)


def test_signal_during_leader_creation_still_closes_created_resource(
    monkeypatch, config, robot_server
):
    config, events = install_devices(monkeypatch, config, robot_server)

    class InterruptedLeader:
        def __init__(self, *_args):
            events.append("leader-start")
            os.kill(os.getpid(), signal.SIGTERM)

        def close(self):
            events.append("leader-stop")

    monkeypatch.setattr(workflow, "GelloLeader", InterruptedLeader)
    assert workflow.run_workflow(config, assume_yes=True) == 0
    assert events == ["server-start", "leader-start", "leader-stop", "server-stop"]


def test_exclusive_workflow_lock():
    with workflow.application_lock():
        with pytest.raises(RuntimeError, match="another"):
            with workflow.application_lock():
                pytest.fail("second lock acquisition should fail")


def test_signal_during_writer_start_does_not_leave_unstarted_thread(
    monkeypatch, config, robot_server
):
    import threading

    config, events = install_devices(monkeypatch, config, robot_server)
    original_start = threading.Thread.start

    def interrupt_start(thread):
        if thread.name.startswith("raw-episode-writer-"):
            os.kill(os.getpid(), signal.SIGTERM)
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", interrupt_start)
    assert workflow.run_workflow(config, record=True, assume_yes=True) == 0
    (session,) = config.path("raw_data_root").iterdir()
    assert (session / "episodes/episode_000000.jsonl.partial").exists()
    assert events[-1] == "server-stop"
    assert not any(
        t.name.startswith("raw-episode-writer-") for t in threading.enumerate()
    )


def test_unavailable_confirmation_input_does_not_start_hardware(
    monkeypatch, config, robot_server
):
    config, events = install_devices(monkeypatch, config, robot_server)

    def eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(RuntimeError, match="terminal input"):
        workflow.run_workflow(config)
    assert not events and not robot_server["commands"]


def test_occupied_managed_endpoint_is_refused_before_can_setup(
    monkeypatch, config, robot_server, tmp_path
):
    port_file = tmp_path / "serial"
    port_file.touch()
    config = replace(
        config,
        robot=replace(config.robot, port=robot_server["port"]),
        gello=replace(config.gello, port=str(port_file)),
    )

    def unexpected(*_args, **_kwargs):
        pytest.fail("CAN must not be touched when the SDK endpoint is occupied")

    monkeypatch.setattr(workflow.subprocess, "run", unexpected)
    with pytest.raises(RuntimeError, match="existing-server"):
        workflow.preflight(config, existing_server=False, skip_can_setup=False)


def test_sdk_subprocess_is_isolated_and_stopped(monkeypatch, config):
    import sys

    monkeypatch.setattr(
        workflow,
        "project_command",
        lambda *_args: [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    server = workflow.SDKServer(config)
    try:
        assert os.getsid(server.process.pid) == server.process.pid
        server.check_alive()
    finally:
        server.close()
    assert server.process.poll() is not None


def test_sdk_startup_failure_reports_child_log(monkeypatch, config):
    import sys

    monkeypatch.setattr(
        workflow,
        "project_command",
        lambda *_args: [
            sys.executable,
            "-c",
            "print('SDK boot failed'); raise SystemExit(3)",
        ],
    )
    server = workflow.SDKServer(config)
    try:
        server.process.wait(timeout=5)
        with pytest.raises(RuntimeError, match="SDK boot failed"):
            server.check_alive()
    finally:
        server.close()
