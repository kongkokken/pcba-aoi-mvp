"""图像差分检测 (任务书 §十五/§十七 / Phase 9)。

流程: 尺寸检查 -> 光照预处理(高斯模糊/亮度归一化/可选CLAHE,配置化)
-> 灰度 -> absdiff -> threshold -> 形态学开/闭 -> 连通域
-> 面积/宽高过滤噪声 -> 异常列表。

注意: 不是简单的 diff>threshold 判 NG;异常需经 min_area/max_area/
bbox 宽高过滤后才成立。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.exceptions import InspectionError
from src.utils.image_utils import apply_clahe, normalize_brightness, to_gray
from src.utils.logger import get_logger

logger = get_logger("image_difference")


@dataclass
class DiffRegion:
    """一个差分异常区域。"""
    x: int
    y: int
    width: int
    height: int
    area: float
    mean_diff: float = 0.0


@dataclass
class DifferenceResult:
    diff_image: np.ndarray          # 可视化差分图(灰度)
    binary: np.ndarray              # 阈值+形态学后的二值图
    regions: list[DiffRegion] = field(default_factory=list)


class ImageDifferenceDetector:
    def __init__(self, cfg: ConfigManager) -> None:
        self.threshold = int(cfg.get("difference.threshold", 30))
        self.min_area = float(cfg.get("difference.min_area", 10))
        self.max_area = float(cfg.get("difference.max_area", 5000))
        self.blur = int(cfg.get("difference.blur", 3))
        self.morph = int(cfg.get("difference.morphology", 3))
        self.min_mean_diff = float(cfg.get("difference.min_mean_diff", 25))
        self.edge_exclusion_px = int(cfg.get("difference.edge_exclusion_px", 2))
        self.normalize = bool(cfg.get("illumination.normalize_brightness", True))
        self.use_clahe = bool(cfg.get("illumination.clahe", False))
        self.clahe_clip = float(cfg.get("illumination.clahe_clip", 2.0))
        self.clahe_grid = int(cfg.get("illumination.clahe_grid", 8))

    # ---- 光照预处理 -----------------------------------------------------
    def preprocess(self, image: np.ndarray,
                   target_mean: float | None = None) -> np.ndarray:
        """可配置光照预处理: CLAHE(可选) -> 灰度 -> 亮度归一化(可选) -> 高斯模糊。

        注意: 亮度归一化必须在灰度域进行,BGR 三通道均值与灰度均值不一致
        (绿色通道权重高),在彩色域归一会引入巨大偏差(实测自差均值 16)。
        """
        img = image
        if self.use_clahe:
            img = apply_clahe(img, self.clahe_clip, self.clahe_grid)
        gray = to_gray(img)
        if self.normalize and target_mean is not None:
            gray = normalize_brightness(gray, target_mean)
        k = max(1, self.blur) | 1  # 保证奇数核
        return cv2.GaussianBlur(gray, (k, k), 0)

    # ---- 差分 -----------------------------------------------------------
    def compute(self, golden: np.ndarray, current: np.ndarray,
                component_mask: np.ndarray | None = None,
                pcb_mask: np.ndarray | None = None) -> DifferenceResult:
        """golden vs current 差分,仅在 pcb_mask AND NOT component_mask 内生效。"""
        if golden is None or current is None or golden.size == 0 or current.size == 0:
            raise InspectionError("差分输入图像为空")
        if golden.shape[:2] != current.shape[:2]:
            raise InspectionError(
                f"图像尺寸不一致: golden{golden.shape[:2]} vs current{current.shape[:2]}")

        g = self.preprocess(golden)
        c = self.preprocess(current,
                            target_mean=float(to_gray(golden).mean()))
        diff = cv2.absdiff(to_gray(g), to_gray(c))

        _, binary = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)
        k = np.ones((max(1, self.morph), max(1, self.morph)), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)   # 去椒盐噪声
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)  # 连通断裂区域

        # 掩膜: 只在 PCB 非元件区域内检测
        if pcb_mask is not None:
            binary = cv2.bitwise_and(binary, pcb_mask)
        if component_mask is not None:
            binary = cv2.bitwise_and(binary, cv2.bitwise_not(component_mask))

        # 边缘排除: 仅在 golden 强边缘附近(膨胀 N px)不判定,
        # 消除亚像素对齐残差重影;current 独有边缘(=新异物)保留可检
        if self.edge_exclusion_px > 0:
            edges = cv2.Canny(g, 50, 150)
            dil = 2 * self.edge_exclusion_px + 1
            edges = cv2.dilate(edges, np.ones((dil, dil), np.uint8))
            binary = cv2.bitwise_and(binary, cv2.bitwise_not(edges))

        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary, connectivity=8)
        regions: list[DiffRegion] = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if not (self.min_area <= area <= self.max_area):
                continue  # 过滤过小噪声 / 过大光照变化
            # 区域自身平均差值: 过滤亚像素对齐残差造成的边缘重影
            region_mean = float(diff[labels == i].mean())
            if region_mean < self.min_mean_diff:
                continue
            regions.append(DiffRegion(x, y, w, h, float(area),
                                      round(region_mean, 2)))
        logger.info("Difference calculated: %d 个异常区域(过滤后)", len(regions))
        return DifferenceResult(diff_image=diff, binary=binary, regions=regions)
