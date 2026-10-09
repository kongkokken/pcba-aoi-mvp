"""相机标定模块测试 (融合版 §8.4/§22): 保存/加载/损坏/分辨率不符/样本不足/
校正输出/残差统计/条件变更提示/identity 豁免。"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from src.calibration.calibration import (BoardSpec, CalibrationManager)
from src.calibration.synthetic_board import TRUE_DIST, TRUE_K, generate_views
from src.config.config_manager import ConfigManager
from src.utils.exceptions import CalibrationError


@pytest.fixture()
def calib_cfg(cfg: ConfigManager, tmp_path) -> ConfigManager:
    """标定参数文件指向临时目录的独立配置。"""
    c = ConfigManager()
    c._data = copy.deepcopy(cfg._data)  # 测试内独立副本,避免污染全局配置
    c._data["calibration"]["parameter_file"] = str(
        tmp_path / "camera_calibration.json")
    return c


@pytest.fixture(scope="module")
def board() -> BoardSpec:
    return BoardSpec(type="chessboard", rows=6, cols=9,
                     square_size=25.0, unit="mm")


@pytest.fixture(scope="module")
def views(board: BoardSpec) -> list[np.ndarray]:
    return generate_views(board, n_views=10)


class TestCalibrationSolve:
    def test_calibrate_recovers_intrinsics(self, calib_cfg, board, views):
        """合成畸变样本 -> calibrateCamera 回收内参接近真值。"""
        cm = CalibrationManager(calib_cfg)
        params = cm.calibrate(views, board)
        K = np.asarray(params["camera_matrix"])
        assert abs(K[0, 0] - TRUE_K[0, 0]) / TRUE_K[0, 0] < 0.10  # fx 偏差<10%
        assert abs(K[1, 1] - TRUE_K[1, 1]) / TRUE_K[1, 1] < 0.10
        # RMS 阈值说明: 合成样本经 warpPerspective+畸变 remap 双重插值,
        # 角点定位精度受限;此处验证求解链路而非度量学精度(§23 合成测试层级)
        assert params["rms_reprojection_error"] < 3.0
        assert params["valid_sample_count"] == len(views)
        # 每样本残差齐全(§8.4: 不得只看 RMS)
        res = [r.get("residual_px") for r in params["per_image"]
               if r["detected"]]
        assert len(res) == len(views) and all(r < 4.0 for r in res)

    def test_insufficient_samples_raise(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        with pytest.raises(CalibrationError, match="样本不足"):
            cm.calibrate(views[:2], board)  # 2 < min_samples=5

    def test_undetectable_images_raise(self, calib_cfg, board):
        cm = CalibrationManager(calib_cfg)
        blanks = [np.full((720, 1280, 3), 128, np.uint8) for _ in range(6)]
        with pytest.raises(CalibrationError, match="有效标定样本不足"):
            cm.calibrate(blanks, board)


class TestParamPersistence:
    def test_save_load_roundtrip(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        params = cm.calibrate(views, board)
        path = cm.save_params(params)
        assert path.exists()
        loaded = cm.load_params(image_size=(1280, 720))
        assert np.allclose(loaded["camera_matrix"], params["camera_matrix"])
        assert loaded["board"]["rows"] == 6
        assert loaded["sample_count"] == len(views)

    def test_missing_file_raises(self, calib_cfg):
        cm = CalibrationManager(calib_cfg)
        with pytest.raises(CalibrationError, match="不存在"):
            cm.load_params()

    def test_corrupt_file_raises(self, calib_cfg):
        cm = CalibrationManager(calib_cfg)
        cm.param_path.parent.mkdir(parents=True, exist_ok=True)
        cm.param_path.write_text("{not json!!!", encoding="utf-8")
        with pytest.raises(CalibrationError, match="损坏"):
            cm.load_params()

    def test_bad_matrix_shape_raises(self, calib_cfg):
        cm = CalibrationManager(calib_cfg)
        cm.param_path.parent.mkdir(parents=True, exist_ok=True)
        cm.param_path.write_text(
            '{"camera_matrix": [[1,0],[0,1]], "dist_coeffs": [0,0,0,0],'
            ' "image_width": 1280, "image_height": 720,'
            ' "rms_reprojection_error": 0.5}', encoding="utf-8")
        with pytest.raises(CalibrationError, match="矩阵"):
            cm.load_params()

    def test_resolution_mismatch_raises(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        cm.save_params(cm.calibrate(views, board))
        with pytest.raises(CalibrationError, match="不匹配"):
            cm.load_params(image_size=(640, 480))


class TestUndistort:
    def test_undistort_output_valid(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        params = cm.calibrate(views, board)
        out = cm.undistort(views[0], params)
        assert out.shape == views[0].shape
        assert out.dtype == views[0].dtype
        assert not np.array_equal(out, views[0])  # 确实做了畸变校正
        # 映射表缓存复用
        assert (1280, 720) in cm._map_cache

    def test_identity_undistort_is_noop(self, calib_cfg):
        cm = CalibrationManager(calib_cfg)
        img = np.random.default_rng(0).integers(
            0, 255, (100, 100, 3), dtype=np.uint8)
        params = CalibrationManager.identity_params(100, 100, "测试豁免")
        out = cm.undistort(img, params)
        assert np.array_equal(out, img)

    def test_identity_params_flagged(self):
        p = CalibrationManager.identity_params(1280, 720, "合成图无畸变")
        assert p["is_identity"] is True
        assert "无畸变" in p["notes"]


class TestQualityAndConditions:
    def test_quality_report_content(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        params = cm.calibrate(views, board)
        report = cm.quality_report(params)
        assert "RMS" in report and "残差" in report
        assert report.count("样本") >= params["valid_sample_count"]

    def test_condition_change_warnings(self, calib_cfg, board, views):
        cm = CalibrationManager(calib_cfg)
        params = cm.calibrate(views, board)
        assert cm.check_condition_change(params, (1280, 720)) == []
        warns = cm.check_condition_change(params, (640, 480))
        assert any("分辨率" in w for w in warns)
        identity = CalibrationManager.identity_params(1280, 720, "豁免")
        warns2 = cm.check_condition_change(identity, (1280, 720))
        assert any("identity" in w for w in warns2)
