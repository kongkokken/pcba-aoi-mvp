"""检测引擎与判定逻辑测试 (融合版 §18/§19/§22):
PASS/NG/REVIEW 判定、JSON 字段完整、产物文件齐全、门控规则。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.config.config_manager import ConfigManager
from src.golden.golden_manager import GoldenManager
from src.inspection.inspection_engine import InspectionEngine
from src.utils.image_utils import load_image

# §19 要求的产物清单
REQUIRED_ARTIFACTS = [
    "original.jpg", "undistorted.jpg", "aligned.jpg", "roi_overlay.jpg",
    "pcb_mask.png", "component_mask.png", "valid_inspection_mask.png",
    "diff.png", "overlay.jpg", "result.json", "config_snapshot.yaml",
]

REQUIRED_JSON_FIELDS = [
    "pcb_name", "timestamp", "overall_status", "alignment_status",
    "calibration_status", "coordinate_mapping_status",
    "components_total", "components_pass", "components_ng",
    "solder_defect_count", "defects", "config_versions",
    "review_reasons", "result_grade",
]

REQUIRED_DEFECT_FIELDS = ["type", "ref", "board_id", "x", "y",
                          "width", "height", "area", "score", "message"]


@pytest.fixture(scope="module")
def ready(cfg: ConfigManager, synthetic: Path):
    """确保 identity 标定 + golden 就绪(合成路径)。"""
    import main
    main.ensure_synthetic_calibration(cfg)
    gm = GoldenManager(cfg)
    if not gm.exists():
        gm.create_golden(load_image(synthetic / "capture_ok.jpg"))
    return cfg


def cfg_with(cfg: ConfigManager, **overrides) -> ConfigManager:
    """深拷贝配置并覆盖指定键(如 decision__require_valid_calibration=False)。"""
    c = ConfigManager()
    c._data = copy.deepcopy(cfg._data)
    for key, value in overrides.items():
        node = c._data
        parts = key.split("__")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return c


class TestDecisionLogic:
    def test_synthetic_ok_pass(self, ready, synthetic):
        r = InspectionEngine(ready).inspect(
            load_image(synthetic / "capture_ok.jpg"), save_output=False,
            source="synthetic")
        assert r.overall_status == "PASS"
        assert r.calibration_status == "identity_skip"
        assert r.coordinate_mapping_status == "confirmed"
        assert r.result_grade == "MVP_CANDIDATE"

    def test_synthetic_ng(self, ready, synthetic):
        r = InspectionEngine(ready).inspect(
            load_image(synthetic / "capture_ng.jpg"), save_output=False,
            source="synthetic")
        assert r.overall_status == "NG"
        assert r.solder_defect_count == 3

    def test_unconfirmed_coordinates_force_review(self, ready, synthetic):
        """坐标语义未确认时不得输出 PASS (§27.5)。"""
        c = cfg_with(ready, coordinate__coordinate_meaning_confirmed=False)
        r = InspectionEngine(c).inspect(
            load_image(synthetic / "capture_ok.jpg"), save_output=False,
            source="synthetic")
        assert r.overall_status == "REVIEW"
        assert any("坐标语义" in x for x in r.review_reasons)

    def test_identity_not_accepted_for_real_source(self, ready, synthetic):
        """identity 豁免仅对 synthetic 来源有效;相机来源必须 REVIEW。"""
        r = InspectionEngine(ready).inspect(
            load_image(synthetic / "capture_ok.jpg"), save_output=False,
            source="camera")
        assert r.overall_status == "REVIEW"
        assert r.calibration_status == "identity_skip"
        assert any("标定" in x for x in r.review_reasons)

    def test_gating_can_be_disabled_by_config(self, ready, synthetic):
        """配置显式放宽门控时恢复 PASS(记录配置变更的责任在使用方)。"""
        c = cfg_with(ready,
                     decision__require_valid_calibration=False,
                     decision__require_valid_coordinate_mapping=False)
        r = InspectionEngine(c).inspect(
            load_image(synthetic / "capture_ok.jpg"), save_output=False,
            source="camera")
        assert r.overall_status == "PASS"


class TestResultArtifacts:
    def test_artifacts_and_json_fields(self, ready, synthetic):
        engine = InspectionEngine(ready)
        r = engine.inspect(load_image(synthetic / "capture_ng.jpg"),
                           save_output=True, source="synthetic")
        assert r.overall_status == "NG"
        out = Path(r.output_dir)
        for name in REQUIRED_ARTIFACTS:
            assert (out / name).exists(), f"缺产物: {name}"
        data = json.loads((out / "result.json").read_text(encoding="utf-8"))
        for f in REQUIRED_JSON_FIELDS:
            assert f in data, f"result.json 缺字段: {f}"
        assert len(data["defects"]) == 3
        for d in data["defects"]:
            for f in REQUIRED_DEFECT_FIELDS:
                assert f in d, f"defect 缺字段: {f}"
            assert d["board_id"] == "BOARD_1"

    def test_error_result_does_not_crash(self, ready):
        import numpy as np
        r = InspectionEngine(ready).inspect(
            np.zeros((0, 0, 3), np.uint8), save_output=False)
        assert r.overall_status == "ERROR"
        assert r.message
