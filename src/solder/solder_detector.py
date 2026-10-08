"""疑似锡珠/锡渣检测 (任务书 §十六 / Phase 10)。

第一阶段统一定义 SuspectedSolderDefect —— 不声称能 100% 区分
锡珠/锡渣/灰尘/划痕/反光,仅按几何与灰度特征给出疑似分类与评分。

特征: area / bbox / aspect_ratio / circularity(4πA/P²) / mean_gray / score
过滤: min_area / max_area / min_circularity / max_aspect_ratio (config solder 段)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.difference.image_difference import DifferenceResult
from src.utils.logger import get_logger

logger = get_logger("solder_detector")


@dataclass
class SuspectedSolderDefect:
    """一个疑似焊接缺陷。"""
    type: str            # suspected_solder_ball / suspected_debris
    x: int
    y: int
    width: int
    height: int
    area: float
    aspect_ratio: float
    circularity: float
    mean_gray: float
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


class SolderDefectDetector:
    def __init__(self, cfg: ConfigManager) -> None:
        self.min_area = float(cfg.get("solder.min_area", 10))
        self.max_area = float(cfg.get("solder.max_area", 5000))
        self.min_circularity = float(cfg.get("solder.min_circularity", 0.2))
        self.max_aspect = float(cfg.get("solder.max_aspect_ratio", 8.0))
        # 圆度高于此值倾向判为锡珠(圆形),否则倾向锡渣(不规则)
        self.ball_circularity = 0.7

    def detect(self, diff_result: DifferenceResult,
               current_gray: np.ndarray | None = None) -> list[SuspectedSolderDefect]:
        """从差分结果的二值图中提取疑似缺陷(轮廓级特征 + 过滤)。"""
        binary = diff_result.binary
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        defects: list[SuspectedSolderDefect] = []
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if not (self.min_area <= area <= self.max_area):
                continue
            peri = float(cv2.arcLength(cnt, True))
            if peri < 1e-3:
                continue
            circularity = float(4 * np.pi * area / (peri * peri))  # 圆度 4πA/P²
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = max(w, h) / max(1, min(w, h))
            # 几何过滤
            if circularity < self.min_circularity or aspect > self.max_aspect:
                continue
            mean_gray = 0.0
            if current_gray is not None:
                mask = np.zeros(current_gray.shape, np.uint8)
                cv2.drawContours(mask, [cnt], -1, 255, -1)
                mean_gray = float(cv2.mean(current_gray, mask=mask)[0])
            score = self._score(area, circularity, mean_gray)
            dtype = ("suspected_solder_ball" if circularity >= self.ball_circularity
                     else "suspected_debris")
            defects.append(SuspectedSolderDefect(
                type=dtype, x=int(x), y=int(y), width=int(w), height=int(h),
                area=round(area, 1), aspect_ratio=round(aspect, 2),
                circularity=round(circularity, 3), mean_gray=round(mean_gray, 1),
                score=score))
        defects.sort(key=lambda d: -d.score)
        logger.info("Defect detected: %d 个疑似缺陷 %s", len(defects),
                    [(d.type, d.x, d.y, d.score) for d in defects])
        return defects

    def _score(self, area: float, circularity: float, mean_gray: float) -> float:
        """综合评分 0-1: 面积适中度 + 圆度 + 与基材的灰度差。"""
        # 面积: 在 [min_area, max_area] 内按对数归一
        a = np.clip(np.log10(max(area, 1)) / np.log10(self.max_area), 0, 1)
        gray_score = np.clip(abs(mean_gray - 90.0) / 120.0, 0, 1)  # 基材灰~90
        return round(float(0.4 * a + 0.3 * circularity + 0.3 * gray_score), 3)
