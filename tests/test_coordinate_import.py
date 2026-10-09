"""坐标文件解析与语义确认测试 (融合版 §10):
多格式读取/字段映射/可追溯性/校验清单/语义门控阻断 ROI。"""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

from src.config.config_manager import ConfigManager
from src.coordinate.coordinate_transform import CoordinateTransform
from src.coordinate.excel_manager import (BASE_COLUMNS, COLUMNS,
                                          EXTENDED_COLUMNS, ExcelManager,
                                          default_rows)
from src.roi.roi_manager import RoiManager
from src.utils.exceptions import ExcelConfigError

FIXTURE_XLS = Path(__file__).parent / "fixtures" / "components_legacy.xls"


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


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


class TestTemplate:
    def test_template_has_base_and_extended_columns(self, cfg: ConfigManager,
                                                    tmp_path: Path):
        em = ExcelManager(cfg)
        em.path = tmp_path / "pcb_config.xlsx"
        em.create_template(overwrite=True)
        df = pd.read_excel(em.path, sheet_name="Components")
        for col in COLUMNS:
            assert col in df.columns, f"模板缺字段: {col}"
        assert len(BASE_COLUMNS) == 16 and len(EXTENDED_COLUMNS) == 13

    def test_synthetic_template_rows_confirmed(self, cfg: ConfigManager,
                                               tmp_path: Path):
        """合成模板为自建几何,语义已定义 -> YES(诚实,非伪造确认)。"""
        em = ExcelManager(cfg)
        em.path = tmp_path / "t.xlsx"
        em.create_template(overwrite=True)
        comps = em.load_components()
        assert len(comps) == 6
        for c in comps:
            assert c.coord_confirmed is True
            assert c.coordinate_system == "pcb_absolute_mm"
            assert c.teach_x is not None and c.teach_y is not None
            assert c.board_id == "BOARD_1"


class TestFormats:
    def test_csv_support(self, cfg: ConfigManager, tmp_path: Path):
        p = write_csv(default_rows(), tmp_path / "comps.csv")
        comps = ExcelManager(cfg).load_components(p)
        assert len(comps) == 6
        assert comps[0].source_file == "comps.csv"
        assert comps[0].source_sheet == ""       # CSV 无工作表
        assert comps[0].source_row == 2          # 表头占第 1 行

    def test_legacy_xls_support(self, cfg: ConfigManager):
        """旧版 .xls(xlrd 引擎);夹具由 tools 脚本用 xlwt 生成。"""
        if not FIXTURE_XLS.exists():
            pytest.skip("legacy .xls fixture 未生成")
        comps = ExcelManager(cfg).load_components(FIXTURE_XLS)
        assert len(comps) == 6
        assert comps[0].ref == "R101"
        assert comps[0].source_sheet == "Components"

    def test_unsupported_format_rejected(self, cfg: ConfigManager,
                                         tmp_path: Path):
        p = tmp_path / "comps.txt"
        p.write_text("Ref,X\nR1,1\n", encoding="utf-8")
        with pytest.raises(ExcelConfigError, match="不支持"):
            ExcelManager(cfg).load_components(p)


class TestFieldMapping:
    def test_field_mapping_avoids_hardcoding(self, cfg: ConfigManager,
                                             tmp_path: Path):
        """客户列名 RefDes/PosX/PosY 经映射接入,不改程序 (§10.1)。"""
        df = default_rows().rename(columns={"Ref": "RefDes", "X": "PosX",
                                            "Y": "PosY"})
        p = write_csv(df, tmp_path / "customer.csv")
        c = cfg_with(cfg, coordinate_import__field_mapping={
            "Ref": "RefDes", "X": "PosX", "Y": "PosY"})
        comps = ExcelManager(c).load_components(p)
        assert comps[0].ref == "R101"
        assert comps[0].x == pytest.approx(25.4)

    def test_missing_required_field_lists_mapping_hint(
            self, cfg: ConfigManager, tmp_path: Path):
        df = default_rows().drop(columns=["Angle"])
        p = write_csv(df, tmp_path / "bad.csv")
        with pytest.raises(ExcelConfigError, match="field_mapping"):
            ExcelManager(cfg).load_components(p)


class TestValidation:
    def test_duplicate_ref_raises(self, cfg: ConfigManager, tmp_path: Path):
        df = default_rows()
        df.loc[1, "Ref"] = df.loc[0, "Ref"]
        with pytest.raises(ExcelConfigError, match="重复"):
            ExcelManager(cfg).load_components(write_csv(df, tmp_path / "d.csv"))

    def test_empty_coordinate_raises_no_guessfill(self, cfg: ConfigManager,
                                                  tmp_path: Path):
        """空坐标必须报错,不得猜测补齐 (§10.2)。"""
        df = default_rows()
        df.loc[2, "X"] = None
        with pytest.raises(ExcelConfigError, match="坐标为空或非法"):
            ExcelManager(cfg).load_components(write_csv(df, tmp_path / "e.csv"))

    def test_abnormal_angle_raises(self, cfg: ConfigManager, tmp_path: Path):
        df = default_rows()
        df.loc[0, "Angle"] = 400.0
        with pytest.raises(ExcelConfigError, match="角度异常"):
            ExcelManager(cfg).load_components(write_csv(df, tmp_path / "a.csv"))

    def test_missing_teach_values_stay_none(self, cfg: ConfigManager,
                                            tmp_path: Path):
        df = default_rows()
        df.loc[0, "TeachX"] = None
        comps = ExcelManager(cfg).load_components(
            write_csv(df, tmp_path / "t.csv"))
        assert comps[0].teach_x is None      # 缺失保留 None
        assert comps[1].teach_x is not None  # 其他行不受影响


class TestSemanticsGating:
    def test_unconfirmed_marks_component(self, cfg: ConfigManager,
                                         tmp_path: Path):
        df = default_rows()
        df.loc[1, "CoordinateMeaningConfirmed"] = "NO"
        comps = ExcelManager(cfg).load_components(
            write_csv(df, tmp_path / "u.csv"))
        assert comps[0].coord_confirmed is True
        assert comps[1].coord_confirmed is False
        assert "待确认" in comps[1].notes
        # 原始值保留可追溯 (§10.1)
        assert comps[1].raw["CoordinateMeaningConfirmed"] == "NO"

    def test_unconfirmed_blocks_roi(self, cfg: ConfigManager, tmp_path: Path):
        """CoordinateMeaningConfirmed=NO -> ROI UNCONFIGURED (§10.2/§12.9)。"""
        df = default_rows()
        df.loc[0, "CoordinateMeaningConfirmed"] = "NO"
        comps = ExcelManager(cfg).load_components(
            write_csv(df, tmp_path / "u.csv"))
        roi_mgr = RoiManager(cfg, CoordinateTransform.from_config(cfg))
        rois = roi_mgr.create_rois(comps)
        assert rois[0].status == "UNCONFIGURED"
        assert rois[1].status == "OK"
        assert roi_mgr.last_summary["unconfigured"] == 1

    def test_legacy_file_without_semantics_column_falls_back(
            self, cfg: ConfigManager, tmp_path: Path):
        """旧格式(无语义列)回退全局确认状态,并在 notes 记录(可追溯)。"""
        df = default_rows()[BASE_COLUMNS]   # 模拟旧 16 字段文件
        comps = ExcelManager(cfg).load_components(
            write_csv(df, tmp_path / "legacy.csv"))
        assert all(c.coord_confirmed for c in comps)  # 全局配置=true
        assert "回退全局确认状态" in comps[0].notes
        # 全局未确认时旧文件同样被阻断
        c = cfg_with(cfg, coordinate__coordinate_meaning_confirmed=False)
        comps2 = ExcelManager(c).load_components(
            write_csv(df, tmp_path / "legacy2.csv"))
        assert not any(c2.coord_confirmed for c2 in comps2)
