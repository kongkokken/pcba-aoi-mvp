"""OCR 引擎预留接口 (任务书 §三十五)。

第一阶段不实现 OCR;接口预留给未来 PaddleOCR 接入:
- Excel 中 OCR=1 的元件,读取 ExpectedValue
- recognize(image, roi) -> 识别文本
- 最终 Expected vs Detected 判定
"""
from __future__ import annotations

import numpy as np

from src.roi.roi import Roi


class OcrEngine:
    """OCR 接口基类(预留)。默认实现返回 None = 未启用。"""

    def recognize(self, image: np.ndarray, roi: Roi) -> str | None:
        """识别 ROI 区域文本。第一阶段返回 None。"""
        return None


class PaddleOcrEngine(OcrEngine):
    """未来 PaddleOCR 接入点(当前未实现,实例化即提示)。"""

    def __init__(self) -> None:
        raise NotImplementedError(
            "PaddleOCR 未接入(第一阶段预留接口);请实现 recognize() 后再启用")
