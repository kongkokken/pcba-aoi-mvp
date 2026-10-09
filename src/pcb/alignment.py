"""PCB 图像对齐 (任务书 §九 / Phase 3)。

4 点: cv2.findHomography + warpPerspective;
3 点: 退化为 cv2.getAffineTransform。
对齐目标 = 标准坐标图 (width_mm*px_per_mm, height_mm*px_per_mm)。
所有失败路径抛 AlignmentError,绝不崩溃。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.exceptions import AlignmentError
from src.utils.logger import get_logger

logger = get_logger("alignment")


class Aligner:
    """由 Mark 像素坐标计算变换并把拍摄图对齐到标准坐标图。"""

    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.px_per_mm = float(cfg.get("pcb.px_per_mm", 8))
        self.board_w = int(round(float(cfg.require("pcb.width_mm")) * self.px_per_mm))
        self.board_h = int(round(float(cfg.require("pcb.height_mm")) * self.px_per_mm))
        marks_mm = np.array(cfg.require("pcb.marks_mm"), dtype=np.float64)
        self.canonical_marks = marks_mm * self.px_per_mm  # TL,TR,BR,BL (px)
        self.method = str(cfg.get("alignment.method", "homography"))
        self.reproj_max = float(cfg.get("alignment.reproj_error_max", 10.0))

    @property
    def aligned_size(self) -> tuple[int, int]:
        """(宽, 高) 标准图尺寸。"""
        return (self.board_w, self.board_h)

    # ---- 变换计算 ------------------------------------------------------
    def compute_transform(self, detected_marks: np.ndarray) -> np.ndarray:
        """detected_marks: Nx2 (TL,TR,BR,BL 顺序, N>=3)。返回 3x3 单应矩阵。"""
        src = np.asarray(detected_marks, dtype=np.float64)
        if src.ndim != 2 or src.shape[1] != 2 or len(src) < 3:
            raise AlignmentError(f"Mark 点数量/维度非法: {src.shape}")
        dst = self.canonical_marks[:len(src)]

        if len(src) >= 4 and self.method == "homography":
            # >4 点且配置启用时使用 RANSAC 鲁棒估计 (§9.3);恰好 4 点用精确解
            use_ransac = bool(self.cfg.get("alignment.use_ransac", True))
            method = cv2.RANSAC if (use_ransac and len(src) > 4) else 0
            H, mask = cv2.findHomography(src, dst, method=method)
            if H is None:
                raise AlignmentError("findHomography 返回 None(点可能共线/退化)")
            self._validate(H, src, dst)
            logger.info("Homography calculated (4点), 重投影误差已校验")
            return H

        # 3 点仿射退化路径
        M = cv2.getAffineTransform(src[:3].astype(np.float32),
                                   dst[:3].astype(np.float32))
        H = np.eye(3)
        H[:2, :] = M
        self._validate(H, src[:3], dst[:3])
        logger.info("Affine transform calculated (3点退化路径)")
        return H

    def _validate(self, H: np.ndarray, src: np.ndarray, dst: np.ndarray) -> None:
        """Homography 有效性: 有限值 / 非奇异 / 重投影误差。"""
        if not np.all(np.isfinite(H)):
            raise AlignmentError("变换矩阵含 NaN/Inf")
        if abs(np.linalg.det(H)) < 1e-8:
            raise AlignmentError("变换矩阵接近奇异")
        proj = cv2.perspectiveTransform(
            src.reshape(-1, 1, 2).astype(np.float32), H.astype(np.float64)
        ).reshape(-1, 2)
        err = np.linalg.norm(proj - dst, axis=1)
        if float(err.max()) > self.reproj_max:
            raise AlignmentError(
                f"重投影误差过大: max={err.max():.2f}px > {self.reproj_max}px")

    # ---- 对齐 ----------------------------------------------------------
    def align(self, image: np.ndarray, detected_marks: np.ndarray) -> np.ndarray:
        """拍摄图 -> 标准坐标图 (board_w x board_h)。"""
        if image is None or image.size == 0:
            raise AlignmentError("输入图像为空")
        H = self.compute_transform(detected_marks)
        aligned = cv2.warpPerspective(image, H, (self.board_w, self.board_h))
        logger.info("对齐完成: %dx%d -> %dx%d",
                    image.shape[1], image.shape[0], self.board_w, self.board_h)
        return aligned

    def align_with_matrix(self, image: np.ndarray, H: np.ndarray) -> np.ndarray:
        """已有变换矩阵时直接对齐(供 Golden 创建流程复用)。"""
        return cv2.warpPerspective(image, H, (self.board_w, self.board_h))
