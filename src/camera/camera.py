"""摄像头封装 (任务书 Phase 1)。

Camera: 打开 / 读取帧 / 拍照保存 / 释放,全部失败路径抛 CameraError。
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from src.utils.exceptions import CameraError
from src.utils.image_utils import ensure_dir, save_image
from src.utils.logger import get_logger

logger = get_logger("camera")

# OpenCV 后端映射
_BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


class Camera:
    """单个摄像头会话。支持上下文管理器协议。"""

    def __init__(
        self,
        index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        backend: str = "dshow",
        warmup_frames: int = 8,
    ) -> None:
        self.index = index
        self.req_width = width
        self.req_height = height
        self.req_fps = fps
        self.backend = backend
        self.warmup_frames = warmup_frames
        self._cap: cv2.VideoCapture | None = None

    # ---- 生命周期 ----------------------------------------------------
    def open(self) -> None:
        """打开摄像头并验证能读到有效帧,失败抛 CameraError。"""
        api = _BACKENDS.get(self.backend, cv2.CAP_ANY)
        cap = cv2.VideoCapture(self.index, api)
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"摄像头 {self.index} 无法打开 (backend={self.backend})")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req_height)
        cap.set(cv2.CAP_PROP_FPS, self.req_fps)
        self._cap = cap

        # 预热: 丢弃前几帧等待自动曝光稳定
        for _ in range(max(0, self.warmup_frames)):
            cap.read()
            time.sleep(0.02)

        frame = self.read_frame()
        if frame is None or frame.size == 0 or float(frame.mean()) < 1.0:
            raise CameraError(f"摄像头 {self.index} 返回无效帧(黑帧/空帧)")
        logger.info(
            "Camera opened: index=%d, resolution=%dx%d (requested %dx%d), fps=%.1f",
            self.index, self.width, self.height,
            self.req_width, self.req_height, self.fps,
        )

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera released: index=%d", self.index)

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # ---- 状态 --------------------------------------------------------
    def _require_open(self) -> cv2.VideoCapture:
        if self._cap is None or not self._cap.isOpened():
            raise CameraError("摄像头未打开,请先调用 open()")
        return self._cap

    @property
    def width(self) -> int:
        return int(self._require_open().get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def height(self) -> int:
        return int(self._require_open().get(cv2.CAP_PROP_FRAME_HEIGHT))

    @property
    def fps(self) -> float:
        return float(self._require_open().get(cv2.CAP_PROP_FPS))

    # ---- 取流 --------------------------------------------------------
    def read_frame(self) -> np.ndarray:
        """读取一帧;失败抛 CameraError。"""
        cap = self._require_open()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise CameraError(f"摄像头 {self.index} 读取帧失败")
        logger.debug("Frame received: %dx%d", frame.shape[1], frame.shape[0])
        return frame

    def measure_fps(self, n_frames: int = 30) -> float:
        """实测 FPS(读取 n 帧计时)。"""
        cap = self._require_open()
        start = time.perf_counter()
        count = 0
        for _ in range(n_frames):
            ok, _ = cap.read()
            if ok:
                count += 1
        elapsed = time.perf_counter() - start
        return count / elapsed if elapsed > 0 else 0.0

    def capture_to(self, path: Path | str) -> Path:
        """拍照并保存到指定路径。"""
        frame = self.read_frame()
        ensure_dir(Path(path).parent)
        saved = save_image(frame, path)
        logger.info("拍照已保存: %s (%dx%d)", saved, frame.shape[1], frame.shape[0])
        return saved
