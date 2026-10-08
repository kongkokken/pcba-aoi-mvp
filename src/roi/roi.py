"""ROI 数据结构与生成 (任务书 §十二 / Phase 6)。

ROI = 旋转矩形: 中心 + 宽高 + 角度,用 cv2.boxPoints 得 4 顶点。
支持: 外扩(RoiExpand) / 越界检查与裁剪 / 绘制。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import Component
from src.utils.exceptions import ROIError


@dataclass
class Roi:
    """对齐图像中的一个旋转矩形 ROI。"""
    ref: str
    cx: float          # 中心 x (px)
    cy: float
    width: float       # px
    height: float
    angle: float       # 度
    inspect: bool = True
    mask: bool = True
    algorithm: str = "Geometry"
    expected_value: str = ""
    points: np.ndarray = field(default=None, repr=False)  # boxPoints 缓存

    def __post_init__(self) -> None:
        self.points = cv2.boxPoints(
            ((self.cx, self.cy), (self.width, self.height), self.angle))

    @property
    def bounding_rect(self) -> tuple[int, int, int, int]:
        """外接正矩形 (x, y, w, h)。"""
        x, y, w, h = cv2.boundingRect(self.points.astype(np.int32))
        return int(x), int(y), int(w), int(h)

    def clip_to_image(self, img_w: int, img_h: int) -> None:
        """顶点裁剪进图像范围(越界 ROI 不允许存在,裁剪后仍非法则抛错)。"""
        np.clip(self.points[:, 0], 0, img_w - 1, out=self.points[:, 0])
        np.clip(self.points[:, 1], 0, img_h - 1, out=self.points[:, 1])
        self.cx = float(np.clip(self.cx, 0, img_w - 1))
        self.cy = float(np.clip(self.cy, 0, img_h - 1))
        if cv2.contourArea(self.points.astype(np.float32)) < 1.0:
            raise ROIError(f"ROI {self.ref} 裁剪后面积过小(完全越界)")

    def contains(self, x: float, y: float) -> bool:
        return cv2.pointPolygonTest(self.points.astype(np.float32),
                                    (float(x), float(y)), False) >= 0

    def draw(self, image: np.ndarray, color: tuple[int, int, int] = (0, 255, 0),
             label: bool = True) -> np.ndarray:
        cv2.polylines(image, [self.points.astype(np.int32)], True, color, 1)
        if label:
            x, y, _, _ = self.bounding_rect
            cv2.putText(image, self.ref, (x, max(10, y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return image
