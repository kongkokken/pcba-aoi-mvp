"""摄像头模块测试 (任务书 §二十六.1): 基本逻辑,不依赖真实硬件。"""
from __future__ import annotations

import numpy as np
import pytest

from src.camera.camera import Camera
from src.camera.camera_manager import (find_working_camera,
                                       validate_frame)
from src.utils.exceptions import CameraError


class TestFrameValidation:
    def test_valid_frame(self):
        frame = np.full((100, 100, 3), 128, np.uint8)
        assert validate_frame(frame)

    def test_black_frame_invalid(self):
        assert not validate_frame(np.zeros((100, 100, 3), np.uint8))

    def test_none_frame_invalid(self):
        assert not validate_frame(None)

    def test_empty_frame_invalid(self):
        assert not validate_frame(np.zeros((0, 0, 3), np.uint8))


class TestCameraErrors:
    def test_open_invalid_index_raises(self):
        """不存在的摄像头 index 必须抛 CameraError,不允许崩溃。"""
        cam = Camera(index=97, warmup_frames=0)
        with pytest.raises(CameraError):
            cam.open()

    def test_read_before_open_raises(self):
        cam = Camera(index=0)
        with pytest.raises(CameraError):
            cam.read_frame()

    def test_release_idempotent(self):
        cam = Camera(index=0)
        cam.release()  # 未打开时 release 不应抛错
        cam.release()


class TestCameraSelection:
    def test_find_working_camera(self):
        results = [
            {"index": 0, "opened": False, "valid_frame": False},
            {"index": 1, "opened": True, "valid_frame": False},
            {"index": 2, "opened": True, "valid_frame": True},
        ]
        assert find_working_camera(results) == 2

    def test_no_working_camera(self):
        results = [{"index": 0, "opened": False, "valid_frame": False}]
        assert find_working_camera(results) is None
