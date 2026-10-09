"""统一检测引擎 (融合版 §18/§19)。

流程: 采图/载入 -> 标定参数校验 -> 畸变校正 -> Mark 定位 -> 对齐
-> 坐标变换 -> ROI -> Mask -> Golden -> 差分 -> 缺陷候选 -> 判定 -> 保存。

判定门控(§18/§27.5):
- decision.require_valid_calibration: 标定无效时不得输出 PASS
  (identity 豁免仅当 source="synthetic" 且参数带文档化理由时视为可接受)
- decision.require_valid_coordinate_mapping: 坐标语义未确认时不得 PASS
- Golden 与当前条件不一致 -> REVIEW,绝不静默差分
不确定时按 decision.uncertain_status(默认 REVIEW) 判定。

产物(§19): original/undistorted/aligned/roi_overlay/pcb_mask/
component_mask/valid_inspection_mask/diff/overlay/result.json/config_snapshot。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.calibration.calibration import CalibrationManager
from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import (MAPPING_VERSION,
                                                 CoordinateTransform)
from src.coordinate.excel_manager import ExcelManager
from src.difference.image_difference import ImageDifferenceDetector
from src.golden.golden_manager import GoldenManager
from src.inspection.inspection_result import (DefectRecord, InspectionResult)
from src.mask.component_mask import ComponentMaskGenerator
from src.panel.panel_segmenter import PanelSegmenter
from src.pcb.alignment import Aligner, leave_one_out_error
from src.pcb.mark_detector import MarkDetector
from src.pcb.pcb_locator import PcbLocator
from src.roi.roi_manager import ROI_CONFIG_VERSION, RoiManager
from src.solder.solder_detector import SolderDefectDetector
from src.utils.exceptions import AOIError, CalibrationError
from src.utils.image_utils import ensure_dir, save_image, to_gray
from src.utils.logger import get_logger

logger = get_logger("inspection_engine")

_COLOR_PASS = (0, 200, 0)
_COLOR_NG = (0, 0, 230)
_COLOR_REVIEW = (0, 200, 230)   # 黄: WARNING/REVIEW (§19)


class InspectionEngine:
    """PCBA AOI 检测引擎(GUI / CLI / Streamlit 共用)。"""

    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.calibration = CalibrationManager(cfg)
        self.mark_detector = MarkDetector(cfg)
        self.aligner = Aligner(cfg)
        self.pcb_locator = PcbLocator(cfg)
        self.excel = ExcelManager(cfg)
        self.golden_mgr = GoldenManager(cfg)
        self.diff_detector = ImageDifferenceDetector(cfg)
        self.solder_detector = SolderDefectDetector(cfg)
        self.panel = PanelSegmenter(cfg)
        self.last_output_dir: Path | None = None
        self.last_roi_summary: dict = {}
        self.last_reproj_loo: tuple[float, float] = (0.0, 0.0)

    # ---- 标定检查 (§8/§18) ---------------------------------------------
    def _check_calibration(self, image_size: tuple[int, int],
                           source: str) -> tuple[str, dict | None, bool]:
        """返回 (状态字符串, 参数或None, 是否满足放行门控)。"""
        if not bool(self.cfg.get("calibration.enabled", True)):
            reason = "calibration.enabled=false(配置显式关闭)"
            logger.warning("跳过畸变校正: %s", reason)
            return f"disabled", None, False
        try:
            params = self.calibration.load_params(image_size)
        except CalibrationError as e:
            logger.warning("标定参数不可用: %s —— 跳过畸变校正", e)
            return f"invalid:{e}", None, False
        for w in self.calibration.check_condition_change(params, image_size):
            logger.warning("标定条件提醒: %s", w)
        if params.get("is_identity"):
            # identity 豁免: 仅合成来源可接受(§27.5 不得对真实相机放行)
            ok = source == "synthetic"
            status = "identity_skip"
            logger.info("使用 identity 标定豁免(%s), source=%s, 放行门控=%s",
                        params.get("notes", ""), source, ok)
            return status, params, ok
        return "valid", params, True

    # ---- 主流程 ---------------------------------------------------------
    def inspect(self, capture_image: np.ndarray, save_output: bool = True,
                source: str = "generic") -> InspectionResult:
        """对一张拍摄图执行完整检测。source: synthetic/camera/upload/generic。
        任何 AOIError 都转化为 ERROR 结果,不崩溃。"""
        result = InspectionResult.now(str(self.cfg.get("pcb.name", "DEMO_PCB")))
        try:
            self._run(capture_image, result, save_output, source)
        except AOIError as e:
            result.overall_status = "ERROR"
            result.message = str(e)
            logger.error("Inspection failed: %s", e)
        return result

    def _run(self, capture_image: np.ndarray, result: InspectionResult,
             save_output: bool, source: str) -> None:
        if capture_image is None or capture_image.size == 0:
            from src.utils.exceptions import InspectionError
            raise InspectionError("输入图像为空")

        # 0. 标定校验 + 畸变校正(§8: 必须在坐标映射与 ROI 之前)
        img_size = (capture_image.shape[1], capture_image.shape[0])
        calib_status, calib_params, calib_ok = self._check_calibration(
            img_size, source)
        result.calibration_status = calib_status
        undistorted = (self.calibration.undistort(capture_image, calib_params)
                       if calib_params is not None else capture_image)
        if calib_params is None:
            logger.warning("畸变校正跳过(无有效参数),后续模块使用原始图;"
                           "Golden 与 Current 均未校正,约定一致")

        # 1. Mark 定位 + 对齐
        marks = self.mark_detector.detect(undistorted)
        H = self.aligner.compute_transform(marks)
        # 独立点重投影评估(§11.1): 留一点拟合、投影该点,误差独立可信
        self.last_reproj_loo = leave_one_out_error(
            marks, self.aligner.canonical_marks[:len(marks)])
        aligned = self.aligner.align_with_matrix(undistorted, H)
        result.alignment_status = "OK"

        # 2. 坐标映射状态(§10.2/§11)
        confirmed = bool(self.cfg.get("coordinate.coordinate_meaning_confirmed",
                                      False))
        result.coordinate_mapping_status = "confirmed" if confirmed \
            else "unconfirmed"

        # 3. ROI + Mask
        transform = CoordinateTransform.from_config(self.cfg, homography=H)
        components = self.excel.load_components()
        roi_mgr = RoiManager(self.cfg, transform)
        rois = roi_mgr.create_rois(components)
        self.last_roi_summary = roi_mgr.last_summary
        w, h = self.aligner.aligned_size
        mask_gen = ComponentMaskGenerator(w, h)
        component_mask = mask_gen.generate(rois)
        pcb_mask = self.pcb_locator.board_mask_aligned(w, h)
        valid_mask = mask_gen.detection_mask(pcb_mask, component_mask)
        if int(valid_mask.sum()) == 0:
            from src.utils.exceptions import InspectionError
            raise InspectionError("有效检测 Mask 为空(元件掩膜覆盖了全部 PCB 区)")

        # 4. Golden + 条件一致性检查(§14)
        golden, golden_meta = self.golden_mgr.load_golden()
        golden_calib = golden_meta.get("calibration", {})
        condition_mismatch = (
            bool(golden_calib) is False
            or golden_calib.get("is_identity") != bool(
                calib_params and calib_params.get("is_identity"))
            or golden_meta.get("transform_version") != MAPPING_VERSION)

        # 5. 差分 + 缺陷检测
        diff = self.diff_detector.compute(golden, aligned,
                                          component_mask, pcb_mask)
        defects = self.solder_detector.detect(diff, to_gray(aligned))

        # 6. 结果汇总
        inspected = [c for c in components if c.inspect]
        result.components_total = len(inspected)
        result.components_pass = len(inspected)
        result.components_ng = 0
        result.solder_defect_count = len(defects)
        # 缺陷归属: 单板编号由拼板坐标空间判定(§9.1),关联包含它的 ROI
        defect_records: list[DefectRecord] = []
        for d in defects:
            board_id = self.panel.board_id_for_image_point(d.x, d.y)
            ref = next((r.ref for r in rois if r.contains(d.x, d.y)), "")
            defect_records.append(DefectRecord(
                type=d.type, ref=ref, board_id=board_id,
                x=d.x, y=d.y, width=d.width, height=d.height,
                area=d.area, score=d.score,
                message=f"疑似{'锡珠' if 'ball' in d.type else '锡渣'} "
                        f"@({d.x},{d.y})px 圆度={d.circularity}(候选排序分,非概率)"))
        result.defects = defect_records
        result.config_versions = {
            "config_file": self.cfg.config_path.name,
            "mapping_version": MAPPING_VERSION,
            "roi_config_version": ROI_CONFIG_VERSION,
            "calibration": calib_status,
            "coordinate_file": self.excel.path.name,
        }

        # 7. 判定门控(§18): REVIEW > NG > PASS
        review: list[str] = []
        if bool(self.cfg.get("decision.require_valid_calibration", True)) \
                and not calib_ok:
            review.append(f"无有效相机标定(状态: {calib_status})")
        if bool(self.cfg.get("decision.require_valid_coordinate_mapping",
                             True)) and not confirmed:
            review.append("坐标语义未确认(CoordMeaningConfirmed=NO)")
        if condition_mismatch:
            review.append("Golden 与当前标定/变换条件不一致,应重建 Golden")
        # ROI 状态门控(§12/§18): UNCONFIGURED 元件无法验证 -> REVIEW;
        # REVIEW 状态 ROI 内发现缺陷 -> 该缺陷需人工复核 -> REVIEW
        roi_summary = self.last_roi_summary
        if roi_summary.get("unconfigured", 0) > 0:
            review.append(
                f"{roi_summary['unconfigured']} 个 ROI 坐标语义未确认"
                "(UNCONFIGURED),对应元件本次未验证")
        review_rois = [r for r in rois if r.status == "REVIEW"]
        if review_rois:
            hits = [d.ref for d in defect_records
                    if d.ref and any(r.ref == d.ref for r in review_rois)]
            if hits:
                review.append(
                    f"缺陷落在待复核 ROI({','.join(sorted(set(hits)))}),需人工确认")
            else:
                logger.info("ROI REVIEW 状态(无缺陷落入): %s",
                            [r.ref for r in review_rois])
        result.review_reasons = review
        if review:
            result.overall_status = str(
                self.cfg.get("decision.uncertain_status", "REVIEW"))
            result.message = "; ".join(review)
            logger.warning("判定 REVIEW: %s", result.message)
        else:
            result.overall_status = "NG" if defects else "PASS"

        # 8. 产物(§19)
        if save_output:
            out_dir = self._make_output_dir()
            result.output_dir = str(out_dir)
            overlay = self._draw_overlay(aligned, rois, defects,
                                         result.overall_status)
            # roi_overlay: 拼板边界 + 编号打底,ROI 按状态着色叠加 (§9.1/§12)
            roi_overlay = roi_mgr.draw_all(self.panel.draw_boards(aligned),
                                           rois)
            masks_color = ComponentMaskGenerator.visualize_color(
                pcb_mask, component_mask, valid_mask)
            save_image(capture_image, out_dir / "original.jpg")
            save_image(undistorted, out_dir / "undistorted.jpg")
            save_image(aligned, out_dir / "aligned.jpg")
            save_image(roi_overlay, out_dir / "roi_overlay.jpg")
            save_image(pcb_mask, out_dir / "pcb_mask.png")
            save_image(component_mask, out_dir / "component_mask.png")
            save_image(valid_mask, out_dir / "valid_inspection_mask.png")
            save_image(masks_color, out_dir / "masks_color.png")
            save_image(diff.diff_image, out_dir / "diff.png")
            save_image(overlay, out_dir / "overlay.jpg")
            self._save_config_snapshot(out_dir, result, H)
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

    def _save_config_snapshot(self, out_dir: Path,
                              result: InspectionResult,
                              H: np.ndarray | None = None) -> None:
        """本次检测的配置/参数快照(§19 可追溯),含坐标映射与拼板信息。"""
        snapshot = {"config": self.cfg.as_dict(),
                    "versions": result.config_versions,
                    "calibration_status": result.calibration_status,
                    "coordinate_mapping_status":
                        result.coordinate_mapping_status,
                    "mapping": {
                        "mapping_version": MAPPING_VERSION,
                        "homography": H.tolist() if H is not None else None,
                        "reproj_loo_max_px": round(self.last_reproj_loo[0], 3),
                        "reproj_loo_mean_px": round(self.last_reproj_loo[1], 3),
                    },
                    "panel": {
                        "mode": self.panel.mode,
                        "placements": [
                            {"board_id": p.board_id,
                             "origin_x_mm": p.origin_x_mm,
                             "origin_y_mm": p.origin_y_mm,
                             "rotation_deg": p.rotation_deg,
                             "width_mm": p.width_mm,
                             "height_mm": p.height_mm}
                            for p in self.panel.placements()],
                    },
                    "roi_summary": self.last_roi_summary}
        (out_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False),
            encoding="utf-8")

    @staticmethod
    def _draw_overlay(aligned: np.ndarray, rois, defects,
                      status: str) -> np.ndarray:
        """overlay: 绿=PASS ROI,红=NG 缺陷框,黄=REVIEW,顶部状态条。"""
        out = aligned.copy()
        for roi in rois:
            roi.draw(out, _COLOR_PASS)
        for d in defects:
            cv2.rectangle(out, (d.x - 3, d.y - 3),
                          (d.x + d.width + 3, d.y + d.height + 3),
                          _COLOR_NG, 2)
            cv2.putText(out, d.type.replace("suspected_", ""),
                        (d.x, max(12, d.y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, _COLOR_NG, 1)
        color = {"PASS": _COLOR_PASS, "NG": _COLOR_NG}.get(
            status, _COLOR_REVIEW)
        cv2.rectangle(out, (0, 0), (out.shape[1], 26), (30, 30, 30), -1)
        cv2.putText(out, f"AOI RESULT: {status} (MVP候选)  "
                    f"defects={len(defects)}",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        return out
