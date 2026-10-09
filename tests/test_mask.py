"""Mask 三输出与极性测试 (融合版 §13):
极性约定 255=真、pcb/component/valid 三掩膜、空掩膜报错、彩色可视化。"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from src.config.config_manager import ConfigManager
from src.mask.component_mask import MASK_ON, ComponentMaskGenerator
from src.roi.roi import Roi


def cfg_with(cfg: ConfigManager, **overrides) -> ConfigManager:
    c = ConfigManager()
    c._data = copy.deepcopy(cfg._data)
    for key, value in overrides.items():
        node = c._data
        parts = key.split("__")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return c


def make_roi(cx=50.0, cy=50.0, w=20.0, h=10.0) -> Roi:
    return Roi(ref="T1", cx=cx, cy=cy, width=w, height=h, angle=0.0)


class TestPolarity:
    def test_polarity_255_accepted(self, cfg: ConfigManager):
        gen = ComponentMaskGenerator(100, 100, cfg)
        assert gen.polarity == MASK_ON == 255

    def test_other_polarity_rejected(self, cfg: ConfigManager):
        """配置与实现约定不一致时拒绝静默继续 (§13)。"""
        c = cfg_with(cfg, mask__polarity=0)
        with pytest.raises(ValueError):
            ComponentMaskGenerator(100, 100, c)


class TestThreeOutputs:
    def setup_method(self):
        self.gen = ComponentMaskGenerator(100, 100)
        self.comp = self.gen.generate([make_roi()])
        self.pcb = np.full((100, 100), MASK_ON, np.uint8)
        self.pcb[0:5, 0:5] = 0          # 左上角板外
        self.valid = self.gen.detection_mask(self.pcb, self.comp)

    def test_component_mask_marks_roi(self):
        assert self.comp[50, 50] == MASK_ON
        assert self.comp[10, 90] == 0

    def test_valid_is_pcb_minus_component(self):
        assert self.valid[50, 50] == 0        # 元件区不在检测区
        assert self.valid[50, 90] == MASK_ON  # 开阔区在检测区
        assert self.valid[2, 2] == 0          # 板外不在检测区

    def test_empty_detection_mask_raises(self):
        full = np.full((100, 100), MASK_ON, np.uint8)
        with pytest.raises(ValueError):
            self.gen.detection_mask(full, full)  # 元件掩膜覆盖全部板区

    def test_size_mismatch_raises(self):
        with pytest.raises(ValueError):
            self.gen.detection_mask(np.zeros((50, 50), np.uint8),
                                    np.zeros((100, 100), np.uint8))

    def test_visualize_color_semantics(self):
        vis = ComponentMaskGenerator.visualize_color(
            self.pcb, self.comp, self.valid)
        assert vis.shape == (100, 100, 3)
        assert tuple(vis[50, 90]) == (0, 200, 0)    # 检测区: 绿
        assert tuple(vis[50, 50]) == (0, 0, 200)    # 元件屏蔽: 红
        assert tuple(vis[2, 2]) == (90, 90, 90)     # 板外: 灰

    def test_mask_false_roi_excluded(self):
        roi = make_roi()
        roi.mask = False
        mask = self.gen.generate([roi])
        assert mask.sum() == 0
