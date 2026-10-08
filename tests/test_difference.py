"""差分 / Homography / 异常识别测试 (任务书 §二十六.6-10)。"""
from __future__ import annotations

import numpy as np
import pytest

from src.config.config_manager import ConfigManager
from src.difference.image_difference import ImageDifferenceDetector
from src.pcb.alignment import Aligner
from src.pcb.mark_detector import MarkDetector
from src.solder.solder_detector import SolderDefectDetector
from src.utils.exceptions import AlignmentError, InspectionError
from src.utils.image_utils import load_image, to_gray


@pytest.fixture(scope="module")
def detector(cfg: ConfigManager) -> ImageDifferenceDetector:
    return ImageDifferenceDetector(cfg)


class TestDifferenceBasics:
    def test_identical_images_no_regions(self, detector, golden_image):
        res = detector.compute(golden_image, golden_image.copy())
        assert res.regions == []

    def test_empty_image_raises(self, detector, golden_image):
        with pytest.raises(InspectionError):
            detector.compute(np.zeros((0, 0, 3), np.uint8), golden_image)
        with pytest.raises(InspectionError):
            detector.compute(golden_image, None)

    def test_size_mismatch_raises(self, detector, golden_image):
        small = np.zeros((100, 100, 3), np.uint8)
        with pytest.raises(InspectionError):
            detector.compute(golden_image, small)

    def test_known_blob_detected(self, detector, golden_image):
        """在 golden 副本上人为画一个亮斑,必须被检出。"""
        current = golden_image.copy()
        h, w = current.shape[:2]
        cv2_circle = (w // 2 + 100, h // 2 + 100)
        import cv2
        cv2.circle(current, cv2_circle, 8, (240, 245, 250), -1)
        res = detector.compute(golden_image, current)
        hit = any(abs(r.x + r.width / 2 - cv2_circle[0]) < 15
                  and abs(r.y + r.height / 2 - cv2_circle[1]) < 15
                  for r in res.regions)
        assert hit, "人为亮斑未被检出"


class TestHomographyFailure:
    def test_collinear_points_raise(self, cfg: ConfigManager):
        aligner = Aligner(cfg)
        collinear = np.float64([[0, 0], [100, 100], [200, 200], [300, 300]])
        with pytest.raises(AlignmentError):
            aligner.compute_transform(collinear)

    def test_too_few_points_raise(self, cfg: ConfigManager):
        aligner = Aligner(cfg)
        with pytest.raises(AlignmentError):
            aligner.compute_transform(np.float64([[0, 0], [10, 10]]))

    def test_duplicate_points_raise(self, cfg: ConfigManager):
        aligner = Aligner(cfg)
        dup = np.float64([[100, 100], [100, 100], [100, 100], [100, 100]])
        with pytest.raises(AlignmentError):
            aligner.compute_transform(dup)

    def test_empty_image_align_raises(self, cfg: ConfigManager):
        aligner = Aligner(cfg)
        marks = np.float64([[0, 0], [100, 0], [100, 100], [0, 100]])
        with pytest.raises(AlignmentError):
            aligner.align(np.zeros((0, 0, 3), np.uint8), marks)


class TestAnomalyDetectionEndToEnd:
    """用合成图走完整 差分->缺陷 链路 (任务书 §二十六.10)。"""

    def test_synthetic_ng_detects_all_defects(self, cfg: ConfigManager,
                                              synthetic, golden_image):
        det, aligner = MarkDetector(cfg), Aligner(cfg)
        img = load_image(synthetic / "capture_ng.jpg")
        aligned = aligner.align(img, det.detect(img))
        dd = ImageDifferenceDetector(cfg)
        res = dd.compute(golden_image, aligned)
        defects = SolderDefectDetector(cfg).detect(res, to_gray(aligned))
        # 合成 NG 图含 3 个缺陷,且无元件掩膜时也应至少检出 3 个异常区
        assert len(res.regions) >= 3
        assert len(defects) >= 3
        types = {d.type for d in defects}
        assert "suspected_solder_ball" in types
        assert "suspected_debris" in types

    def test_synthetic_ok_no_defects(self, cfg: ConfigManager,
                                     synthetic, golden_image):
        det, aligner = MarkDetector(cfg), Aligner(cfg)
        img = load_image(synthetic / "capture_ok.jpg")
        aligned = aligner.align(img, det.detect(img))
        dd = ImageDifferenceDetector(cfg)
        res = dd.compute(golden_image, aligned)
        defects = SolderDefectDetector(cfg).detect(res, to_gray(aligned))
        assert defects == []
