"""坐标转换测试 (任务书 §二十六.2): PCB->Image->PCB 回环误差 <= 0.1 mm。"""
from __future__ import annotations

import numpy as np
import pytest

from src.coordinate.coordinate_transform import CoordinateTransform

ROUNDTRIP_TOLERANCE_MM = 0.1  # 任务书规定默认允许误差

TEST_POINTS = np.array([
    [0.0, 0.0], [6.0, 6.0], [25.4, 30.2], [50.0, 40.0],
    [94.0, 64.0], [100.0, 70.0], [0.001, 69.999], [33.333, 55.555],
])


class TestRoundTrip:
    def test_identity_roundtrip(self):
        ct = CoordinateTransform(px_per_mm=8.0)
        for x, y in TEST_POINTS:
            px, py = ct.pcb_to_image(x, y)
            rx, ry = ct.image_to_pcb(px, py)
            assert abs(rx - x) <= ROUNDTRIP_TOLERANCE_MM
            assert abs(ry - y) <= ROUNDTRIP_TOLERANCE_MM

    def test_roundtrip_with_origin_and_rotation(self):
        ct = CoordinateTransform(px_per_mm=8.0, origin_px=(13.7, -4.2),
                                 rotation_deg=3.5)
        for x, y in TEST_POINTS:
            px, py = ct.pcb_to_image(x, y)
            rx, ry = ct.image_to_pcb(px, py)
            assert abs(rx - x) <= ROUNDTRIP_TOLERANCE_MM
            assert abs(ry - y) <= ROUNDTRIP_TOLERANCE_MM

    def test_batch_matches_single(self):
        ct = CoordinateTransform(px_per_mm=8.0, rotation_deg=-2.0)
        batch = ct.pcb_to_image_batch(TEST_POINTS)
        single = np.array([ct.pcb_to_image(x, y) for x, y in TEST_POINTS])
        assert np.allclose(batch, single)

    def test_scale_correctness(self):
        ct = CoordinateTransform(px_per_mm=8.0)
        px, py = ct.pcb_to_image(10.0, 5.0)
        assert (px, py) == (80.0, 40.0)

    def test_camera_to_pcb_requires_homography(self):
        ct = CoordinateTransform(px_per_mm=8.0)
        with pytest.raises(ValueError):
            ct.camera_to_pcb(100.0, 100.0)
