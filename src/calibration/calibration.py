"""相机内参标定与镜头畸变校正 (融合版 §8,正式模块)。

职责:
1. 标定样本检测(棋盘格角点)+ cv2.calibrateCamera 求解
2. 参数保存/加载到 data/calibration/(JSON,含矩阵/畸变系数/分辨率/标定板信息/
   日期/RMS/每样本残差/样本数/软件版本/备注)
3. 加载时校验: 文件完整性、矩阵形状、数值有效性、分辨率匹配
4. 畸变校正: initUndistortRectifyMap + remap(映射表按图像尺寸缓存复用)
5. 质量报告: RMS + 每样本残差 + 覆盖率(不只看 RMS)
6. identity 参数: 用于无畸变合成数据等有文档化理由的豁免场景

注意(§8 两类标定之分): 本模块只处理镜头成像几何畸变,
不代表 PCB 平面坐标已经准确映射(那是 alignment/coordinate 的职责)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.config.config_manager import ConfigManager
from src.utils.exceptions import CalibrationError
from src.utils.logger import get_logger

logger = get_logger("calibration")

SOFTWARE_VERSION = "PCBA_AOI_MVP 2.0"
PARAM_FORMAT_VERSION = "1.0"


@dataclass
class BoardSpec:
    """标定板规格(内角点布局)。"""
    type: str = "chessboard"
    rows: int = 6          # 内角点行数
    cols: int = 9          # 内角点列数
    square_size: float = 25.0
    unit: str = "mm"

    @classmethod
    def from_config(cls, cfg: ConfigManager) -> "BoardSpec":
        return cls(
            type=str(cfg.get("calibration.board.type", "chessboard")),
            rows=int(cfg.get("calibration.board.rows", 6)),
            cols=int(cfg.get("calibration.board.cols", 9)),
            square_size=float(cfg.get("calibration.board.square_size", 25.0)),
            unit=str(cfg.get("calibration.board.unit", "mm")),
        )


class CalibrationManager:
    """标定参数生命周期: 采集求解 -> 保存 -> 加载校验 -> 畸变校正。"""

    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.require_resolution_match = bool(
            cfg.get("calibration.require_resolution_match", True))
        self.min_samples = int(cfg.get("calibration.min_samples", 5))
        self._map_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    @property
    def param_path(self) -> Path:
        p = Path(str(self.cfg.get(
            "calibration.parameter_file",
            "data/calibration/camera_calibration.json")))
        return p if p.is_absolute() else self.cfg.root / p

    # ---- 1. 标定求解 -----------------------------------------------------
    def detect_corners(self, image: np.ndarray,
                       board: BoardSpec) -> np.ndarray | None:
        """单张图角点检测,失败返回 None(不抛错,由上层统计成功率)。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        ok, corners = cv2.findChessboardCorners(gray, (board.cols, board.rows))
        if not ok:
            return None
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
        return cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)

    def calibrate(self, images: list[np.ndarray],
                  board: BoardSpec | None = None) -> dict:
        """从样本图像求解内参。样本不足/全部检测失败抛 CalibrationError。"""
        board = board or BoardSpec.from_config(self.cfg)
        if len(images) < self.min_samples:
            raise CalibrationError(
                f"标定样本不足: {len(images)} < min_samples={self.min_samples}"
                "(不得仅凭单张/少量图片声称标定可靠, §8.1)")
        objp = np.zeros((board.rows * board.cols, 3), np.float32)
        objp[:, :2] = np.mgrid[0:board.cols, 0:board.rows].T.reshape(-1, 2)
        objp *= board.square_size

        objpoints, imgpoints, per_image = [], [], []
        img_size: tuple[int, int] | None = None
        for idx, img in enumerate(images):
            if img is None or img.size == 0:
                per_image.append({"index": idx, "detected": False,
                                  "reason": "empty"})
                continue
            size = (img.shape[1], img.shape[0])
            img_size = img_size or size
            if size != img_size:
                per_image.append({"index": idx, "detected": False,
                                  "reason": "size_mismatch"})
                continue
            corners = self.detect_corners(img, board)
            if corners is None:
                per_image.append({"index": idx, "detected": False,
                                  "reason": "corners_not_found"})
                continue
            objpoints.append(objp)
            imgpoints.append(corners)
            per_image.append({"index": idx, "detected": True})

        n_ok = len(objpoints)
        if n_ok < self.min_samples:
            raise CalibrationError(
                f"有效标定样本不足: {n_ok}/{len(images)} 张检测成功, "
                f"需要 >= {self.min_samples}")
        assert img_size is not None
        rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
            objpoints, imgpoints, img_size, None, None)

        # 每样本重投影残差(§8.4: 不得只看 RMS)
        residuals: list[float] = []
        for i, (obj, rvec, tvec) in enumerate(zip(objpoints, rvecs, tvecs)):
            proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
            # OpenCV 5.0 对 cv2.norm 类型一致性敏感,统一转 float64 计算
            diff = (imgpoints[i].reshape(-1, 2).astype(np.float64)
                    - proj.reshape(-1, 2).astype(np.float64))
            err = float(np.linalg.norm(diff, axis=1).mean())
            residuals.append(round(err, 4))
        # 把残差写回检测成功的样本记录
        ok_iter = iter(residuals)
        for rec in per_image:
            if rec["detected"]:
                rec["residual_px"] = next(ok_iter)

        params = {
            "format_version": PARAM_FORMAT_VERSION,
            "camera_matrix": np.asarray(K).tolist(),
            "dist_coeffs": np.asarray(dist).ravel().tolist(),
            "image_width": img_size[0],
            "image_height": img_size[1],
            "board": {"type": board.type, "rows": board.rows,
                      "cols": board.cols, "square_size": board.square_size,
                      "unit": board.unit},
            "calibration_date": datetime.now().isoformat(timespec="seconds"),
            "rms_reprojection_error": round(float(rms), 4),
            "sample_count": len(images),
            "valid_sample_count": n_ok,
            "per_image": per_image,
            "software_version": SOFTWARE_VERSION,
            "opencv_version": cv2.__version__,
            "is_identity": False,
            "camera_id": f"index_{self.cfg.get('camera.index', 0)}",
            "notes": "",
        }
        logger.info("Calibration performed: RMS=%.4f px, 有效样本 %d/%d",
                    rms, n_ok, len(images))
        return params

    # ---- 2. 保存 / 加载 ----------------------------------------------------
    def save_params(self, params: dict) -> Path:
        path = self.param_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(params, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        logger.info("Calibration saved: %s", path)
        return path

    def load_params(self, image_size: tuple[int, int] | None = None) -> dict:
        """加载并校验参数。失败抛 CalibrationError(损坏/缺键/形状错/分辨率不符)。"""
        path = self.param_path
        if not path.exists():
            raise CalibrationError(f"标定参数文件不存在: {path}")
        try:
            params = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CalibrationError(f"标定文件损坏(非合法 JSON): {path}: {e}") from e
        self.validate_params(params, image_size)
        logger.info("Calibration loaded: %s (RMS=%s, 样本=%s)",
                    path, params.get("rms_reprojection_error"),
                    params.get("valid_sample_count"))
        return params

    def validate_params(self, params: dict,
                        image_size: tuple[int, int] | None = None) -> None:
        required = ["camera_matrix", "dist_coeffs", "image_width",
                    "image_height", "rms_reprojection_error"]
        missing = [k for k in required if k not in params]
        if missing:
            raise CalibrationError(f"标定参数缺少字段: {missing}")
        K = np.asarray(params["camera_matrix"], dtype=np.float64)
        if K.shape != (3, 3) or not np.all(np.isfinite(K)):
            raise CalibrationError(f"相机矩阵形状/数值非法: {K.shape}")
        dist = np.asarray(params["dist_coeffs"], dtype=np.float64).ravel()
        if dist.size < 4 or not np.all(np.isfinite(dist)):
            raise CalibrationError(f"畸变系数非法: 长度 {dist.size}")
        if K[0, 0] <= 0 or K[1, 1] <= 0:
            raise CalibrationError("焦距非正数,参数无效")
        if self.require_resolution_match and image_size is not None:
            if (int(params["image_width"]), int(params["image_height"])) != \
                    (int(image_size[0]), int(image_size[1])):
                raise CalibrationError(
                    f"图像分辨率 {image_size} 与标定分辨率 "
                    f"({params['image_width']},{params['image_height']}) 不匹配,"
                    f"需评估/重新标定 (§8.2)")

    def exists(self) -> bool:
        return self.param_path.exists()

    def check_condition_change(self, params: dict,
                               image_size: tuple[int, int]) -> list[str]:
        """关键条件变化提醒(§8.2): 分辨率不符/identity 用于真实源等。"""
        warnings: list[str] = []
        if (int(params.get("image_width", 0)),
                int(params.get("image_height", 0))) != tuple(image_size):
            warnings.append("图像分辨率与标定分辨率不一致,应评估或重新标定")
        if params.get("is_identity"):
            warnings.append("当前参数为 identity 豁免(无畸变假设),"
                            "更换相机/镜头/对焦/工作距离后必须重新标定")
        return warnings

    # ---- 3. 畸变校正 --------------------------------------------------------
    def _build_maps(self, params: dict,
                    size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        if size not in self._map_cache:
            K = np.asarray(params["camera_matrix"], dtype=np.float64)
            dist = np.asarray(params["dist_coeffs"], dtype=np.float64)
            m1, m2 = cv2.initUndistortRectifyMap(
                K, dist, None, K, size, cv2.CV_32FC1)
            self._map_cache[size] = (m1, m2)
        return self._map_cache[size]

    def undistort(self, image: np.ndarray, params: dict) -> np.ndarray:
        """畸变校正(复用映射表)。identity 参数时直接返回原图。"""
        if params.get("is_identity"):
            logger.debug("Undistort skipped: identity 参数 (%s)",
                         params.get("notes", ""))
            return image
        size = (image.shape[1], image.shape[0])
        self.validate_params(params, size)
        m1, m2 = self._build_maps(params, size)
        out = cv2.remap(image, m1, m2, cv2.INTER_LINEAR)
        logger.info("Undistortion completed: %dx%d", size[0], size[1])
        return out

    # ---- 4. identity 豁免 ---------------------------------------------------
    @staticmethod
    def identity_params(width: int, height: int, reason: str) -> dict:
        """无畸变豁免参数(§8: 跳过必须有文档化理由)。
        用于: 合成图像按构造无镜头畸变。不得用于真实相机量产放行。"""
        f = float(max(width, height))
        return {
            "format_version": PARAM_FORMAT_VERSION,
            "camera_matrix": [[f, 0.0, width / 2], [0.0, f, height / 2],
                              [0.0, 0.0, 1.0]],
            "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
            "image_width": int(width), "image_height": int(height),
            "board": None,
            "calibration_date": datetime.now().isoformat(timespec="seconds"),
            "rms_reprojection_error": 0.0,
            "sample_count": 0, "valid_sample_count": 0,
            "per_image": [],
            "software_version": SOFTWARE_VERSION,
            "opencv_version": cv2.__version__,
            "is_identity": True,
            "camera_id": "synthetic",
            "notes": reason,
        }

    # ---- 5. 质量报告 ---------------------------------------------------------
    @staticmethod
    def quality_report(params: dict) -> str:
        """RMS + 每样本残差 + 覆盖情况(§8.4 不允许只报 RMS)。"""
        if params.get("is_identity"):
            return f"identity 豁免参数: {params.get('notes', '')}"
        lines = [f"RMS 重投影误差: {params.get('rms_reprojection_error')} px",
                 f"样本: 有效 {params.get('valid_sample_count')}"
                 f"/{params.get('sample_count')}"]
        for rec in params.get("per_image", []):
            if rec.get("detected"):
                lines.append(f"  样本{rec['index']}: 残差 "
                             f"{rec.get('residual_px')} px")
            else:
                lines.append(f"  样本{rec['index']}: 检测失败 "
                             f"({rec.get('reason')})")
        return "\n".join(lines)
