"""摄像头管理: 枚举探测可用摄像头,按配置创建 Camera (任务书 §三)。"""
from __future__ import annotations

import cv2
import numpy as np

from src.camera.camera import Camera, _BACKENDS
from src.config.config_manager import ConfigManager
from src.utils.exceptions import CameraError
from src.utils.logger import get_logger

logger = get_logger("camera_manager")

PROBE_INDICES = (0, 1, 2, 3)  # 任务书要求的探测范围


def probe_cameras(indices: tuple[int, ...] = PROBE_INDICES,
                  backend: str = "dshow") -> list[dict]:
    """逐个探测摄像头,返回 [{index, opened, width, height, valid_frame}]。"""
    api = _BACKENDS.get(backend, cv2.CAP_ANY)
    results: list[dict] = []
    for idx in indices:
        info: dict = {"index": idx, "opened": False, "width": 0,
                      "height": 0, "valid_frame": False}
        cap = cv2.VideoCapture(idx, api)
        try:
            if cap.isOpened():
                info["opened"] = True
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    info["valid_frame"] = bool(frame.mean() > 1.0)
                    info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()
        results.append(info)
        logger.info("探测摄像头 %d: %s", idx, info)
    return results


def find_working_camera(results: list[dict]) -> int | None:
    """从探测结果中选出第一个能读到有效帧的 index。"""
    for info in results:
        if info["opened"] and info["valid_frame"]:
            return int(info["index"])
    return None


def create_camera_from_config(cfg: ConfigManager,
                              index: int | None = None) -> Camera:
    """按 config.yaml 的 camera 段创建 Camera(尚未 open)。"""
    return Camera(
        index=index if index is not None else int(cfg.get("camera.index", 0)),
        width=int(cfg.get("camera.width", 1280)),
        height=int(cfg.get("camera.height", 720)),
        fps=int(cfg.get("camera.fps", 30)),
        backend=str(cfg.get("camera.backend", "dshow")),
        warmup_frames=int(cfg.get("camera.warmup_frames", 8)),
    )


def open_first_working(cfg: ConfigManager) -> Camera:
    """探测并打开第一个可用摄像头;全部失败抛 CameraError。"""
    results = probe_cameras(backend=str(cfg.get("camera.backend", "dshow")))
    idx = find_working_camera(results)
    if idx is None:
        raise CameraError(f"未发现可用摄像头 (探测: {PROBE_INDICES})")
    cam = create_camera_from_config(cfg, index=idx)
    cam.open()
    return cam


def validate_frame(frame: np.ndarray | None) -> bool:
    """帧有效性检查(供单元测试与流程复用)。"""
    return frame is not None and frame.size > 0 and float(frame.mean()) > 1.0
