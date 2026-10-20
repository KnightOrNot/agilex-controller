"""Hardware-free coverage of the independent entry point and configuration."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilex_data_collection import main
from agilex_data_collection.config import AppConfig
from agilex_data_collection.worker import check_can_ready


def test_help_does_not_import_runtime(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    assert "serve" in capsys.readouterr().out


@pytest.mark.parametrize("simulate", [False, True])
def test_serve_prepares_can_before_exec_only_for_hardware(
    tmp_path, monkeypatch, simulate
):
    import agilex_data_collection as entry

    adapters = tmp_path / "agilex-adapters"
    (adapters / ".venv/bin").mkdir(parents=True)
    (adapters / "pyproject.toml").touch()
    (adapters / ".venv/bin/python").touch()
    events = []
    config_path = tmp_path / "custom.toml"
    monkeypatch.setattr(entry.shutil, "which", lambda _name: "/fake/uv")
    monkeypatch.setattr(
        entry, "configure_can", lambda project, path: events.append((project, path))
    )

    def execve(*_args):
        events.append("exec")

    monkeypatch.setattr(entry.os, "execve", execve)
    args = ["--project", str(tmp_path), "serve", "--config", str(config_path)]
    if simulate:
        args.append("--simulate")
    assert entry.main(args) == 0
    assert events == (["exec"] if simulate else [(tmp_path, config_path), "exec"])


def test_can_setup_uses_hardware_toml_and_shared_lock(tmp_path, monkeypatch):
    import contextlib

    from agilex_controller import workflow
    from agilex_data_collection import configure_can

    hardware = tmp_path / "hardware.toml"
    hardware.write_text('[robot]\ncan_interface = "can7"\ncan_bitrate = 500000\n')
    app = tmp_path / "app.toml"
    app.write_text('hardware_config = "hardware.toml"\n')
    script = tmp_path / "agilex-sdk-python/scripts/config_can.sh"
    script.parent.mkdir(parents=True)
    script.touch()
    events = []

    @contextlib.contextmanager
    def lock():
        events.append("lock")
        yield
        events.append("unlock")

    def run(command, **kwargs):
        assert events == ["lock"]
        assert command == [str(script), "can7", "500000"]
        assert kwargs == {"cwd": tmp_path, "check": True}
        events.append("configured")

    monkeypatch.setattr(workflow, "application_lock", lock)
    monkeypatch.setattr("agilex_data_collection.subprocess.run", run)
    configure_can(tmp_path, app)
    assert events == ["lock", "configured", "unlock"]


def test_can_setup_failure_prevents_server_start(tmp_path, monkeypatch):
    import agilex_data_collection as entry

    adapters = tmp_path / "agilex-adapters"
    (adapters / ".venv/bin").mkdir(parents=True)
    (adapters / "pyproject.toml").touch()
    (adapters / ".venv/bin/python").touch()
    monkeypatch.setattr(entry.shutil, "which", lambda _name: "/fake/uv")

    def fail(*_args):
        raise subprocess.CalledProcessError(1, ["config_can.sh"])

    monkeypatch.setattr(entry, "configure_can", fail)
    monkeypatch.setattr(
        entry.os, "execve", lambda *_args: pytest.fail("server started")
    )
    with pytest.raises(SystemExit) as result:
        entry.main(["--project", str(tmp_path), "serve"])
    assert result.value.code != 0


@pytest.mark.parametrize(
    "text",
    [
        "dataset_fps = 60",
        "watchdog_s = -1",
        "control_hz = true",
        "camera_enabled = 1",
        "position_tolerance_deg = 0",
        "position_tolerance_deg = true",
        "position_tolerance_deg = nan",
        'camera_mode = "invalid"',
        "camera_mode = []",
        "unknown = 1",
    ],
)
def test_reject_invalid_app_configuration(tmp_path: Path, text: str):
    path = tmp_path / "settings.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        AppConfig.load(path)


def test_app_configuration_is_separate():
    project = Path(__file__).resolve().parents[1]
    app = AppConfig.load(project / "config/data_collection.toml")
    assert app.dataset_fps == 30
    assert app.control_hz == 50
    assert app.camera_enabled and app.depth_enabled


@pytest.mark.parametrize(
    ("flags", "state", "bitrate", "error"),
    [
        (["UP"], "ERROR-ACTIVE", 1_000_000, None),
        ([], "STOPPED", None, "DOWN"),
        (["UP"], "BUS-OFF", 1_000_000, "stopped"),
        (["UP"], "ERROR-ACTIVE", 500_000, "bitrate"),
    ],
)
def test_can_readiness_does_not_open_hardware(
    monkeypatch, flags, state, bitrate, error
):
    def inspect(command, **kwargs):
        assert command == ["ip", "-details", "-json", "link", "show", "dev", "can0"]
        assert kwargs == dict(check=True, capture_output=True, text=True, timeout=5)
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {
                        # SocketCAN may report operstate UNKNOWN while enabled.
                        "operstate": "UNKNOWN",
                        "flags": flags,
                        "linkinfo": {
                            "info_kind": "can",
                            "info_data": {
                                "state": state,
                                "bittiming": {"bitrate": bitrate},
                            },
                        },
                    }
                ]
            )
        )

    monkeypatch.setattr("agilex_data_collection.worker.subprocess.run", inspect)
    if error:
        with pytest.raises(RuntimeError, match=error) as result:
            check_can_ready("can0", 1_000_000)
        assert "config_can.sh can0 1000000" in str(result.value)
    else:
        check_can_ready("can0", 1_000_000)


@pytest.mark.parametrize(
    "failure", [FileNotFoundError("ip"), subprocess.TimeoutExpired("ip", 5)]
)
def test_can_inspection_failure_is_actionable(monkeypatch, failure):
    def inspect(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("agilex_data_collection.worker.subprocess.run", inspect)
    with pytest.raises(RuntimeError, match="check iproute2 and device"):
        check_can_ready("can0", 1_000_000)


def test_can_check_precedes_sdk_camera_and_motion(monkeypatch):
    import contextlib

    from agilex_controller import workflow
    from agilex_data_collection.worker import Hardware

    project = Path(__file__).resolve().parents[1]
    hardware = Hardware(project, AppConfig())
    monkeypatch.setattr(workflow, "application_lock", contextlib.nullcontext)

    def down(*_args):
        raise RuntimeError("CAN interface is DOWN")

    def unexpected(*_args, **_kwargs):
        pytest.fail("hardware preflight must not run before CAN is ready")

    monkeypatch.setattr("agilex_data_collection.worker.check_can_ready", down)
    monkeypatch.setattr(workflow, "preflight", unexpected)
    try:
        with pytest.raises(RuntimeError, match="DOWN"):
            hardware.start()
        assert hardware.camera is hardware.robot is hardware.server is None
    finally:
        hardware._stack.close()


@pytest.mark.parametrize("tolerance", [1.0, 1.5])
def test_position_verifies_real_feedback_with_configured_tolerance(
    monkeypatch, capsys, tolerance
):
    import itertools

    import numpy as np

    from agilex_controller import control
    from agilex_data_collection.worker import Hardware

    class Robot:
        commands = []

        def get_joint_state(self):
            # Reproduce the reported physical residual, without hardware access.
            state = np.zeros(7)
            state[2] = np.deg2rad(1.032)
            return state

        def command_joint_state(self, command):
            self.commands.append(command.copy())

    clock = itertools.count()
    monkeypatch.setattr(control.time, "sleep", lambda _period: None)
    monkeypatch.setattr(control.time, "monotonic", lambda: float(next(clock)))
    app = AppConfig(position_tolerance_deg=tolerance)
    hardware = Hardware(Path(__file__).resolve().parents[1], app)
    robot = Robot()
    if tolerance == 1.0:
        with pytest.raises(RuntimeError, match="startup_zero.*J3 error=1.032"):
            hardware._position(robot, np.zeros(6), "startup_zero")
    else:
        hardware._position(robot, np.zeros(6), "startup_zero")
    np.testing.assert_allclose(robot.commands[-1][:6], 0)
    assert np.rad2deg(robot.get_joint_state()[2]) == pytest.approx(1.032)
    line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("[position_result] ")
    )
    report = json.loads(line.removeprefix("[position_result] "))
    assert report["final_error_deg"][2] == pytest.approx(1.032)
    assert report["observed_range_deg"] == [0] * 6
    assert report["commands"] == len(robot.commands)
    assert report["feedback_reads"] >= 2


def test_exit_zero_uses_same_tolerance_and_releases_resources_on_failure(monkeypatch):
    import numpy as np

    from agilex_controller import robot_client
    from agilex_data_collection.worker import Hardware

    events = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(self.name)

    class Client(Resource):
        def __init__(self, *_args):
            super().__init__("zero-client")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    app = AppConfig(position_tolerance_deg=1.5)
    hardware = Hardware(Path(__file__).resolve().parents[1], app)
    hardware.robot = Resource("follow-client")
    hardware.leader = Resource("leader")
    hardware.server = Resource("server")
    hardware.camera = Resource("camera")
    hardware.ready = True
    hardware._stack.callback(lambda: events.append("lock"))

    def position(robot, target, stage):
        assert isinstance(robot, Client)
        assert stage == "exit_zero"
        np.testing.assert_allclose(target, 0)
        assert hardware.app.position_tolerance_deg == 1.5
        events.append("zero")
        raise RuntimeError("exit_zero: positioning failed")

    monkeypatch.setattr(robot_client, "RobotClient", Client)
    monkeypatch.setattr(hardware, "_position", position)
    with pytest.raises(RuntimeError, match="exit_zero"):
        hardware.close()
    assert events == [
        "follow-client",
        "leader",
        "zero",
        "zero-client",
        "server",
        "camera",
        "lock",
    ]


@pytest.mark.parametrize(
    "startup_failure,cleanup_failure", [(True, False), (False, True), (True, True)]
)
def test_worker_preserves_primary_and_cleanup_errors(
    tmp_path, monkeypatch, capsys, startup_failure, cleanup_failure
):
    from agilex_data_collection import worker
    from agilex_data_collection.diagnostics import worker_failure

    events = []

    class FakeHardware:
        def __init__(self, _app):
            pass

        def start(self):
            if startup_failure:
                raise RuntimeError("startup_zero: J3 error=1.032 deg")
            raise KeyboardInterrupt

        def close(self):
            events.append("cleanup")
            if cleanup_failure:
                raise RuntimeError("exit_zero: J3 error=1.032 deg")

    path = tmp_path / "app.toml"
    path.write_text("")
    monkeypatch.setattr(worker, "Simulation", FakeHardware)
    monkeypatch.setattr(worker.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "worker",
            "--project",
            str(tmp_path),
            "--config",
            str(path),
            "--endpoint",
            f"ipc://{tmp_path}/test.sock",
            "--simulate",
        ],
    )
    assert worker.main() == 1
    assert events == ["cleanup"]
    log = tmp_path / "worker.log"
    log.write_text(capsys.readouterr().err + "[安全退出] 延迟输出\n")
    message = str(worker_failure(log, 1))
    if startup_failure:
        assert "startup_zero: J3 error=1.032" in message
    if cleanup_failure:
        assert "exit_zero: J3 error=1.032" in message
    assert "延迟输出" not in message


def test_legacy_traceback_not_masked_by_buffered_cleanup(tmp_path):
    from agilex_data_collection.diagnostics import worker_failure

    path = tmp_path / "worker.log"
    path.write_text(
        "Traceback (most recent call last):\n"
        '  File "worker.py", line 181, in start\n'
        "RuntimeError: JS positioning failed: J3 error=1.032 deg\n"
        "During handling of the above exception, another exception occurred:\n"
        "Traceback (most recent call last):\n"
        "RuntimeError: 安全回零: JS positioning failed: J3 error=1.032 deg\n"
        "[安全退出] 通过现有 JS 服务分步回零……\n"
    )
    message = str(worker_failure(path, 1))
    assert "RuntimeError: JS positioning failed: J3 error=1.032" in message
    assert "安全退出" not in message
