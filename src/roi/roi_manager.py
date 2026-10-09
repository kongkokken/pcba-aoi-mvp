"""ROI 管理: 由 Excel 元件表批量生成 ROI,做越界检查与可视化。"""
from __future__ import annotations

import numpy as np

from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import Component
from src.roi.roi import Roi
from src.utils.exceptions import ROIError
from src.utils.logger import get_logger

logger = get_logger("roi_manager")

# ROI 配置版本: ROI 生成策略/外扩语义变更时递增 (§14/§19)
ROI_CONFIG_VERSION = "1.0"


class RoiManager:
    def __init__(self, cfg: ConfigManager, transform: CoordinateTransform) -> None:
        self.cfg = cfg
        self.transform = transform
        self.default_expand = float(cfg.get("roi.default_expand", 0.2))
        # 标准图尺寸(ROI 不允许越出此范围)
        self.img_w = int(round(float(cfg.require("pcb.width_mm"))
                               * float(cfg.get("pcb.px_per_mm", 8))))
        self.img_h = int(round(float(cfg.require("pcb.height_mm"))
                               * float(cfg.get("pcb.px_per_mm", 8))))

    def create_roi(self, comp: Component) -> Roi:
        """单个元件 mm 坐标 -> 对齐图像旋转矩形 ROI(含外扩与边界裁剪)。"""
        expand = comp.roi_expand if comp.roi_expand > 0 else self.default_expand
        cx, cy = self.transform.pcb_to_image(comp.x, comp.y)
        w = comp.width * self.transform.px_per_mm * (1 + expand)
        h = comp.height * self.transform.px_per_mm * (1 + expand)
        roi = Roi(ref=comp.ref, cx=cx, cy=cy, width=w, height=h,
                  angle=comp.angle, inspect=comp.inspect, mask=comp.mask,
                  algorithm=comp.algorithm, expected_value=comp.expected_value)
        roi.clip_to_image(self.img_w, self.img_h)
        return roi

    def create_rois(self, components: list[Component]) -> list[Roi]:
        """批量生成,任一 ROI 完全越界即抛 ROIError。"""
        rois: list[Roi] = []
        for comp in components:
            try:
                rois.append(self.create_roi(comp))
            except ROIError as e:
                logger.error("ROI 生成失败: %s", e)
                raise
        logger.info("ROI generated: %d 个 (%s)",
                    len(rois), [r.ref for r in rois])
        return rois

    def draw_all(self, image: np.ndarray, rois: list[Roi],
                 color: tuple[int, int, int] = (0, 255, 0)) -> np.ndarray:
        out = image.copy()
        for roi in rois:
            roi.draw(out, color)
        return out
