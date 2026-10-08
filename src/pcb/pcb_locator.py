"""PCB 板定位与有效区域 (任务书 §十八: 差分不作用于整个画面)。

拍摄图中: 通过颜色阈值找最大板轮廓(自动路径),失败时退化为
Mark 外扩四边形。标准图中: 板区域 = 全图减配置边距 -> pcb_mask。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger("pcb_locator")


class PcbLocator:
    """定位 PCB 区域,生成 pcb_mask。"""

    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.margin = int(cfg.get("pcb.board_margin_px", 4))

    def detect_board_quad(self, image: np.ndarray) -> np.ndarray | None:
        """在拍摄图中自动检测 PCB 外轮廓四边形(绿色基材阈值)。
        失败返回 None(调用方退化到 Mark 外扩)。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # 常见阻焊绿/蓝绿范围,适度放宽
        mask = cv2.inRange(hsv, np.array([35, 40, 30]), np.array([95, 255, 220]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        biggest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(biggest) < 0.05 * image.shape[0] * image.shape[1]:
            return None  # 面积太小,不可靠
        peri = cv2.arcLength(biggest, True)
        approx = cv2.approxPolyDP(biggest, 0.02 * peri, True)
        if len(approx) >= 4:
            rect = cv2.minAreaRect(biggest)
            return cv2.boxPoints(rect)
        return None

    def board_mask_aligned(self, width: int, height: int) -> np.ndarray:
        """标准图中的 PCB 有效区域掩膜: 全板减边距(255=有效)。"""
        mask = np.zeros((height, width), np.uint8)
        m = self.margin
        cv2.rectangle(mask, (m, m), (width - m - 1, height - m - 1), 255, -1)
        logger.debug("pcb_mask 生成: %dx%d, margin=%d", width, height, m)
        return mask
