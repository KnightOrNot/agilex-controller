"""Write controller raw data, convert with Python 3.12, and load the result."""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from agilex_controller.cli import main
from agilex_controller.control import _sample_from_cycle
from agilex_controller.recording import RawEpisodeRecorder

ROOT = Path(__file__).resolve().parents[1]
CONVERTER_PYTHON = ROOT / "lerobot-converter/.venv/bin/python"


@pytest.mark.integration
@pytest.mark.skipif(
    not CONVERTER_PYTHON.is_file(), reason="converter environment not installed"
)
def test_controller_raw_converts_and_loads_as_lerobot(tmp_path):
    recorder = RawEpisodeRecorder(
        tmp_path / "raw",
        control_hz=50,
        joint_signs=[1, 1, -1, -1, 1, 1],
        task="controller regression",
    )
    recorder.start_episode()
    for index in range(20):
        timestamp = 1_000_000_000 + index * 20_000_000
        recorder.add_sample(
            _sample_from_cycle(
                command=np.array([0.1] * 6 + [0.7]),
                observations={
                    "joint_positions": np.array([0.09] * 6 + [0.6]),
                    "joint_velocities": np.zeros(7),
                    "ee_pos_quat": np.array([0, 0, 0.2, 0, 0, 0, 1]),
                    "gripper_position": np.array(0.6),
                },
                command_time_ns=timestamp - 1,
                observation_time_ns=timestamp,
                wall_time_ns=timestamp + 1,
                control_period_ns=20_000_000,
            )
        )
    recorder.save_episode()
    recorder.start_episode()
    recorder.close_interrupted()
    raw_path = recorder.episodes_dir / "episode_000000.jsonl"
    original = raw_path.read_bytes()
    output = tmp_path / "dataset"
    assert (
        main(
            [
                "convert",
                str(recorder.session_dir),
                str(output),
                "--fps",
                "30",
                "--repo-id",
                "local/controller-regression",
            ]
        )
        == 0
    )
    assert raw_path.read_bytes() == original
    report = json.loads((output / "quality_report.json").read_text())
    assert report["kept_episodes"] == 1
    assert report["ignored_partial_episodes"] == 1
    assert report["converted_frames"] == 12
    script = (
        "from lerobot.datasets.lerobot_dataset import LeRobotDataset; "
        "import sys; "
        "d = LeRobotDataset('local/controller-regression', root=sys.argv[1]); "
        "assert len(d) == 12; "
        "assert d.num_episodes == 1; "
        "assert tuple(d[0]['action'].shape) == (7,); "
        "assert abs(float(d[0]['action'][6]) - 0.7) < 1e-6; "
        "print('LeRobot round-trip: 1 episode, 12 frames, 7D action')"
    )
    subprocess.run(
        [str(CONVERTER_PYTHON), "-c", script, str(output)],
        check=True,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
        timeout=60,
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not CONVERTER_PYTHON.is_file(), reason="converter environment not installed"
)
@pytest.mark.parametrize("depth_enabled", [False, True])
def test_rgb_recording_converts_to_timestamp_aligned_video(tmp_path, depth_enabled):
    import time

    from test_camera import (
        FakeSource,
        depth_frame,
        frame,
        sample,
        wait_depth,
        wait_frame,
    )

    from agilex_controller.camera import CameraSession
    from agilex_controller.configuration import CameraConfig

    base = time.monotonic_ns() - 500_000_000
    source = FakeSource()
    source.frames.get_nowait()
    source.frames.put(frame(0, base))
    if depth_enabled:
        source.metadata["depth"] = {
            "width": 64,
            "height": 64,
            "fps": 30,
            "depth_units_m": 0.001,
        }
        source.frames.put(depth_frame(0, base + 1_000_000))
    camera = CameraSession(
        CameraConfig(frame_timeout_s=10, depth_enabled=depth_enabled),
        source_factory=lambda **_kw: source,
    )
    recorder = RawEpisodeRecorder(
        tmp_path / "raw",
        control_hz=50,
        joint_signs=[1] * 6,
        task="RGB round trip",
        cameras=camera,
    )
    try:
        recorder.start_episode()
        for index in range(1, 13):
            source.frames.put(frame(index, base + round(index * 1e9 / 30)))
            wait_frame(camera, index)
            if depth_enabled:
                source.frames.put(
                    depth_frame(index, base + round(index * 1e9 / 30) + 1_000_000)
                )
                wait_depth(camera, index)
        for index in range(20):
            recorder.add_sample(sample(base + index * 20_000_000))
        recorder.save_episode()
    finally:
        camera.close()
        recorder.close_interrupted()
    original = {
        str(p.relative_to(recorder.session_dir)): p.read_bytes()
        for p in recorder.session_dir.rglob("*")
        if p.is_file()
    }
    output = tmp_path / "rgb_dataset"
    assert (
        main(
            [
                "convert",
                str(recorder.session_dir),
                str(output),
                "--fps",
                "30",
                "--repo-id",
                "local/rgb-regression",
            ]
        )
        == 0
    )
    assert list(output.rglob("*.mp4"))
    report = json.loads((output / "quality_report.json").read_text())
    quality = report["episodes"][0]["cameras"]["front"]
    assert quality["unique_frames"] == 12
    assert quality["max_time_match_error_ms"] < 0.001
    if depth_enabled:
        assert (
            abs(
                report["episodes"][0]["cameras"]["front_depth"][
                    "max_time_match_error_ms"
                ]
                - 1
            )
            < 0.001
        )
    assert original == {
        str(p.relative_to(recorder.session_dir)): p.read_bytes()
        for p in recorder.session_dir.rglob("*")
        if p.is_file()
    }
    script = """
import sys
from lerobot.datasets.lerobot_dataset import LeRobotDataset

d = LeRobotDataset('local/rgb-regression', root=sys.argv[1], depth_output_unit='m')
assert len(d) == 12
for i in range(len(d)):
    image = d[i]['observation.images.front']
    assert tuple(image.shape) == (3, 64, 64)
    assert abs(float(image[0].mean()) - (20 + 10 * i) / 255) < 0.05
    if len(sys.argv) > 2:
        depth = d[i]['observation.images.front_depth']
        assert tuple(depth.shape) == (1, 64, 64)
        assert float(depth[0, 0, 0]) == 0
        assert abs(float(depth[0, 0, 1]) - 65.535) < 1e-5
        assert abs(float(depth[0, 1, 1]) - (1000 + i * 17) * 0.001) < 1e-6
print('RGB-D round-trip: 12 aligned frames decoded, metric depth preserved')
"""
    subprocess.run(
        [
            str(CONVERTER_PYTHON),
            "-c",
            script,
            str(output),
            *(["depth"] if depth_enabled else []),
        ],
        check=True,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
        timeout=60,
    )
