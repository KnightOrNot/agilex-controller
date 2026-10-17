"""Hardware-free coverage of the independent entry point and configuration."""

from pathlib import Path

import pytest

from agilex_data_collection import main
from agilex_data_collection.config import AppConfig


def test_help_does_not_import_runtime(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    assert "serve" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "dataset_fps = 60",
        "watchdog_s = -1",
        "control_hz = true",
        "camera_enabled = 1",
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
