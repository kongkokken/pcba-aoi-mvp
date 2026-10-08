"""Mark 定位 (任务书 §八 / Phase 2)。

主路径: 模板匹配 (data/templates/mark_template_1..4.png, TM_CCOEFF_NORMED);
备用路径: HoughCircles + 亮斑几何筛选。

输出 4 个 Mark 中心(顺序 TL/TR/BR/BL),并做合法性检查:
数量 / 重复点 / 共线 / 坐标范围,不合法抛 MarkDetectionError。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.exceptions import MarkDetectionError
from src.utils.image_utils import load_image, to_gray
from src.utils.logger import get_logger

logger = get_logger("mark_detector")


@dataclass
class MarkPoint:
    """一个 Mark 检测结果。"""
    x: float
    y: float
    score: float
    method: str  # "template" / "hough"


class MarkDetector:
    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.template_threshold = float(cfg.get("mark.template_threshold", 0.8))
        self.min_dist = float(cfg.get("mark.min_dist_px", 40))
        self.min_area_quad = float(cfg.get("mark.min_collinearity_area", 50.0))
        self.expected_marks = len(cfg.get("pcb.marks_mm", [0, 0, 0, 0]))

    # ---- 模板管理 ------------------------------------------------------
    def load_templates(self, template_dir: Path | str | None = None) -> list[np.ndarray]:
        """加载 mark_template_*.png(灰度);无模板返回空列表。"""
        tdir = Path(template_dir) if template_dir else self.cfg.data_dir() / "templates"
        templates: list[np.ndarray] = []
        if tdir.exists():
            for p in sorted(tdir.glob("mark_template_*.png")):
                templates.append(to_gray(load_image(p)))
        return templates

    # ---- 主入口 --------------------------------------------------------
    def detect(self, image: np.ndarray,
               templates: list[np.ndarray] | None = None) -> np.ndarray:
        """检测 Mark,返回 Nx2 float64 数组(未排序)。失败抛 MarkDetectionError。"""
        if image is None or image.size == 0:
            raise MarkDetectionError("输入图像为空")
        gray = to_gray(image)

        if templates is None:
            templates = self.load_templates()
        points: list[MarkPoint] = []
        if templates:
            points = self._detect_by_template(gray, templates)
        if len(points) < self.expected_marks:
            logger.info("模板匹配仅得 %d 个 Mark,尝试 HoughCircles 备用路径",
                        len(points))
            hough_pts = self._detect_by_hough(gray)
            points = self._merge_points(points, hough_pts)

        # 亚像素精化: 对粗定位中心做亮斑质心计算,消除整像素抖动
        # (否则 ±1px 的匹配位置抖动会导致 warp 后高对比边缘出现差分重影)
        for p in points:
            p.x, p.y = self._refine_centroid(gray, p.x, p.y)

        self.validate(points, gray.shape)
        ordered = self.order_points(np.array([[p.x, p.y] for p in points]))
        logger.info("Mark detected: %d 个 -> %s", len(points),
                    np.round(ordered, 1).tolist())
        return ordered

    @staticmethod
    def _refine_centroid(gray: np.ndarray, x: float, y: float,
                         win: int = 25) -> tuple[float, float]:
        """在粗中心附近窗口内对亮斑(Mark 白圆)做质心精化,确定性亚像素。"""
        h, w = gray.shape
        half = win // 2
        x0 = int(np.clip(round(x) - half, 0, max(0, w - win)))
        y0 = int(np.clip(round(y) - half, 0, max(0, h - win)))
        patch = gray[y0:y0 + win, x0:x0 + win]
        if patch.size == 0:
            return x, y
        _, bw = cv2.threshold(patch, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        m = cv2.moments(bw, binaryImage=True)
        if m["m00"] < 10:  # 亮斑太小,放弃精化
            return x, y
        return x0 + m["m10"] / m["m00"], y0 + m["m01"] / m["m00"]

    # ---- 模板匹配 ------------------------------------------------------
    def _detect_by_template(self, gray: np.ndarray,
                            templates: list[np.ndarray]) -> list[MarkPoint]:
        """多模板匹配 + 非极大值抑制。"""
        candidates: list[MarkPoint] = []
        for tpl in templates:
            if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
                continue
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            # 取所有高于阈值的位置
            ys, xs = np.where(res >= self.template_threshold)
            for x, y in zip(xs, ys):
                candidates.append(MarkPoint(
                    float(x + tpl.shape[1] / 2), float(y + tpl.shape[0] / 2),
                    float(res[y, x]), "template"))
        return self._nms(candidates)

    def _nms(self, candidates: list[MarkPoint]) -> list[MarkPoint]:
        """按分数排序后做距离 NMS(合并同一 Mark 的重复响应)。"""
        candidates.sort(key=lambda p: -p.score)
        kept: list[MarkPoint] = []
        for c in candidates:
            if all((c.x - k.x) ** 2 + (c.y - k.y) ** 2 >= self.min_dist ** 2
                   for k in kept):
                kept.append(c)
        return kept

    # ---- Hough 备用 ----------------------------------------------------
    def _detect_by_hough(self, gray: np.ndarray) -> list[MarkPoint]:
        """HoughCircles 检测圆形 Mark,用亮度筛选(Mark 中心为亮圆)。"""
        blurred = cv2.GaussianBlur(gray, (5, 5), 1.5)
        r_est = max(6, int(self.cfg.get("mark.radius_px", 12)))
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=self.min_dist,
            param1=float(self.cfg.get("mark.hough_param1", 80)),
            param2=float(self.cfg.get("mark.hough_param2", 25)),
            minRadius=max(4, r_est - 8), maxRadius=r_est + 14)
        points: list[MarkPoint] = []
        if circles is not None:
            for x, y, r in np.round(circles[0]).astype(int):
                # Mark 中心应显著亮于外环: 用内外均值差打分
                inner = self._ring_mean(gray, x, y, 0, max(2, r - 3))
                outer = self._ring_mean(gray, x, y, r + 2, r + 6)
                if inner - outer > 25:
                    points.append(MarkPoint(float(x), float(y),
                                            float(inner - outer) / 255.0, "hough"))
        return points

    @staticmethod
    def _ring_mean(gray: np.ndarray, cx: int, cy: int,
                   r_in: int, r_out: int) -> float:
        """环形区域灰度均值(越界自动裁剪)。"""
        h, w = gray.shape
        mask = np.zeros((h, w), np.uint8)
        cv2.circle(mask, (cx, cy), max(1, r_out), 255, -1)
        if r_in > 0:
            cv2.circle(mask, (cx, cy), r_in, 0, -1)
        total = int(mask.sum() // 255)
        if total == 0:
            return 0.0
        return float(cv2.mean(gray, mask=mask)[0])

    @staticmethod
    def _merge_points(a: list[MarkPoint], b: list[MarkPoint]) -> list[MarkPoint]:
        """合并两路检测结果(同位置保留高分者)。"""
        merged = list(a)
        for p in b:
            if all((p.x - q.x) ** 2 + (p.y - q.y) ** 2 >= 20 ** 2 for q in merged):
                merged.append(p)
        return merged

    # ---- 合法性检查 -----------------------------------------------------
    def validate(self, points: list[MarkPoint], shape: tuple[int, int]) -> None:
        """数量/重复/共线/范围检查,任一失败抛 MarkDetectionError。"""
        n = len(points)
        if n < 3:
            raise MarkDetectionError(f"Mark 数量不足: {n} < 3")
        if n < self.expected_marks:
            logger.warning("Mark 数量 %d 少于期望 %d,将退化为仿射变换",
                           n, self.expected_marks)
        h, w = shape
        for i, p in enumerate(points):
            if not (0 <= p.x < w and 0 <= p.y < h):
                raise MarkDetectionError(f"Mark{i} 坐标越界: ({p.x:.1f},{p.y:.1f})")
            for j, q in enumerate(points[:i]):
                if (p.x - q.x) ** 2 + (p.y - q.y) ** 2 < self.min_dist ** 2:
                    raise MarkDetectionError(
                        f"Mark{i} 与 Mark{j} 重复: ({p.x:.1f},{p.y:.1f})")
        pts = np.array([[p.x, p.y] for p in points], dtype=np.float64)
        if len(pts) >= 4:
            area = cv2.contourArea(self.order_points(pts[:4]).astype(np.float32))
        else:
            area = 0.5 * abs(np.cross(pts[1] - pts[0], pts[2] - pts[0]))
        if area < self.min_area_quad:
            raise MarkDetectionError(f"Mark 接近共线(面积 {area:.1f} px²)")

    @staticmethod
    def order_points(points: np.ndarray) -> np.ndarray:
        """把点集排序为 TL, TR, BR, BL(和差法)。"""
        pts = np.asarray(points, dtype=np.float64)
        s = pts.sum(axis=1)
        d = pts[:, 0] - pts[:, 1]
        return np.array([pts[np.argmin(s)], pts[np.argmax(d)],
                         pts[np.argmax(s)], pts[np.argmin(d)]])
