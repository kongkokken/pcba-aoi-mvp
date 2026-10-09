"""拼板分割与单板管理 (融合版 §9.1)。

- 判定输入是单板还是拼板(config 驱动: single/grid/auto)
- grid 模式: 按 rows/cols/spacing/rotation 计算每个单板在拼板坐标系中的
  位置与编号(row_major: BOARD_1..N)
- auto 模式: 在拍摄图中检测多个板轮廓(验证钩子: 轮廓数/面积),
  不假定所有单板几何一致;失败退化 single 并警告
- 单板↔拼板坐标变换(原点偏移+旋转)
- 可视化: 板边界 + 编号

手动回退: config.yaml panel 组即为可持久化的人工配置 (§1 人工干预要求)。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger("panel")


@dataclass
class BoardPlacement:
    """一个单板在拼板坐标系中的放置。"""
    board_id: str
    origin_x_mm: float     # 单板原点在拼板坐标系中的位置
    origin_y_mm: float
    rotation_deg: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0

    def board_to_panel(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """单板坐标 -> 拼板坐标(旋转+平移)。"""
        t = np.deg2rad(self.rotation_deg)
        c, s = np.cos(t), np.sin(t)
        return (self.origin_x_mm + c * x_mm - s * y_mm,
                self.origin_y_mm + s * x_mm + c * y_mm)

    def panel_to_board(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """拼板坐标 -> 单板坐标(逆变换)。"""
        dx, dy = x_mm - self.origin_x_mm, y_mm - self.origin_y_mm
        t = np.deg2rad(self.rotation_deg)
        c, s = np.cos(t), np.sin(t)
        return (c * dx + s * dy, -s * dx + c * dy)


class PanelSegmenter:
    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.mode = str(cfg.get("panel.mode", "single"))
        self.rows = int(cfg.get("panel.rows", 1))
        self.cols = int(cfg.get("panel.cols", 1))
        self.spacing_x = float(cfg.get("panel.spacing_x_mm", 0.0))
        self.spacing_y = float(cfg.get("panel.spacing_y_mm", 0.0))
        self.rotation = float(cfg.get("panel.rotation_deg", 0.0))
        self.board_w = float(cfg.require("pcb.width_mm"))
        self.board_h = float(cfg.require("pcb.height_mm"))
        self.px_per_mm = float(cfg.get("pcb.px_per_mm", 8))

    # ---- 判定 -------------------------------------------------------------
    def is_panel(self) -> bool:
        """单板/拼板判定(配置驱动;auto 模式交由 detect_boards 验证)。"""
        return self.mode in ("grid", "auto") and self.rows * self.cols > 1

    def placements(self) -> list[BoardPlacement]:
        """按配置生成单板放置表。single/grid 均返回确定结果。"""
        if self.mode == "single" or self.rows * self.cols <= 1:
            return [BoardPlacement("BOARD_1", 0.0, 0.0, 0.0,
                                   self.board_w, self.board_h)]
        out: list[BoardPlacement] = []
        n = 1
        for r in range(self.rows):
            for c in range(self.cols):
                out.append(BoardPlacement(
                    board_id=f"BOARD_{n}",
                    origin_x_mm=c * (self.board_w + self.spacing_x),
                    origin_y_mm=r * (self.board_h + self.spacing_y),
                    rotation_deg=self.rotation,
                    width_mm=self.board_w, height_mm=self.board_h))
                n += 1
        logger.info("Panel segmentation: %s 模式, %d 单板 (%dx%d)",
                    self.mode, len(out), self.rows, self.cols)
        return out

    def detect_boards_auto(self, image: np.ndarray) -> list[np.ndarray]:
        """auto 模式验证钩子: 在拍摄图中检测多个板轮廓。
        返回轮廓四边形列表;<=1 个时调用方应退化 single 并记录警告。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([35, 40, 30]), np.array([95, 255, 220]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        quads: list[np.ndarray] = []
        min_area = 0.02 * image.shape[0] * image.shape[1]
        for cnt in contours:
            if cv2.contourArea(cnt) >= min_area:
                quads.append(cv2.boxPoints(cv2.minAreaRect(cnt)))
        if len(quads) <= 1:
            logger.warning("auto 拼板检测仅找到 %d 个板轮廓,退化为 single", len(quads))
        else:
            logger.info("auto 拼板检测: %d 个板轮廓(需人工核对几何一致性)", len(quads))
        return quads

    # ---- 拼板坐标 -----------------------------------------------------------
    def panel_size_mm(self) -> tuple[float, float]:
        ps = self.placements()
        w = max(p.origin_x_mm + p.width_mm for p in ps)
        h = max(p.origin_y_mm + p.height_mm for p in ps)
        return w, h

    def board_id_for_panel_point(self, x_mm: float, y_mm: float) -> str:
        """拼板坐标点所属单板编号(用于缺陷归属)。"""
        for p in self.placements():
            bx, by = p.panel_to_board(x_mm, y_mm)
            if 0 <= bx <= p.width_mm and 0 <= by <= p.height_mm:
                return p.board_id
        return "UNKNOWN"

    def board_id_for_image_point(self, x_px: float, y_px: float) -> str:
        """对齐图像像素点 -> 所属单板(单板/拼板共享 canonical mm 空间)。"""
        return self.board_id_for_panel_point(x_px / self.px_per_mm,
                                             y_px / self.px_per_mm)

    # ---- 可视化 ---------------------------------------------------------------
    def draw_boards(self, image: np.ndarray,
                    color: tuple[int, int, int] = (255, 180, 0)) -> np.ndarray:
        """在对齐图上绘制单板边界与编号。"""
        out = image.copy()
        for p in self.placements():
            corners_mm = [p.board_to_panel(0, 0),
                          p.board_to_panel(p.width_mm, 0),
                          p.board_to_panel(p.width_mm, p.height_mm),
                          p.board_to_panel(0, p.height_mm)]
            pts = (np.array(corners_mm) * self.px_per_mm).astype(np.int32)
            cv2.polylines(out, [pts], True, color, 2)
            cv2.putText(out, p.board_id, tuple(pts[0] + [6, 18]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        return out
