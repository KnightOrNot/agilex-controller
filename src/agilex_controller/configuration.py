"""Validated application configuration; paths are relative to the project root."""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RobotConfig:
    host: str = "127.0.0.1"
    port: int = 6001
    hz: float = 50.0
    can_interface: str = "can0"
    can_bitrate: int = 1_000_000


@dataclass(frozen=True)
class GelloConfig:
    port: str = (
        "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTBM4Z46-if00-port0"
    )
    # Device calibration belongs to this installation, not the reusable GELLO fork.
    joint_ids: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    joint_offsets: tuple[float, ...] = (
        math.pi,
        math.pi,
        math.pi,
        math.pi,
        math.pi,
        math.pi,
    )
    joint_signs: tuple[int, ...] = (1, -1, -1, -1, 1, 1)
    gripper_config: tuple[int, ...] = (7, 159, 201)
    # This maps calibrated master joints to the particular PiPER-X installation.
    follower_signs: tuple[int, ...] = (1, 1, -1, -1, 1, 1)


@dataclass(frozen=True)
class RecordingConfig:
    task: str = "PiPER-X GELLO teleoperation"
    queue_size: int = 500
    dataset_fps: int = 30
    convert: bool = True
    start_recording: bool = False


@dataclass(frozen=True)
class CameraConfig:
    enabled: bool = False
    name: str = "front"
    serial: str = ""
    depth_enabled: bool = True
    depth_width: int = 640
    depth_height: int = 480
    depth_fps: int = 30
    width: int = 640
    height: int = 480
    fps: int = 30
    warmup_frames: int = 15
    startup_timeout_s: float = 10.0
    frame_timeout_s: float = 1.0
    queue_size: int = 32
    png_compress_level: int = 0
    max_skew_ms: float = 50.0
    preview: bool = False


@dataclass(frozen=True)
class SafetyConfig:
    max_start_error_rad: float = 0.35
    transition_step_rad: float = 0.02
    max_command_step_rad: float = 1.0
    request_timeout_s: float = 2.0
    startup_timeout_s: float = 15.0


@dataclass(frozen=True)
class PathsConfig:
    sdk_project: str = "agilex-sdk-python"
    converter_project: str = "lerobot-converter"
    raw_data_root: str = "data/raw"
    lerobot_data_root: str = "data/lerobot"


@dataclass(frozen=True)
class ControllerConfig:
    root: Path
    robot: RobotConfig = field(default_factory=RobotConfig)
    gello: GelloConfig = field(default_factory=GelloConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)

    def path(self, name: str) -> Path:
        return (self.root / getattr(self.paths, name)).resolve()

    def validate(self) -> None:
        camera = self.camera
        if any(
            type(getattr(camera, key)) is not bool
            for key in ("enabled", "preview", "depth_enabled")
        ):
            raise ValueError(
                "camera enabled, preview and depth_enabled must be boolean"
            )
        if not isinstance(camera.name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*", camera.name
        ):
            raise ValueError(
                "camera.name must be an identifier without path separators"
            )
        if not isinstance(camera.serial, str):
            raise ValueError("camera.serial must be a string; empty selects one device")
        for name in (
            "width",
            "height",
            "fps",
            "depth_width",
            "depth_height",
            "depth_fps",
            "queue_size",
        ):
            if type(getattr(camera, name)) is not int or getattr(camera, name) <= 0:
                raise ValueError(f"camera.{name} must be a positive integer")
        if type(camera.warmup_frames) is not int or camera.warmup_frames < 0:
            raise ValueError("camera.warmup_frames must be a non-negative integer")
        if (
            type(camera.png_compress_level) is not int
            or not 0 <= camera.png_compress_level <= 9
        ):
            raise ValueError("camera.png_compress_level must be an integer in [0, 9]")
        for name in ("startup_timeout_s", "frame_timeout_s", "max_skew_ms"):
            value = getattr(camera, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"camera.{name} must be positive and finite")
        for name, value in (
            ("robot.port", self.robot.port),
            ("robot.can_bitrate", self.robot.can_bitrate),
            ("recording.queue_size", self.recording.queue_size),
            ("recording.dataset_fps", self.recording.dataset_fps),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.robot.port > 65535:
            raise ValueError("robot.port must be within [1, 65535]")
        for name, value in (
            ("robot.hz", self.robot.hz),
            *(
                (f"safety.{f.name}", getattr(self.safety, f.name))
                for f in fields(self.safety)
            ),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.safety.transition_step_rad > 0.05:
            raise ValueError("safety.transition_step_rad must be at most 0.05")
        if self.safety.max_command_step_rad > 1.0:
            raise ValueError("safety.max_command_step_rad must be at most 1.0")
        for name, value in (
            ("robot.host", self.robot.host),
            ("robot.can_interface", self.robot.can_interface),
            ("gello.port", self.gello.port),
            ("recording.task", self.recording.task),
            *(
                (f"paths.{f.name}", getattr(self.paths, f.name))
                for f in fields(self.paths)
            ),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("convert", "start_recording"):
            if type(getattr(self.recording, name)) is not bool:
                raise ValueError(f"recording.{name} must be boolean")
        device = self.gello
        for name in (
            "joint_ids",
            "joint_offsets",
            "joint_signs",
            "gripper_config",
            "follower_signs",
        ):
            if not isinstance(getattr(device, name), tuple):
                raise ValueError(f"gello.{name} must be an array")
        if len(device.joint_ids) != 6 or any(
            type(i) is not int or not 0 <= i <= 252 for i in device.joint_ids
        ):
            raise ValueError("gello.joint_ids must contain six Dynamixel IDs")
        if len(device.gripper_config) != 3 or any(
            type(x) is not int for x in device.gripper_config
        ):
            raise ValueError(
                "gello.gripper_config must contain [id, open_deg, closed_deg]"
            )
        motor_id, opened, closed = device.gripper_config
        if not 0 <= motor_id <= 252 or opened == closed:
            raise ValueError("gello.gripper_config has invalid ID or equal endpoints")
        if len(set((*device.joint_ids, motor_id))) != 7:
            raise ValueError("GELLO motor IDs must be unique")
        if len(device.joint_offsets) != 6 or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in device.joint_offsets
        ):
            raise ValueError("gello.joint_offsets must contain six finite radians")
        for name in ("joint_signs", "follower_signs"):
            signs = getattr(device, name)
            if len(signs) != 6 or any(
                type(x) is not int or x not in (-1, 1) for x in signs
            ):
                raise ValueError(f"gello.{name} must contain six +1/-1 values")


SECTIONS = {
    "robot": RobotConfig,
    "gello": GelloConfig,
    "recording": RecordingConfig,
    "camera": CameraConfig,
    "safety": SafetyConfig,
    "paths": PathsConfig,
}

OVERRIDES = {
    "camera_enabled": ("camera", "enabled"),
    "camera_depth_enabled": ("camera", "depth_enabled"),
    "camera_preview": ("camera", "preview"),
    "camera_serial": ("camera", "serial"),
    "camera_width": ("camera", "width"),
    "camera_height": ("camera", "height"),
    "camera_fps": ("camera", "fps"),
    "camera_png_compress_level": ("camera", "png_compress_level"),
    "host": ("robot", "host"),
    "port": ("robot", "port"),
    "hz": ("robot", "hz"),
    "can_interface": ("robot", "can_interface"),
    "can_bitrate": ("robot", "can_bitrate"),
    "gello_port": ("gello", "port"),
    "joint_signs": ("gello", "follower_signs"),
    "task": ("recording", "task"),
    "record_queue_size": ("recording", "queue_size"),
    "dataset_fps": ("recording", "dataset_fps"),
    "convert": ("recording", "convert"),
    "start_recording": ("recording", "start_recording"),
    "request_timeout_s": ("safety", "request_timeout_s"),
    "startup_timeout_s": ("safety", "startup_timeout_s"),
    "max_start_error_rad": ("safety", "max_start_error_rad"),
    "transition_step_rad": ("safety", "transition_step_rad"),
    "max_command_step_rad": ("safety", "max_command_step_rad"),
    "sdk_project": ("paths", "sdk_project"),
    "converter_project": ("paths", "converter_project"),
    "raw_data_root": ("paths", "raw_data_root"),
    "lerobot_data_root": ("paths", "lerobot_data_root"),
}


def load_config(
    root: str | Path | None = None,
    config_file: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> ControllerConfig:
    project = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    path = (
        Path(config_file).resolve() if config_file else project / "config/default.toml"
    )
    if config_file is not None or path.exists():
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    else:
        data = {}
    # [collection] configures the separate browser app; it shares this file but
    # is validated by agilex_data_collection.config.AppConfig.
    unknown = data.keys() - SECTIONS.keys() - {"collection"}
    if unknown:
        raise ValueError(f"unknown configuration sections: {sorted(unknown)}")
    sections = {}
    for name, cls in SECTIONS.items():
        values = data.get(name, {})
        if not isinstance(values, dict):
            raise ValueError(f"{name} must be a TOML table")
        unknown = values.keys() - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown {name} options: {sorted(unknown)}")
        sections[name] = cls(
            **{k: tuple(v) if isinstance(v, list) else v for k, v in values.items()}
        )
    for key, value in (overrides or {}).items():
        if key in OVERRIDES:
            section, attribute = OVERRIDES[key]
            if isinstance(value, list):
                value = tuple(value)
            sections[section] = replace(sections[section], **{attribute: value})
    result = ControllerConfig(root=project, **sections)
    result.validate()
    return result
