"""元件 Mask 生成 (融合版 §13)。

极性约定(全系统一致,配置 mask.polarity 记录):
- 255 = 该区域为真(pcb_mask: 板区; component_mask: 元件区;
  valid_inspection_mask: 可检测区)
- 0   = 屏蔽/无效

最终检测区 = pcb_mask AND NOT component_mask (§13)。
三个标准输出: pcb_mask.png / component_mask.png / valid_inspection_mask.png,
另有彩色可视化 visualize_color(绿=检测区, 红=元件屏蔽, 灰=板外)。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.roi.roi import Roi
from src.utils.logger import get_logger

logger = get_logger("component_mask")

MASK_ON = 255  # 极性: 255=区域为真 (§13, config mask.polarity)


class ComponentMaskGenerator:
    def __init__(self, width: int, height: int,
                 cfg: ConfigManager | None = None) -> None:
        self.width = width
        self.height = height
        # 极性读取自配置(当前仅支持 255 为真;配置不一致时拒绝静默继续)
        self.polarity = int(cfg.get("mask.polarity", 255)) if cfg else MASK_ON
        if self.polarity != MASK_ON:
            raise ValueError(
                f"当前实现约定 mask.polarity=255,配置为 {self.polarity}")

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
                center = np.array([roi.cx, roi.cy])
                pts = center + (pts - center) * (1 + extra_expand)
            cv2.fillPoly(mask, [pts.astype(np.int32)], MASK_ON)
            n += 1
        logger.info("component_mask 生成: %d 个元件区, 覆盖率 %.1f%%",
                    n, mask.mean() / 255 * 100)
        return mask

    def detection_mask(self, pcb_mask: np.ndarray,
                       component_mask: np.ndarray) -> np.ndarray:
        """最终检测区 = PCB 区域 AND NOT 元件区域。空掩膜报错(§13)。"""
        if pcb_mask.shape != component_mask.shape:
            raise ValueError(
                f"mask 尺寸不一致: pcb{pcb_mask.shape} vs comp{component_mask.shape}")
        det = cv2.bitwise_and(pcb_mask, cv2.bitwise_not(component_mask))
        coverage = det.mean() / 255 * 100
        if coverage <= 0:
            raise ValueError("有效检测 Mask 为空(元件掩膜覆盖全部板区,§13 检查)")
        logger.info("valid_inspection_mask: 有效检测区 %.1f%%", coverage)
        return det

    @staticmethod
    def visualize_color(pcb_mask: np.ndarray, component_mask: np.ndarray,
                        valid_mask: np.ndarray) -> np.ndarray:
        """彩色可视化: 绿=实际检测区, 红=元件屏蔽区, 灰=板外 (§13)。"""
        h, w = valid_mask.shape
        vis = np.full((h, w, 3), (90, 90, 90), np.uint8)   # 板外: 灰
        vis[pcb_mask == MASK_ON] = (60, 120, 60)            # 板区底色
        vis[valid_mask == MASK_ON] = (0, 200, 0)            # 检测区: 绿
        vis[component_mask == MASK_ON] = (0, 0, 200)        # 元件: 红
        return vis
