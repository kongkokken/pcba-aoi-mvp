"""合成棋盘格标定样本生成器(无真实标定板时的测试/演示路径,§8/§23)。

用已知真值内参 K / 畸变系数 dist 渲染多视角棋盘格:
平面纹理 -> 透视变换(随机姿态) -> initInverseRectificationMap 正向畸变。
生成的样本喂给 cv2.calibrateCamera,可回收接近真值的参数,
从而真实检验 CalibrationManager 的求解/残差/校验链路。

真实相机标定仍为 PENDING(需要实体标定板),见 README 五级测试报告。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.calibration.calibration import BoardSpec

# 真值内参(合成相机): 测试用,仅用于生成样本与比对回收精度
TRUE_K = np.array([[900.0, 0.0, 640.0],
                   [0.0, 900.0, 360.0],
                   [0.0, 0.0, 1.0]])
TRUE_DIST = np.array([-0.25, 0.08, 0.0, 0.0, 0.0])  # 轻微桶形畸变


def _flat_chessboard(board: BoardSpec, px_per_sq: int = 40) -> np.ndarray:
    """渲染平面棋盘格纹理(含外框,尺寸 = (cols+1)sq x (rows+1)sq)。"""
    w, h = (board.cols + 1) * px_per_sq, (board.rows + 1) * px_per_sq
    img = np.full((h, w), 255, np.uint8)
    for r in range(board.rows + 1):
        for c in range(board.cols + 1):
            if (r + c) % 2 == 0:
                cv2.rectangle(img, (c * px_per_sq, r * px_per_sq),
                              ((c + 1) * px_per_sq, (r + 1) * px_per_sq), 0, -1)
    return img


def generate_views(board: BoardSpec, n_views: int = 10,
                   width: int = 1280, height: int = 720,
                   seed: int = 7) -> list[np.ndarray]:
    """生成 n_views 张带已知畸变的棋盘格样本图(覆盖中心/四边/四角)。

    用真实 3D 投影(cv2.projectPoints,显著离面旋转)计算板面四角在图像中的
    位置再 warp 纹理 —— 焦距只能透过平面在不同倾角下的透视形变观测,
    近正视的小扰动视图无法恢复焦距(实测 fx 漂到 3 倍真值)。
    """
    rng = np.random.default_rng(seed)
    texture = _flat_chessboard(board)
    th, tw = texture.shape
    src = np.float32([[0, 0], [tw, 0], [tw, th], [0, th]])

    # 板面 3D 四角(单位: 标定板格数 * square_size, Z=0 平面)
    bw, bh = board.cols * board.square_size, board.rows * board.square_size
    board_corners = np.float32([[0, 0, 0], [bw, 0, 0],
                                [bw, bh, 0], [0, bh, 0]])
    # 姿态: (绕X倾角°, 绕Y倾角°, 中心归一化位置) —— 覆盖中心/四角/四边
    poses = [(25, -20, 0.50, 0.50), (-30, 15, 0.28, 0.28),
             (20, 25, 0.72, 0.28), (-20, -25, 0.72, 0.72),
             (30, 10, 0.28, 0.72), (0, 30, 0.50, 0.22),
             (0, -30, 0.50, 0.78), (35, 0, 0.22, 0.50),
             (-35, 0, 0.78, 0.50), (15, 15, 0.50, 0.50)]

    # 畸变映射: 输出图(畸变后)每像素 -> 无畸变图源坐标
    mapx, mapy = cv2.initInverseRectificationMap(
        TRUE_K, TRUE_DIST, None, TRUE_K, (width, height), cv2.CV_32FC1)

    views: list[np.ndarray] = []
    for i in range(n_views):
        ax, ay, cx, cy = poses[i % len(poses)]
        ax += float(rng.uniform(-4, 4))
        ay += float(rng.uniform(-4, 4))
        rvec = np.deg2rad([ax, ay, float(rng.uniform(-5, 5))])
        # 平移: 使板心落在 (cx,cy) 处,距离按板宽估计
        dist_z = 900.0  # 焦距量级的工作距离
        tvec = np.array([cx * 2 - 1, cy * 2 - 1, 0.0]) * 250.0
        tvec[2] = dist_z + float(rng.uniform(-80, 80))
        proj, _ = cv2.projectPoints(board_corners, rvec, tvec,
                                    TRUE_K, None)
        dst = proj.reshape(-1, 2)
        M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
        view = cv2.warpPerspective(texture, M, (width, height),
                                   borderValue=180)
        distorted = cv2.remap(view, mapx, mapy, cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=180)
        views.append(cv2.cvtColor(distorted, cv2.COLOR_GRAY2BGR))
    return views
