"""统一检测引擎 (任务书 §十九 / Phase 13 核心,Phase 11 先行供 GUI 调用)。

流程: capture -> Mark定位 -> 对齐 -> 坐标变换 -> ROI -> component mask
-> golden -> difference -> solder detector -> result
-> 保存 output/<YYYYMMDD_HHMMSS>/{original,aligned,mask,diff,overlay,result.json}
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import ExcelManager
from src.difference.image_difference import ImageDifferenceDetector
from src.golden.golden_manager import GoldenManager
from src.inspection.inspection_result import (DefectRecord, InspectionResult)
from src.mask.component_mask import ComponentMaskGenerator
from src.pcb.alignment import Aligner
from src.pcb.mark_detector import MarkDetector
from src.pcb.pcb_locator import PcbLocator
from src.roi.roi_manager import RoiManager
from src.solder.solder_detector import SolderDefectDetector
from src.utils.exceptions import AOIError
from src.utils.image_utils import ensure_dir, save_image, to_gray
from src.utils.logger import get_logger

logger = get_logger("inspection_engine")

_COLOR_PASS = (0, 200, 0)
_COLOR_NG = (0, 0, 230)
_COLOR_WARN = (0, 200, 230)


class InspectionEngine:
    """PCBA AOI 检测引擎(GUI 与 CLI 共用)。"""

    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.mark_detector = MarkDetector(cfg)
        self.aligner = Aligner(cfg)
        self.pcb_locator = PcbLocator(cfg)
        self.excel = ExcelManager(cfg)
        self.golden_mgr = GoldenManager(cfg)
        self.diff_detector = ImageDifferenceDetector(cfg)
        self.solder_detector = SolderDefectDetector(cfg)
        self.last_output_dir: Path | None = None

    # ---- 主流程 ---------------------------------------------------------
    def inspect(self, capture_image: np.ndarray,
                save_output: bool = True) -> InspectionResult:
        """对一张拍摄图执行完整检测。任何 AOIError 都转化为 ERROR 结果。"""
        result = InspectionResult.now(str(self.cfg.get("pcb.name", "DEMO_PCB")))
        try:
            self._run(capture_image, result, save_output)
        except AOIError as e:
            result.overall_status = "ERROR"
            result.message = str(e)
            logger.error("Inspection failed: %s", e)
        return result

    def _run(self, capture_image: np.ndarray, result: InspectionResult,
             save_output: bool) -> None:
        # 1. Mark 定位 + 对齐
        marks = self.mark_detector.detect(capture_image)
        H = self.aligner.compute_transform(marks)
        aligned = self.aligner.align_with_matrix(capture_image, H)
        result.alignment_status = "OK"

        # 2. 坐标系 + ROI + Mask
        transform = CoordinateTransform.from_config(self.cfg, homography=H)
        components = self.excel.load_components()
        rois = RoiManager(self.cfg, transform).create_rois(components)
        w, h = self.aligner.aligned_size
        mask_gen = ComponentMaskGenerator(w, h)
        component_mask = mask_gen.generate(rois)
        pcb_mask = self.pcb_locator.board_mask_aligned(w, h)
        detection_mask = mask_gen.detection_mask(pcb_mask, component_mask)

        # 3. Golden + 差分 + 缺陷检测
        golden, _ = self.golden_mgr.load_golden()
        diff = self.diff_detector.compute(golden, aligned,
                                          component_mask, pcb_mask)
        defects = self.solder_detector.detect(diff, to_gray(aligned))

        # 4. 结果汇总(元件级: 第一阶段元件区被 mask,全部记 PASS;
        #    缺陷级: 非元件区疑似锡珠/锡渣)
        inspected = [c for c in components if c.inspect]
        result.components_total = len(inspected)
        result.components_pass = len(inspected)
        result.components_ng = 0
        result.solder_defect_count = len(defects)
        result.defects = [
            DefectRecord(
                type=d.type, ref="", x=d.x, y=d.y, width=d.width,
                height=d.height, area=d.area, score=d.score,
                message=f"疑似{'锡珠' if 'ball' in d.type else '锡渣'} "
                        f"@({d.x},{d.y})px 圆度={d.circularity}")
            for d in defects
        ]
        result.overall_status = "NG" if defects else "PASS"

        # 5. 输出产物
        if save_output:
            out_dir = self._make_output_dir()
            result.output_dir = str(out_dir)
            overlay = self._draw_overlay(aligned, rois, defects,
                                         result.overall_status)
            save_image(capture_image, out_dir / "original.jpg")
            save_image(aligned, out_dir / "aligned.jpg")
            save_image(detection_mask, out_dir / "mask.png")
            save_image(diff.diff_image, out_dir / "diff.png")
            save_image(overlay, out_dir / "overlay.jpg")
            result.to_json(out_dir / "result.json")
            logger.info("Inspection finished: %s, defects=%d, output=%s",
                        result.overall_status, len(defects), out_dir)
        else:
            logger.info("Inspection finished: %s, defects=%d (未保存)",
                        result.overall_status, len(defects))

    # ---- 输出 -------------------------------------------------------------
    def _make_output_dir(self) -> Path:
        """output/<YYYYMMDD_HHMMSS>/;同秒冲突时追加 _2/_3 序号。"""
        base = self.cfg.output_dir() / datetime.now().strftime("%Y%m%d_%H%M%S")
        out = base
        n = 2
        while out.exists():
            out = base.with_name(f"{base.name}_{n}")
            n += 1
        ensure_dir(out)
        self.last_output_dir = out
        return out

    @staticmethod
    def _draw_overlay(aligned: np.ndarray, rois, defects,
                      status: str) -> np.ndarray:
        """overlay: 绿=PASS ROI,红=NG 缺陷框,顶部状态条。"""
        out = aligned.copy()
        for roi in rois:
            roi.draw(out, _COLOR_PASS)
        for d in defects:
            cv2.rectangle(out, (d.x - 3, d.y - 3),
                          (d.x + d.width + 3, d.y + d.height + 3), _COLOR_NG, 2)
            cv2.putText(out, d.type.replace("suspected_", ""),
                        (d.x, max(12, d.y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, _COLOR_NG, 1)
        color = _COLOR_PASS if status == "PASS" else _COLOR_NG
        cv2.rectangle(out, (0, 0), (out.shape[1], 26), (30, 30, 30), -1)
        cv2.putText(out, f"AOI RESULT: {status}  defects={len(defects)}",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        return out
