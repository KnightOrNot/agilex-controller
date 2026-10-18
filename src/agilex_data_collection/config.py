"""Configuration for the new app, independent of legacy command parsing."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    hardware_config: str = "config/default.toml"
    data_root: str = "data/lerobot/app"
    control_hz: int = 50
    dataset_fps: int = 30
    max_skew_ms: float = 50.0
    queue_size: int = 90
    watchdog_s: float = 1.0
    camera_enabled: bool = True
    camera_mode: str = "auto"
    depth_enabled: bool = True

    @classmethod
    def load(cls, path: Path) -> AppConfig:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        unknown = data.keys() - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown collection settings: {sorted(unknown)}")
        config = cls(**data)
        for name in ("control_hz", "dataset_fps", "queue_size"):
            value = getattr(config, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("max_skew_ms", "watchdog_s"):
            value = getattr(config, name)
            if (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive and finite")
        if config.dataset_fps > config.control_hz:
            raise ValueError("dataset_fps cannot exceed control_hz")
        for name in ("camera_enabled", "depth_enabled"):
            if type(getattr(config, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if type(config.camera_mode) is not str or config.camera_mode not in {
            "auto",
            "fast",
            "slow",
            "manual",
        }:
            raise ValueError("camera_mode must be auto, fast, slow or manual")
        return config
