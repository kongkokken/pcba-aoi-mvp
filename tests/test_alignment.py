"""对齐独立点重投影评估测试 (融合版 §11.1):
留出一点拟合、投影该点,误差独立可信;异常点必须反映在留出误差上。"""
from __future__ import annotations

import numpy as np
import pytest

from src.pcb.alignment import leave_one_out_error
from src.utils.exceptions import AlignmentError

# 标准 Mark 点 (px): TL,TR,BR,BL
CANONICAL = np.array([[48, 48], [752, 48], [752, 512], [48, 512]],
                     dtype=np.float64)


class TestLeaveOneOut:
    def test_pure_affine_gives_near_zero(self):
        """检测点与标准点只差一个仿射变换时,留出误差应接近 0。"""
        detected = CANONICAL * 1.2 + [100, 50]   # 缩放+平移
        max_err, mean_err = leave_one_out_error(detected, CANONICAL)
        # estimateAffine2D 为 float32 计算,容差放宽到 1e-3 px
        assert max_err == pytest.approx(0.0, abs=1e-3)
        assert mean_err == pytest.approx(0.0, abs=1e-3)

    def test_outlier_point_is_exposed(self):
        """一个 Mark 检测偏移 20px: 留出评估必须暴露它(拟合内残差会掩盖)。"""
        detected = CANONICAL.copy()
        detected[2] += [20.0, 0.0]   # BR 点偏移
        max_err, mean_err = leave_one_out_error(detected, CANONICAL)
        assert max_err > 10.0        # 偏移点留出时误差大
        assert mean_err > 1.0

    def test_too_few_points_returns_zero(self):
        max_err, mean_err = leave_one_out_error(CANONICAL[:3], CANONICAL[:3])
        assert (max_err, mean_err) == (0.0, 0.0)

    def test_shape_mismatch_raises(self):
        with pytest.raises(AlignmentError):
            leave_one_out_error(CANONICAL, CANONICAL[:3])
