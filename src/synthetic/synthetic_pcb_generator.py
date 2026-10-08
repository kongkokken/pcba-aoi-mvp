"""合成 PCB 测试图生成器 (任务书 §二十七 / §三十三)。

无真实 PCB 时,用本模块生成:
- canonical(标准)PCB 图: 恰好一块板,尺寸 = width_mm*px_per_mm
- capture(模拟拍摄)图: canonical 经透视变换贴到 1280x720 "桌面"上,
  含噪声与亮度变化,用于真实检验 Mark 定位 + Homography 对齐
- defect 变体: 圆形亮斑(模拟锡珠) / 不规则斑块(模拟锡渣),
  位于非元件区域,真实检验 mask + 差分逻辑
- 4 个 Mark 模板 (data/templates/mark_template_1..4.png)

关键约定: 元件几何与 SYNTHETIC_COMPONENTS 一致(Phase 5 Excel 由程序按此生成),
golden 与 defect 图使用完全相同的板内几何,仅缺陷不同。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.image_utils import ensure_dir, save_image
from src.utils.logger import get_logger

logger = get_logger("synthetic")

# 合成板上的元件表 (Ref, Type, X_mm, Y_mm, W_mm, H_mm, Angle_deg)
# 与 data/pcb_config.xlsx 保持一致(Excel 模板由程序按此表生成)
SYNTHETIC_COMPONENTS: list[tuple[str, str, float, float, float, float, float]] = [
    ("R101", "R", 25.4, 30.2, 4.0, 2.0, 0),
    ("R102", "R", 35.0, 50.0, 4.0, 2.0, 90),
    ("C101", "C", 30.2, 30.2, 3.0, 2.0, 90),
    ("C102", "C", 60.0, 55.0, 3.0, 2.0, 0),
    ("U101", "IC", 50.0, 40.0, 10.0, 8.0, 0),
    ("U102", "IC", 75.0, 25.0, 8.0, 8.0, 0),
]

# 缺陷定义: kind=ball(锡珠,圆形亮斑) / debris(锡渣,不规则斑块),位置避开元件区
SYNTHETIC_DEFECTS: list[dict] = [
    {"kind": "ball", "x_mm": 65.0, "y_mm": 48.0, "radius_px": 6},
    {"kind": "ball", "x_mm": 88.0, "y_mm": 40.0, "radius_px": 4},
    {"kind": "debris", "x_mm": 20.0, "y_mm": 55.0, "radius_px": 8},
]


@dataclass
class SyntheticSet:
    """一次生成的产物路径集合。"""
    golden: Path
    capture_ok: Path
    capture_ng: Path
    capture_shifted: Path
    templates: list[Path] = field(default_factory=list)


class SyntheticPcbGenerator:
    """按 config.yaml 的 pcb/mark/camera 段生成合成 PCB 图像。"""

    def __init__(self, cfg: ConfigManager, seed: int = 42) -> None:
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.px_per_mm: float = float(cfg.get("pcb.px_per_mm", 8))
        self.board_w = int(round(float(cfg.require("pcb.width_mm")) * self.px_per_mm))
        self.board_h = int(round(float(cfg.require("pcb.height_mm")) * self.px_per_mm))
        self.marks_mm = np.array(cfg.require("pcb.marks_mm"), dtype=np.float64)
        self.mark_r = int(cfg.get("mark.radius_px", 12))
        self.cam_w = int(cfg.get("camera.width", 1280))
        self.cam_h = int(cfg.get("camera.height", 720))

    # ---- 坐标换算 -----------------------------------------------------
    def mm2px(self, x_mm: float, y_mm: float) -> tuple[int, int]:
        return (int(round(x_mm * self.px_per_mm)),
                int(round(y_mm * self.px_per_mm)))

    # ---- 标准板面渲染 --------------------------------------------------
    def render_canonical(self, defects: list[dict] | None = None) -> np.ndarray:
        """渲染 800x560 标准 PCB 图(即 Golden 的几何基准)。"""
        img = np.zeros((self.board_h, self.board_w, 3), dtype=np.uint8)
        # 基材绿色 + 纹理噪声
        img[:] = (35, 105, 55)
        noise = self.rng.normal(0, 4, img.shape[:2]).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise[..., None], 0, 255).astype(np.uint8)

        self._draw_traces(img)
        self._draw_pads_and_components(img)
        self._draw_marks(img)
        if defects:
            self._draw_defects(img, defects)
        return img

    def _draw_traces(self, img: np.ndarray) -> None:
        """走线: 若干条深绿色折线。"""
        trace_color = (20, 80, 40)
        for _ in range(14):
            x1 = int(self.rng.integers(5, self.board_w - 5))
            y1 = int(self.rng.integers(5, self.board_h - 5))
            x2 = int(np.clip(x1 + self.rng.integers(-150, 150), 3, self.board_w - 3))
            y2 = int(np.clip(y1 + self.rng.integers(-150, 150), 3, self.board_h - 3))
            cv2.line(img, (x1, y1), (x2, y2), trace_color, 2)

    def _draw_pads_and_components(self, img: np.ndarray) -> None:
        """按元件表绘制焊盘 + 本体 + 丝印框 + 位号。"""
        for ref, ctype, x_mm, y_mm, w_mm, h_mm, ang in SYNTHETIC_COMPONENTS:
            cx, cy = self.mm2px(x_mm, y_mm)
            w, h = int(w_mm * self.px_per_mm), int(h_mm * self.px_per_mm)
            # 丝印框(略大于本体)
            sw, sh = w + 10, h + 10
            rect = ((cx, cy), (sw, sh), ang)
            box = cv2.boxPoints(rect).astype(np.int32)
            cv2.polylines(img, [box], True, (230, 230, 230), 1)
            # 焊盘: 本体两端各一个银色焊盘(仅 R/C)
            if ctype in ("R", "C"):
                self._draw_pad_pair(img, cx, cy, w, h, ang)
            # 元件本体
            body_color = {"R": (40, 40, 45), "C": (150, 140, 130),
                          "IC": (25, 25, 28)}.get(ctype, (60, 60, 60))
            body = ((cx, cy), (w, h), ang)
            bbox = cv2.boxPoints(body).astype(np.int32)
            cv2.fillPoly(img, [bbox], body_color)
            # IC 引脚 + 方向点
            if ctype == "IC":
                self._draw_ic_pins(img, cx, cy, w, h, ang)
            # 位号丝印
            cv2.putText(img, ref, (cx - w // 2, cy - sh // 2 - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (240, 240, 240), 1)

    def _draw_pad_pair(self, img: np.ndarray, cx: int, cy: int,
                       w: int, h: int, ang: float) -> None:
        """沿元件长轴两端绘制银色焊盘。"""
        rad = np.deg2rad(ang)
        dx, dy = np.cos(rad) * w / 2, -np.sin(rad) * w / 2
        for sign in (-1, 1):
            px = int(cx + sign * dx)
            py = int(cy + sign * dy)
            cv2.rectangle(img, (px - 5, py - 5), (px + 5, py + 5),
                          (190, 195, 200), -1)

    def _draw_ic_pins(self, img: np.ndarray, cx: int, cy: int,
                      w: int, h: int, ang: float) -> None:
        """IC 两侧引脚 + 1 脚方向标记。"""
        pins = max(2, h // 8)
        for side in (-1, 1):
            for i in range(pins):
                py = int(cy - h / 2 + (i + 0.5) * h / pins)
                px = int(cx + side * (w / 2 + 2))
                cv2.rectangle(img, (px - 3, py - 2), (px + 3, py + 2),
                              (185, 190, 195), -1)
        cv2.circle(img, (cx - w // 2 + 5, cy - h // 2 + 5), 2,
                   (200, 200, 200), -1)

    def _draw_marks(self, img: np.ndarray) -> None:
        """4 角 Mark: 黑色外环 + 白色实心圆 + 中心黑点(高对比,便于检测)。"""
        for x_mm, y_mm in self.marks_mm:
            cx, cy = self.mm2px(float(x_mm), float(y_mm))
            cv2.circle(img, (cx, cy), self.mark_r + 4, (10, 10, 10), -1)
            cv2.circle(img, (cx, cy), self.mark_r, (245, 245, 245), -1)
            cv2.circle(img, (cx, cy), 3, (10, 10, 10), -1)

    def _draw_defects(self, img: np.ndarray, defects: list[dict]) -> None:
        """在非元件区域绘制锡珠(圆形亮斑)/锡渣(不规则斑块)。"""
        for d in defects:
            cx, cy = self.mm2px(float(d["x_mm"]), float(d["y_mm"]))
            r = int(d["radius_px"])
            if d["kind"] == "ball":
                # 锡珠: 金属亮球,中心高光
                cv2.circle(img, (cx, cy), r, (200, 210, 220), -1)
                cv2.circle(img, (cx - r // 3, cy - r // 3), max(1, r // 3),
                           (240, 245, 250), -1)
            else:
                # 锡渣: 不规则多边形暗斑
                pts = []
                for k in range(7):
                    a = 2 * np.pi * k / 7
                    rr = r * (0.5 + self.rng.random() * 0.8)
                    pts.append((int(cx + rr * np.cos(a)), int(cy + rr * np.sin(a))))
                cv2.fillPoly(img, [np.array(pts, np.int32)], (120, 125, 115))

    # ---- 模拟拍摄 ------------------------------------------------------
    def render_capture(self, pose: str = "default",
                       defects: list[dict] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """把标准板经透视变换贴到 1280x720 画布上,模拟真实拍摄。

        pose: default / shifted(平移+旋转,验证 Homography 恢复能力)
        返回 (图像, 4 个 Mark 在图像中的像素坐标 TL,TR,BR,BL)。
        """
        canonical = self.render_canonical(defects)
        if pose == "shifted":
            quad = np.float32([[210, 130], [1090, 90], [1120, 600], [170, 640]])
        else:
            quad = np.float32([[150, 80], [1130, 60], [1150, 640], [130, 620]])
        src = np.float32([[0, 0], [self.board_w, 0],
                          [self.board_w, self.board_h], [0, self.board_h]])
        M = cv2.getPerspectiveTransform(src, quad)

        # 桌面背景: 深灰 + 噪声
        canvas = np.full((self.cam_h, self.cam_w, 3), (55, 55, 58), np.uint8)
        bg_noise = self.rng.normal(0, 3, canvas.shape[:2]).astype(np.int16)
        canvas = np.clip(canvas.astype(np.int16) + bg_noise[..., None], 0, 255).astype(np.uint8)

        warped = cv2.warpPerspective(canonical, M, (self.cam_w, self.cam_h))
        mask = cv2.warpPerspective(
            np.full((self.board_h, self.board_w), 255, np.uint8),
            M, (self.cam_w, self.cam_h))
        canvas[mask > 127] = warped[mask > 127]

        # 成像退化: 轻微模糊 + 噪声 + 亮度变化(模拟普通摄像头)
        canvas = cv2.GaussianBlur(canvas, (3, 3), 0)
        noise = self.rng.normal(0, 2.0, canvas.shape).astype(np.int16)
        canvas = np.clip(canvas.astype(np.int16) * 1.04 + noise + 3, 0, 255).astype(np.uint8)

        mark_pts = cv2.perspectiveTransform(
            (self.marks_mm * self.px_per_mm).reshape(-1, 1, 2).astype(np.float32), M
        ).reshape(-1, 2)
        return canvas, mark_pts

    # ---- 批量生成 ------------------------------------------------------
    def generate_all(self, out_dir: Path | str | None = None,
                     template_dir: Path | str | None = None) -> SyntheticSet:
        """生成 golden / ok / ng / shifted 四张图 + 4 个 Mark 模板。"""
        out = ensure_dir(out_dir or (self.cfg.data_dir() / "synthetic"))
        tpl_dir = ensure_dir(template_dir or (self.cfg.data_dir() / "templates"))

        golden_img = self.render_canonical()
        golden = save_image(golden_img, out / "golden.png")

        ok_img, ok_marks = self.render_capture("default")
        capture_ok = save_image(ok_img, out / "capture_ok.jpg")

        ng_img, _ = self.render_capture("default", defects=SYNTHETIC_DEFECTS)
        capture_ng = save_image(ng_img, out / "capture_ng.jpg")

        sh_img, _ = self.render_capture("shifted", defects=SYNTHETIC_DEFECTS)
        capture_shifted = save_image(sh_img, out / "capture_shifted.jpg")

        # 从 ok 图裁剪 4 个 Mark 模板(带边距)
        templates: list[Path] = []
        half = self.mark_r + 10
        for i, (mx, my) in enumerate(ok_marks, start=1):
            x0, y0 = int(mx) - half, int(my) - half
            tpl = ok_img[max(0, y0):y0 + 2 * half, max(0, x0):x0 + 2 * half]
            templates.append(save_image(tpl, tpl_dir / f"mark_template_{i}.png"))

        logger.info("合成图像集已生成: %s", out)
        return SyntheticSet(golden, capture_ok, capture_ng, capture_shifted, templates)


if __name__ == "__main__":
    from src.utils.logger import setup_logging
    setup_logging()
    gen = SyntheticPcbGenerator(ConfigManager())
    result = gen.generate_all()
    print(result)
