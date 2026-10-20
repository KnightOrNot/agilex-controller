"""Display transforms use real units and preserve authoritative RGB/Z16 input."""

import numpy as np
import pytest

from agilex_data_collection.preview import depth_colors, point_cloud, preview_image


def calibration():
    return {
        "depth_units_m": 0.001,
        "intrinsics": {
            "fx": 2.0,
            "fy": 4.0,
            "ppx": 1.0,
            "ppy": 0.5,
            "model": "brown_conrady",
            "coeffs": [0.0] * 5,
        },
    }


def test_cloud_deprojects_known_pixels_in_meters_and_preserves_input():
    depth = np.array([[0, 1000, 2000], [1000, 5000, 3000]], dtype=np.uint16)
    original = depth.copy()
    points = point_cloud(depth, calibration(), 1, 3.0)
    np.testing.assert_allclose(
        points, [[0, -0.125, 1], [1, -0.25, 2], [-0.5, 0.125, 1], [1.5, 0.375, 3]]
    )
    np.testing.assert_array_equal(depth, original)
    assert points.dtype == np.dtype("<f4")


@pytest.mark.parametrize("change", ["distortion", "model", "focal"])
def test_cloud_rejects_unsupported_or_invalid_calibration(change):
    settings = calibration()
    if change == "distortion":
        settings["intrinsics"]["coeffs"][0] = 0.01
    elif change == "model":
        settings["intrinsics"]["model"] = "unknown"
    else:
        settings["intrinsics"]["fx"] = 0
    with pytest.raises(ValueError):
        point_cloud(np.ones((2, 2), np.uint16), settings, 1, 3.0)


def test_cloud_bounds_transfer_size():
    points = point_cloud(np.full((480, 640), 1000, np.uint16), calibration(), 1, 3.0)
    assert len(points) <= 20000


def test_depth_preview_invalid_pixels_and_side_by_side_native_views():
    depth = np.array([[0, 1000], [4000, 2000]], np.uint16)
    original = depth.copy()
    color = np.full((4, 4, 3), 123, np.uint8)
    colors = depth_colors(depth, 0.001, 3)
    assert not colors[0, 0].any()
    assert not colors[1, 0].any()
    frames = {"color": {"image": color}, "depth": {"image": depth}}
    image = preview_image(frames, {"depth": calibration()}, "rgbd", 3)
    assert image.shape == (4, 8, 3)
    np.testing.assert_array_equal(image[:, :4], color)
    np.testing.assert_array_equal(depth, original)
