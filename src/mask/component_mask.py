"""元件 Mask 生成 (任务书 §十三 / Phase 7)。

- component_mask: 所有 Mask=1 的元件 ROI 填充区(默认按 RoiExpand 外扩)
- detection_mask: pcb_mask AND NOT component_mask
  —— 只有 PCB 上的非元件区域进入锡珠/锡渣差分检测
"""
from __future__ import annotations

import cv2
import numpy as np

from src.roi.roi import Roi
from src.utils.logger import get_logger

logger = get_logger("component_mask")


class ComponentMaskGenerator:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def generate(self, rois: list[Roi],
                 extra_expand: float = 0.0) -> np.ndarray:
        """生成元件掩膜 (255=元件区)。extra_expand: 在 ROI 基础上再外扩比例。"""
        mask = np.zeros((self.height, self.width), np.uint8)
        n = 0
        for roi in rois:
            if not roi.mask:
                continue
            pts = roi.points.copy()
            if extra_expand > 0:
                # 以中心为基准等比外扩顶点
                center = np.array([roi.cx, roi.cy])
                pts = center + (pts - center) * (1 + extra_expand)
            cv2.fillPoly(mask, [pts.astype(np.int32)], 255)
            n += 1
        logger.info("component_mask 生成: %d 个元件区, 覆盖率 %.1f%%",
                    n, mask.mean() / 255 * 100)
        return mask

    def detection_mask(self, pcb_mask: np.ndarray,
                       component_mask: np.ndarray) -> np.ndarray:
        """最终检测区 = PCB 区域 AND NOT 元件区域。"""
        if pcb_mask.shape != component_mask.shape:
            raise ValueError(
                f"mask 尺寸不一致: pcb{pcb_mask.shape} vs comp{component_mask.shape}")
        det = cv2.bitwise_and(pcb_mask, cv2.bitwise_not(component_mask))
        logger.info("detection_mask: 有效检测区 %.1f%%", det.mean() / 255 * 100)
        return det
