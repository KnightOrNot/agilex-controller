from __future__ import annotations

import math
from pathlib import Path

import pytest

from agilex_controller.cli import _parser, main
from agilex_controller.configuration import load_config


def test_migrated_calibration_matches_previous_installation():
    value = load_config()
    assert value.gello.joint_offsets == (math.pi,) * 6
    assert value.gello.joint_signs == (1, -1, -1, -1, 1, 1)
    assert value.gello.follower_signs == (1, 1, -1, -1, 1, 1)
    assert value.gello.gripper_config == (7, 159, 201)


@pytest.mark.parametrize("before_command", [True, False])
def test_config_cli_precedence_and_relative_paths(
    tmp_path, monkeypatch, before_command
):
    config_file = tmp_path / "experiment.toml"
    config_file.write_text('[robot]\nhz = 25\n[paths]\nraw_data_root = "samples"\n')
    options = ["--project-root", str(tmp_path), "--config", str(config_file)]
    argv = (
        [*options, "record", "--hz", "50"]
        if before_command
        else ["record", *options, "--hz", "50"]
    )
    args = _parser().parse_args(argv)
    monkeypatch.chdir("/tmp")
    value = load_config(args.project_root, args.config, vars(args))
    assert value.robot.hz == 50
    assert value.path("raw_data_root") == tmp_path / "samples"


@pytest.mark.parametrize(
    "contents",
    [
        "[typo]\nhz=50",
        "[robot]\nhzz=20",
        "[robot]\nhz=nan",
        "[recording]\nqueue_size=0",
        "[gello]\nfollower_signs=[1,1,1]",
        "[robot]\nport=true",
        "[safety]\ntransition_step_rad=0.1",
        "[gello]\njoint_ids=[1,2,3,4,5,7]",
        "[recording]\nconvert='yes'",
    ],
)
def test_bad_configuration_is_rejected(tmp_path, contents):
    path = tmp_path / "config.toml"
    path.write_text(contents)
    with pytest.raises(ValueError):
        load_config(tmp_path, path)


def test_invalid_rate_does_not_enter_workflow(monkeypatch, capsys):
    from agilex_controller import workflow

    def unexpected(*args, **kwargs):
        pytest.fail("invalid input must be rejected before hardware work")

    monkeypatch.setattr(workflow, "preflight", unexpected)
    assert main(["record", "--hz", "nan"]) == 1
    assert "finite" in capsys.readouterr().err


def test_scalar_motor_configuration_has_actionable_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[gello]\njoint_ids=6")
    with pytest.raises(ValueError, match="joint_ids must be an array"):
        load_config(tmp_path, path)


def test_cli_follower_signs_are_normalized_to_tuple():
    value = load_config(overrides={"joint_signs": [1] * 6})
    assert value.gello.follower_signs == (1,) * 6


def test_all_command_help_is_available_without_hardware():
    for command in (
        "read",
        "config",
        "status",
        "follow",
        "record",
        "follow-record",
        "movejs",
        "convert",
    ):
        with pytest.raises(SystemExit) as result:
            main([command, "--help"])
        assert result.value.code == 0


def test_unknown_command_returns_argparse_error():
    with pytest.raises(SystemExit) as result:
        main(["unknown"])
    assert result.value.code == 2


def test_sdk_and_converter_not_imported_by_help():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from agilex_controller.cli import main; main([]); "
            "assert not any(n.startswith(('agilex_sdk_python', 'lerobot', "
            "'agilex_gello_software', 'torch')) for n in sys.modules)",
        ],
        check=True,
        cwd=Path(__file__).parents[1],
    )
