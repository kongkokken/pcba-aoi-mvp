"""图像工具函数: 保存(支持中文路径)、灰度化、亮度归一化、CLAHE。"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.utils.logger import get_logger

logger = get_logger("image_utils")


def ensure_dir(path: Path | str) -> Path:
    """确保目录存在并返回 Path。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_image(image: np.ndarray, path: Path | str) -> Path:
    """保存图像。使用 imencode+tofile 兼容含中文/空格的路径。"""
    path = Path(path)
    ensure_dir(path.parent)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise IOError(f"图像编码失败: {path}")
    buf.tofile(str(path))
    logger.debug("图像已保存: %s", path)
    return path


def load_image(path: Path | str, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """读取图像(兼容中文路径),失败抛 IOError。"""
    path = Path(path)
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, flags)
    if img is None:
        raise IOError(f"无法读取图像: {path}")
    return img


def to_gray(image: np.ndarray) -> np.ndarray:
    """统一转单通道灰度图。"""
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def normalize_brightness(image: np.ndarray, target_mean: float) -> np.ndarray:
    """线性亮度归一化: 将图像均值对齐到 target_mean(容忍环境光变化)。"""
    img = image.astype(np.float32)
    cur = float(img.mean())
    if cur < 1e-3:  # 防止黑帧除零
        return image
    out = img * (target_mean / cur)
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_clahe(image: np.ndarray, clip: float = 2.0, grid: int = 8) -> np.ndarray:
    """可选 CLAHE 对比度增强(作用于 LAB 的 L 通道)。"""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_chan, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid))
    l_chan = clahe.apply(l_chan)
    return cv2.cvtColor(cv2.merge([l_chan, a, b]), cv2.COLOR_LAB2BGR)
