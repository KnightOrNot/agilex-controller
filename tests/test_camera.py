"""Asynchronous camera episodes and control cleanup without physical devices."""

import json
import queue
import time
from dataclasses import replace

import numpy as np
import pytest
from camera_realsense.stream import VideoFrame

from agilex_controller.camera import CameraSession, ImageEpisodeWriter
from agilex_controller.configuration import CameraConfig, load_config
from agilex_controller.recording import RawEpisodeRecorder, RecordingError


@pytest.mark.parametrize("level", [0, 1, 9])
@pytest.mark.parametrize("depth", [False, True])
def test_fast_png_is_lossless_and_fsynced_before_finish(
    tmp_path, monkeypatch, level, depth
):
    from PIL import Image

    from agilex_controller import camera as module

    rng = np.random.default_rng(7)
    image = (
        rng.integers(0, 65536, (24, 34), dtype=np.uint16)
        if depth
        else rng.integers(0, 256, (24, 34, 3), dtype=np.uint8)
    )
    if depth:
        image[0, :4] = [0, 1, 256, 65535]
    image = image[:, ::-1]  # Also exercise non-contiguous input and byte order.
    packet = replace(frame(0), image=image, stream="depth" if depth else "color")
    synced = []
    original = module.os.fsync

    def fsync(fd):
        synced.append(fd)
        original(fd)

    monkeypatch.setattr(module.os, "fsync", fsync)
    writer = ImageEpisodeWriter(
        tmp_path / "lossless.partial", 4, png_compress_level=level
    )
    writer.add(packet)
    path = writer.finish()
    with Image.open(path / "frames/000000.png") as decoded:
        assert decoded.format == "PNG"
        np.testing.assert_array_equal(np.asarray(decoded), image)
    rows = (path / "frames.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["stream"] == packet.stream
    assert len(synced) == 2  # Image and frame index; durability remains enforced.


def frame(index, timestamp=None):
    mapped = time.monotonic_ns() if timestamp is None else timestamp
    return VideoFrame(
        np.full((64, 64, 3), [20 + index * 10, 40, 80], dtype=np.uint8),
        mapped,
        time.monotonic_ns(),
        1000 + index * 1000 / 30,
        "global_time",
        index,
        mapped - round((1000 + index * 1000 / 30) * 1e6),
        100,
    )


class FakeSource:
    def __init__(self, **_options):
        self.closed = False
        self.frames = queue.Queue()
        self.frames.put(frame(0))
        self.metadata = {
            "width": 64,
            "height": 64,
            "fps": 30,
            "clock": "time.monotonic_ns",
        }

    def start(self):
        return self

    def read(self, **_options):
        try:
            return self.frames.get(timeout=0.01)
        except queue.Empty:
            return None

    def close(self):
        self.closed = True


def wait_frame(camera, index):
    deadline = time.monotonic() + 2
    while camera._latest.frame_number != index and time.monotonic() < deadline:
        time.sleep(0.002)
    assert camera._latest.frame_number == index


def test_startup_timeout_reports_source_diagnostics_and_closes():
    source = FakeSource()
    source.frames.get_nowait()
    source.startup_status = (
        "phase=startup, restarts=3, last_restart=depth counter reset"
    )
    with pytest.raises(
        RuntimeError, match="startup timeout; phase=startup, restarts=3"
    ):
        CameraSession(
            CameraConfig(startup_timeout_s=0.05, depth_enabled=False),
            source_factory=lambda **kwargs: source,
        )
    assert source.closed


def sample(timestamp):
    return {
        "command_time_ns": timestamp - 1,
        "observation_time_ns": timestamp,
        "wall_time_ns": timestamp,
        "control_period_ns": 20_000_000,
        "action": [0.0] * 6 + [0.5],
        "joint_positions": [0.0] * 6 + [0.5],
        "joint_velocities": [0.0] * 7,
        "ee_pos_quat": [0, 0, 0, 0, 0, 0, 1],
        "gripper_position": 0.5,
    }


def test_save_discard_and_interrupted_camera_episodes(tmp_path):
    camera = CameraSession(
        CameraConfig(frame_timeout_s=10, depth_enabled=False), source_factory=FakeSource
    )
    recorder = RawEpisodeRecorder(
        tmp_path, control_hz=50, joint_signs=[1] * 6, task="camera test", cameras=camera
    )
    try:
        manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
        assert manifest["format_version"] == 2
        recorder.start_episode()
        camera._source.frames.put(frame(1))
        wait_frame(camera, 1)
        recorder.add_sample(sample(camera._latest.timestamp_ns))
        recorder.save_episode()
        folder = recorder.session_dir / "cameras/front/episode_000000"
        rows = [
            json.loads(line)
            for line in (folder / "frames.jsonl").read_text().splitlines()
        ]
        assert len(rows) == 2  # Initial pre-roll and the independently acquired frame.
        assert all((folder / row["file"]).is_file() for row in rows)
        recorder.start_episode()
        recorder.add_sample(sample(camera._latest.timestamp_ns))
        recorder.discard_episode()
        assert not (
            recorder.session_dir / "cameras/front/episode_000001.partial"
        ).exists()
        recorder.start_episode()
        recorder.add_sample(sample(camera._latest.timestamp_ns))
        camera.close()
        recorder.close_interrupted()
        assert (
            recorder.session_dir / "cameras/front/episode_000001.partial/frames.jsonl"
        ).exists()
        assert not (recorder.episodes_dir / "episode_000001.jsonl").exists()
    finally:
        camera.close()
        recorder.close_interrupted()
    assert camera._source.closed


def test_empty_camera_episode_can_be_started_again(tmp_path):
    camera = CameraSession(
        CameraConfig(frame_timeout_s=10, depth_enabled=False), source_factory=FakeSource
    )
    recorder = RawEpisodeRecorder(
        tmp_path, control_hz=50, joint_signs=[1] * 6, task="empty", cameras=camera
    )
    try:
        recorder.start_episode()
        with pytest.raises(RecordingError, match="empty"):
            recorder.save_episode()
        recorder.start_episode()
        recorder.discard_episode()
    finally:
        camera.close()


def test_disk_error_prevents_joint_episode_from_becoming_formal(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("agilex_controller.camera._save_png", fail)
    writer = ImageEpisodeWriter(tmp_path / "camera.partial", 4)
    writer.add(frame(0))
    with pytest.raises(RecordingError, match="disk full"):
        writer.finish()
    assert not writer._thread.is_alive()


def test_camera_start_failure_closes_source():
    source = FakeSource()

    def fail():
        raise RuntimeError("device unavailable")

    source.start = fail
    with pytest.raises(RuntimeError, match="device unavailable"):
        CameraSession(
            CameraConfig(depth_enabled=False), source_factory=lambda **_kw: source
        )
    assert source.closed


@pytest.mark.parametrize(
    "camera",
    [
        "enabled = 1",
        'name = "../bad"',
        "fps = 0",
        "max_skew_ms = nan",
        "png_compress_level = -1",
        "png_compress_level = 10",
        "png_compress_level = true",
    ],
)
def test_camera_config_validation(tmp_path, camera):
    path = tmp_path / "config.toml"
    path.write_text("[camera]\n" + camera + "\n")
    with pytest.raises(ValueError, match="camera"):
        load_config(tmp_path, path)


def test_camera_failure_uses_existing_zero_and_service_cleanup(
    monkeypatch, config, robot_server
):
    from test_workflow import install_devices

    from agilex_controller import workflow

    config, events = install_devices(monkeypatch, config, robot_server)
    config = replace(config, camera=replace(config.camera, enabled=True))

    class Camera:
        def __init__(self, _config):
            events.append("camera-start")

        def check_health(self):
            if "leader-start" in events:
                raise RuntimeError("camera disconnected")

        def close(self):
            np.testing.assert_allclose(robot_server["position"][:6], 0)
            events.append("camera-stop")

    monkeypatch.setattr("agilex_controller.camera.CameraSession", Camera)
    with pytest.raises(RuntimeError, match="camera disconnected"):
        workflow.run_workflow(config, assume_yes=True)
    assert events == [
        "camera-start",
        "server-start",
        "leader-start",
        "leader-stop",
        "server-stop",
        "camera-stop",
    ]


def depth_frame(index, timestamp=None):
    result = frame(index, timestamp)
    image = np.full((64, 64), 1000 + index * 17, dtype=np.uint16)
    image[0, 0], image[0, 1] = 0, 65535
    return replace(result, image=image, stream="depth")


class RGBDSource(FakeSource):
    def __init__(self, **options):
        super().__init__(**options)
        self.frames.put(depth_frame(0))
        self.metadata["depth"] = {
            "width": 64,
            "height": 64,
            "fps": 30,
            "depth_units_m": 0.001,
            "spatial_alignment": "native_depth",
        }


def wait_depth(camera, index):
    deadline = time.monotonic() + 2
    while (
        camera._frames.get("depth") is None
        or camera._frames["depth"].frame_number != index
    ) and time.monotonic() < deadline:
        time.sleep(0.002)
    assert camera._frames["depth"].frame_number == index


def test_depth_write_failure_keeps_entire_episode_partial(tmp_path, monkeypatch):
    from agilex_controller.camera import _save_png

    camera = CameraSession(CameraConfig(frame_timeout_s=10), source_factory=RGBDSource)
    recorder = RawEpisodeRecorder(
        tmp_path,
        control_hz=50,
        joint_signs=[1] * 6,
        task="RGBD failure",
        cameras=camera,
    )

    def fail_depth(image, *args, **kwargs):
        if image.dtype == np.uint16:
            raise OSError("depth disk failure")
        return _save_png(image, *args, **kwargs)

    monkeypatch.setattr("agilex_controller.camera._save_png", fail_depth)
    recorder.start_episode()
    recorder.add_sample(sample(camera._latest.timestamp_ns))
    try:
        with pytest.raises(RecordingError, match="depth disk failure"):
            recorder.save_episode()
        assert not (recorder.episodes_dir / "episode_000000.jsonl").exists()
        assert all(
            not writer._thread.is_alive() for writer in camera._finished.values()
        )
    finally:
        with pytest.raises(RecordingError, match="depth disk failure"):
            camera.close()
        with pytest.raises(RecordingError, match="depth disk failure"):
            recorder.close_interrupted()


def test_depth_startup_timeout_releases_source():
    source = FakeSource()
    with pytest.raises(RuntimeError, match="startup timeout"):
        CameraSession(
            CameraConfig(startup_timeout_s=0.02), source_factory=lambda **_kw: source
        )
    assert source.closed


def test_full_camera_queue_reports_loss_instead_of_dropping_frames(
    tmp_path, monkeypatch
):
    import threading

    from agilex_controller.camera import _save_png

    gate, entered = threading.Event(), threading.Event()

    def block(image, *args, **kwargs):
        entered.set()
        assert gate.wait(2)
        return _save_png(image, *args, **kwargs)

    monkeypatch.setattr("agilex_controller.camera._save_png", block)
    writer = ImageEpisodeWriter(tmp_path / "bounded.partial", 1)
    try:
        writer.add(frame(0))
        assert entered.wait(1)
        writer.add(frame(1))
        with pytest.raises(RecordingError, match="queue is full"):
            writer.add(frame(2))
    finally:
        gate.set()
        with pytest.raises(RecordingError, match="queue is full"):
            writer.finish()


def test_camera_failure_stops_initial_js_but_cleanup_can_still_zero(
    monkeypatch, config, robot_server
):
    from test_workflow import install_devices

    from agilex_controller import workflow

    config, events = install_devices(monkeypatch, config, robot_server)
    config = replace(config, camera=replace(config.camera, enabled=True))

    class Camera:
        def __init__(self, _config):
            pass

        def check_health(self):
            raise RuntimeError("depth stopped before alignment")

        def close(self):
            events.append("camera-stop")

    monkeypatch.setattr("agilex_controller.camera.CameraSession", Camera)
    with pytest.raises(RuntimeError, match="depth stopped"):
        workflow.run_workflow(config, assume_yes=True)
    assert "leader-start" not in events
    assert events == ["server-start", "server-stop", "camera-stop"]
    np.testing.assert_allclose(robot_server["position"][:6], 0)


def test_capture_failure_during_save_never_publishes_joint_episode(tmp_path):
    camera = CameraSession(
        CameraConfig(frame_timeout_s=10, depth_enabled=False), source_factory=FakeSource
    )
    recorder = RawEpisodeRecorder(
        tmp_path,
        control_hz=50,
        joint_signs=[1] * 6,
        task="capture race",
        cameras=camera,
    )
    recorder.start_episode()
    recorder.add_sample(sample(camera._latest.timestamp_ns))
    camera._error = RuntimeError("capture failed during save")
    try:
        with pytest.raises(RecordingError, match="capture failed during save"):
            recorder.save_episode()
        assert not (recorder.episodes_dir / "episode_000000.jsonl").exists()
    finally:
        with pytest.raises(RecordingError, match="capture failed during save"):
            camera.close()
        with pytest.raises(RecordingError, match="capture failed during save"):
            recorder.close_interrupted()
