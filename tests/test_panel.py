"""拼板分割与坐标空间测试 (融合版 §9.1):
single/grid placements、单板<->拼板坐标往返、缺陷归属编号、auto 退化。"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from src.config.config_manager import ConfigManager
from src.panel.panel_segmenter import BoardPlacement, PanelSegmenter
from src.utils.image_utils import load_image


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


class TestPlacements:
    def test_single_mode_one_board(self, cfg: ConfigManager):
        ps = PanelSegmenter(cfg).placements()
        assert len(ps) == 1
        p = ps[0]
        assert p.board_id == "BOARD_1"
        assert (p.origin_x_mm, p.origin_y_mm) == (0.0, 0.0)
        assert (p.width_mm, p.height_mm) == (100.0, 70.0)

    def test_grid_mode_row_major(self, cfg: ConfigManager):
        c = cfg_with(cfg, panel__mode="grid", panel__rows=2, panel__cols=2,
                     panel__spacing_x_mm=5.0, panel__spacing_y_mm=5.0)
        seg = PanelSegmenter(c)
        assert seg.is_panel()
        ps = seg.placements()
        assert [p.board_id for p in ps] == \
            ["BOARD_1", "BOARD_2", "BOARD_3", "BOARD_4"]
        assert (ps[1].origin_x_mm, ps[1].origin_y_mm) == (105.0, 0.0)
        assert (ps[2].origin_x_mm, ps[2].origin_y_mm) == (0.0, 75.0)
        assert (ps[3].origin_x_mm, ps[3].origin_y_mm) == (105.0, 75.0)
        assert seg.panel_size_mm() == (205.0, 145.0)

    def test_single_is_not_panel(self, cfg: ConfigManager):
        assert not PanelSegmenter(cfg).is_panel()


class TestCoordinateMapping:
    def test_board_panel_roundtrip_with_rotation(self):
        p = BoardPlacement("B1", origin_x_mm=10.0, origin_y_mm=20.0,
                           rotation_deg=30.0, width_mm=50.0, height_mm=40.0)
        for x, y in [(0.0, 0.0), (25.0, 20.0), (50.0, 40.0)]:
            px, py = p.board_to_panel(x, y)
            bx, by = p.panel_to_board(px, py)
            assert bx == pytest.approx(x, abs=1e-9)
            assert by == pytest.approx(y, abs=1e-9)

    def test_board_id_for_panel_point(self, cfg: ConfigManager):
        c = cfg_with(cfg, panel__mode="grid", panel__rows=2, panel__cols=2,
                     panel__spacing_x_mm=5.0, panel__spacing_y_mm=5.0)
        seg = PanelSegmenter(c)
        assert seg.board_id_for_panel_point(10.0, 10.0) == "BOARD_1"
        assert seg.board_id_for_panel_point(110.0, 10.0) == "BOARD_2"
        assert seg.board_id_for_panel_point(10.0, 80.0) == "BOARD_3"
        assert seg.board_id_for_panel_point(110.0, 80.0) == "BOARD_4"
        # 拼板间距区不属于任何单板
        assert seg.board_id_for_panel_point(102.0, 10.0) == "UNKNOWN"

    def test_board_id_for_image_point_single(self, cfg: ConfigManager):
        seg = PanelSegmenter(cfg)
        # 对齐图 px -> mm(px_per_mm=8): (400,280)px = (50,35)mm 板内
        assert seg.board_id_for_image_point(400, 280) == "BOARD_1"
        assert seg.board_id_for_image_point(10000, 10000) == "UNKNOWN"


class TestAutoDetect:
    def test_auto_detect_degenerates_to_single(self, cfg: ConfigManager,
                                               synthetic: Path):
        """合成图上只有一块板: auto 检测至多找到 1 个轮廓(退化 single)。"""
        c = cfg_with(cfg, panel__mode="auto")
        seg = PanelSegmenter(c)
        quads = seg.detect_boards_auto(load_image(synthetic / "capture_ok.jpg"))
        assert isinstance(quads, list)
        assert len(quads) <= 1  # >1 才允许按拼板处理,否则退化

    def test_draw_boards_runs(self, cfg: ConfigManager, synthetic: Path):
        img = load_image(synthetic / "capture_ok.jpg")
        out = PanelSegmenter(cfg).draw_boards(img)
        assert out.shape == img.shape
        assert not np.array_equal(out, img)  # 确实画上了边界/编号
