"""ROI 管理: 由元件表批量生成 ROI,越界/重叠/语义状态检查与可视化 (§12)。

状态规则:
- 元件坐标语义未确认(全局或元件级) -> UNCONFIGURED,不得用于最终定位
- 越界: reject_out_of_bounds=true 抛 ROIError;否则裁剪并标 REVIEW
- 两 ROI 重叠面积占比 > overlap_warn_percent -> 双方标 REVIEW 并记入摘要
"""
from __future__ import annotations

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import Component
from src.roi.roi import Roi
from src.utils.exceptions import ROIError
from src.utils.logger import get_logger

logger = get_logger("roi_manager")

# ROI 配置版本: ROI 生成策略/外扩语义变更时递增 (§14/§19)
ROI_CONFIG_VERSION = "1.1"


class RoiManager:
    def __init__(self, cfg: ConfigManager, transform: CoordinateTransform) -> None:
        self.cfg = cfg
        self.transform = transform
        self.default_expand = float(cfg.get("roi.default_expand", 0.2))
        self.reject_oob = bool(cfg.get("roi.reject_out_of_bounds", True))
        self.overlap_warn = float(cfg.get("roi.overlap_warn_percent", 30))
        # 全局坐标语义确认状态(§10.2): 未确认则全部 ROI 标 UNCONFIGURED
        self.coords_confirmed = bool(
            cfg.get("coordinate.coordinate_meaning_confirmed", False))
        # 标准图尺寸(ROI 不允许越出此范围)
        self.img_w = int(round(float(cfg.require("pcb.width_mm"))
                               * float(cfg.get("pcb.px_per_mm", 8))))
        self.img_h = int(round(float(cfg.require("pcb.height_mm"))
                               * float(cfg.get("pcb.px_per_mm", 8))))
        self.last_summary: dict = {}

    def create_roi(self, comp: Component) -> Roi:
        """单个元件 mm 坐标 -> 对齐图像旋转矩形 ROI(含外扩/边界/语义状态)。"""
        expand = comp.roi_expand if comp.roi_expand > 0 else self.default_expand
        cx, cy = self.transform.pcb_to_image(comp.x, comp.y)
        w = comp.width * self.transform.px_per_mm * (1 + expand)
        h = comp.height * self.transform.px_per_mm * (1 + expand)
        roi = Roi(ref=comp.ref, cx=cx, cy=cy, width=w, height=h,
                  angle=comp.angle, inspect=comp.inspect, mask=comp.mask,
                  algorithm=comp.algorithm, expected_value=comp.expected_value,
                  board_id=getattr(comp, "board_id", None) or "BOARD_1")
        # 语义门控(§10.2/§12.9): 未确认坐标的元件只能得到 UNCONFIGURED ROI
        comp_confirmed = getattr(comp, "coord_confirmed", True)
        if not (self.coords_confirmed and comp_confirmed):
            roi.status = "UNCONFIGURED"
            roi.message = "坐标语义未确认(CoordMeaningConfirmed=NO)"
        try:
            roi.clip_to_image(self.img_w, self.img_h)
        except ROIError:
            if self.reject_oob:
                raise
            # 配置允许时: 裁剪到图像范围并标 REVIEW
            np.clip(roi.points[:, 0], 0, self.img_w - 1, out=roi.points[:, 0])
            np.clip(roi.points[:, 1], 0, self.img_h - 1, out=roi.points[:, 1])
            roi.cx = float(np.clip(roi.cx, 0, self.img_w - 1))
            roi.cy = float(np.clip(roi.cy, 0, self.img_h - 1))
            if roi.status == "OK":
                roi.status = "REVIEW"
            roi.message = (roi.message + ";" if roi.message else "") \
                + "ROI 越界,已裁剪"
            logger.warning("ROI %s 越界已裁剪并标 REVIEW", roi.ref)
        return roi

    def create_rois(self, components: list[Component]) -> list[Roi]:
        """批量生成 + 重叠检查 + 质量摘要。"""
        rois: list[Roi] = []
        for comp in components:
            try:
                rois.append(self.create_roi(comp))
            except ROIError as e:
                logger.error("ROI 生成失败: %s", e)
                raise
        overlaps = self._check_overlaps(rois)
        self.last_summary = {
            "total": len(rois),
            "ok": sum(1 for r in rois if r.status == "OK"),
            "review": sum(1 for r in rois if r.status == "REVIEW"),
            "unconfigured": sum(1 for r in rois if r.status == "UNCONFIGURED"),
            "overlap_pairs": overlaps,
            "roi_config_version": ROI_CONFIG_VERSION,
            "coords_confirmed": self.coords_confirmed,
        }
        logger.info("ROI generated: %s", self.last_summary)
        return rois

    def _check_overlaps(self, rois: list[Roi]) -> list[dict]:
        """两两重叠检查(§12.3),超过阈值双方标 REVIEW。"""
        pairs: list[dict] = []
        for i in range(len(rois)):
            for j in range(i + 1, len(rois)):
                a, b = rois[i], rois[j]
                area_a = cv2.contourArea(a.points.astype(np.float32))
                if area_a <= 0:
                    continue
                try:
                    inter_area, _ = cv2.intersectConvexConvex(
                        a.points.astype(np.float32),
                        b.points.astype(np.float32))
                except cv2.error:
                    continue  # 非凸退化情况,跳过该对
                pct = float(inter_area) / area_a * 100
                if pct > self.overlap_warn:
                    pairs.append({"refs": [a.ref, b.ref],
                                  "overlap_percent": round(pct, 1)})
                    for r in (a, b):
                        if r.status == "OK":
                            r.status = "REVIEW"
                            r.message = f"与 {b.ref if r is a else a.ref} " \
                                        f"重叠 {pct:.0f}%"
                    logger.warning("ROI 重叠: %s", pairs[-1])
        return pairs

    def draw_all(self, image: np.ndarray, rois: list[Roi],
                 color: tuple[int, int, int] | None = None) -> np.ndarray:
        out = image.copy()
        for roi in rois:
            roi.draw(out, color)
        return out
