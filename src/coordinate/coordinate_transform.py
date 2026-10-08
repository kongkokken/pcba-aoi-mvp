"""PCB 坐标系统 (任务书 §十 / Phase 4)。

统一约定:
- PCB 坐标系: 单位 mm,原点在板左上角,X 向右,Y 向下
- 图像坐标系: 对齐后标准图的像素坐标

支持: 原点偏移 + 比例尺(px/mm) + 旋转(度) + 可选 Homography(拍摄图→标准图)。
核心保证: pcb -> image -> pcb 回环误差 <= 0.1 mm(Phase 12 有单元测试)。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.config.config_manager import ConfigManager


class CoordinateTransform:
    """PCB mm 坐标与对齐图像像素坐标的双向转换。"""

    def __init__(self, px_per_mm: float, origin_px: tuple[float, float] = (0.0, 0.0),
                 rotation_deg: float = 0.0,
                 homography: np.ndarray | None = None) -> None:
        self.px_per_mm = float(px_per_mm)
        self.origin = np.array(origin_px, dtype=np.float64)
        self.rotation = float(rotation_deg)
        self.homography = homography  # 可选: 拍摄图像素 -> 标准图像素

        theta = np.deg2rad(self.rotation)
        # 旋转矩阵 (PCB->图像方向)
        self._R = np.array([[np.cos(theta), -np.sin(theta)],
                            [np.sin(theta), np.cos(theta)]])
        self._R_inv = self._R.T  # 正交矩阵转置即逆
        # Homography 逆(用于 image->pcb 完整链路)
        self._H_inv = (np.linalg.inv(homography)
                       if homography is not None else None)

    @classmethod
    def from_config(cls, cfg: ConfigManager,
                    homography: np.ndarray | None = None) -> "CoordinateTransform":
        return cls(px_per_mm=float(cfg.get("pcb.px_per_mm", 8)),
                   homography=homography)

    # ---- PCB -> 图像 ---------------------------------------------------
    def pcb_to_image(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """PCB mm -> 标准图像素(含原点/比例/旋转)。"""
        pt = np.array([x_mm, y_mm]) * self.px_per_mm
        px = self._R @ pt + self.origin
        return float(px[0]), float(px[1])

    def pcb_to_image_batch(self, points_mm: np.ndarray) -> np.ndarray:
        pts = np.asarray(points_mm, dtype=np.float64) * self.px_per_mm
        return pts @ self._R.T + self.origin

    # ---- 图像 -> PCB ---------------------------------------------------
    def image_to_pcb(self, x_px: float, y_px: float) -> tuple[float, float]:
        pt = np.array([x_px, y_px]) - self.origin
        mm = self._R_inv @ pt / self.px_per_mm
        return float(mm[0]), float(mm[1])

    def image_to_pcb_batch(self, points_px: np.ndarray) -> np.ndarray:
        pts = np.asarray(points_px, dtype=np.float64) - self.origin
        return (pts @ self._R_inv.T) / self.px_per_mm

    # ---- 拍摄图 -> 标准图(可选 Homography) -----------------------------
    def camera_to_aligned(self, x_px: float, y_px: float) -> tuple[float, float]:
        if self.homography is None:
            raise ValueError("未提供 Homography,无法做拍摄图->标准图转换")
        src = np.array([[[x_px, y_px]]], dtype=np.float64)
        dst = cv2.perspectiveTransform(src, self.homography)[0, 0]
        return float(dst[0]), float(dst[1])

    def camera_to_pcb(self, x_px: float, y_px: float) -> tuple[float, float]:
        """拍摄图像素 -> 标准图像素 -> PCB mm(完整链路)。"""
        ax, ay = self.camera_to_aligned(x_px, y_px)
        return self.image_to_pcb(ax, ay)
