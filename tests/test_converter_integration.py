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
