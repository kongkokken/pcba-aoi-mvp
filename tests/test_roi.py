"""ROI / Mask 测试 (任务书 §二十六.3/4/5)。"""
from __future__ import annotations

import numpy as np
import pytest

from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import Component, ExcelManager
from src.mask.component_mask import ComponentMaskGenerator
from src.pcb.alignment import Aligner
from src.pcb.pcb_locator import PcbLocator
from src.roi.roi import Roi
from src.roi.roi_manager import RoiManager
from src.utils.exceptions import ROIError


def make_component(**kw) -> Component:
    base = dict(ref="T1", type="R", x=50.0, y=35.0, width=4.0, height=2.0,
                angle=0.0, inspect=True, ocr=False, expected_value="",
                mask=True, algorithm="Geometry", position_tolerance=0.5,
                size_tolerance="20%", angle_tolerance=10, roi_expand=0.2)
    base.update(kw)
    return Component(**base)


@pytest.fixture(scope="module")
def roi_manager(cfg: ConfigManager) -> RoiManager:
    return RoiManager(cfg, CoordinateTransform.from_config(cfg))


class TestRoiGeneration:
    def test_rois_from_excel(self, cfg: ConfigManager, roi_manager: RoiManager):
        comps = ExcelManager(cfg).load_components()
        rois = roi_manager.create_rois(comps)
        assert len(rois) == len(comps)
        for roi in rois:
            x, y, w, h = roi.bounding_rect
            assert 0 <= x and 0 <= y
            assert x + w <= roi_manager.img_w and y + h <= roi_manager.img_h

    def test_roi_expansion(self, roi_manager: RoiManager):
        roi = roi_manager.create_roi(make_component(roi_expand=0.2))
        # 4mm*8px=32 -> 外扩 20% -> 38.4
        assert roi.width == pytest.approx(32 * 1.2, abs=0.5)

    def test_rotated_roi(self, roi_manager: RoiManager):
        roi = roi_manager.create_roi(make_component(angle=90.0))
        x, y, w, h = roi.bounding_rect
        assert h > w  # 90° 旋转后外接框高大于宽

    def test_roi_contains_center(self, roi_manager: RoiManager):
        roi = roi_manager.create_roi(make_component())
        assert roi.contains(roi.cx, roi.cy)


class TestRoiOutOfBounds:
    def test_fully_outside_raises(self, roi_manager: RoiManager):
        with pytest.raises(ROIError):
            roi_manager.create_roi(make_component(x=200.0, y=200.0))

    def test_partially_outside_clipped(self, roi_manager: RoiManager):
        roi = roi_manager.create_roi(make_component(x=99.5, y=69.0))
        assert roi.points[:, 0].max() <= roi_manager.img_w - 1
        assert roi.points[:, 1].max() <= roi_manager.img_h - 1


class TestComponentMask:
    def test_mask_excludes_components(self, cfg: ConfigManager,
                                      roi_manager: RoiManager):
        comps = ExcelManager(cfg).load_components()
        rois = roi_manager.create_rois(comps)
        w, h = Aligner(cfg).aligned_size
        gen = ComponentMaskGenerator(w, h)
        cmask = gen.generate(rois)
        assert cmask.shape == (h, w)
        assert cmask.sum() > 0
        # 所有元件中心必须在掩膜内
        for c in comps:
            px, py = int(c.x * 8), int(c.y * 8)
            assert cmask[py, px] == 255

    def test_detection_mask_is_pcb_minus_components(self, cfg: ConfigManager,
                                                    roi_manager: RoiManager):
        rois = roi_manager.create_rois(ExcelManager(cfg).load_components())
        w, h = Aligner(cfg).aligned_size
        gen = ComponentMaskGenerator(w, h)
        cmask = gen.generate(rois)
        pmask = PcbLocator(cfg).board_mask_aligned(w, h)
        det = gen.detection_mask(pmask, cmask)
        # 元件中心不在检测区;开阔区在检测区
        assert det[320, 400] == 0          # U101 中心
        assert det[100, 500] == 255        # 开阔区 (62.5mm, 12.5mm)

    def test_mask_size_mismatch_raises(self):
        gen = ComponentMaskGenerator(100, 100)
        with pytest.raises(ValueError):
            gen.detection_mask(np.zeros((50, 50), np.uint8),
                               np.zeros((100, 100), np.uint8))
