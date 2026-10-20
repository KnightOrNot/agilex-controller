"""Display-only RGB-D processing; never mutates acquired or recorded frames."""

from __future__ import annotations

import numpy as np


def depth_colors(depth: np.ndarray, units: float, max_depth_m: float) -> np.ndarray:
    meters = depth.astype(np.float64) * units
    t = np.clip(meters / max_depth_m, 0, 1)
    colors = np.stack(
        [np.clip(1.5 - np.abs(4 * t - shift), 0, 1) for shift in (3, 2, 1)],
        axis=-1,
    )
    colors[(depth == 0) | (meters > max_depth_m)] = 0
    return (colors * 255).astype(np.uint8)


def preview_image(
    frames: dict, camera: dict, mode: str, max_depth_m: float
) -> np.ndarray:
    if mode == "rgb":
        return frames["color"]["image"]
    depth = depth_colors(
        frames["depth"]["image"], camera["depth"]["depth_units_m"], max_depth_m
    )
    if mode == "depth":
        return depth
    if mode != "rgbd":
        raise ValueError("unknown preview mode")
    color = frames["color"]["image"]
    height, width = color.shape[:2]
    rows = np.linspace(0, depth.shape[0] - 1, height).astype(int)
    columns = np.linspace(0, depth.shape[1] - 1, width).astype(int)
    # Side-by-side viewpoints, not an uncalibrated RGB/depth overlay.
    return np.concatenate((color, depth[rows[:, None], columns]), axis=1)


def point_cloud(depth: np.ndarray, calibration: dict, stride: int, max_depth_m: float):
    """Deproject native rectified depth to depth-camera XYZ meters.

    D455 depth is rectified (Brown-Conrady coefficients all zero). Reject other
    distortion models rather than silently applying a pinhole approximation.
    Color is based on depth, so RGB extrinsics/projection are not required.
    """
    intr = calibration["intrinsics"]
    if intr.get("model") not in {"none", "brown_conrady", "inverse_brown_conrady"}:
        raise ValueError("point cloud requires a supported rectified depth model")
    if any(float(value) != 0 for value in intr.get("coeffs", [])):
        raise ValueError("point cloud requires rectified depth (zero distortion)")
    fx, fy = float(intr["fx"]), float(intr["fy"])
    if not np.isfinite([fx, fy, intr["ppx"], intr["ppy"]]).all() or min(fx, fy) <= 0:
        raise ValueError("invalid depth intrinsics")
    z = depth[::stride, ::stride].astype(np.float64) * calibration["depth_units_m"]
    v, u = np.mgrid[0 : depth.shape[0] : stride, 0 : depth.shape[1] : stride]
    valid = (z > 0) & (z <= max_depth_m)
    x = (u - intr["ppx"]) * z / fx
    y = (v - intr["ppy"]) * z / fy
    xyz = np.column_stack((x[valid], y[valid], z[valid])).astype("<f4")
    # Bound transfer/render cost even for high-resolution camera profiles.
    if len(xyz) > 20000:
        xyz = xyz[:: int(np.ceil(len(xyz) / 20000))]
    return xyz
