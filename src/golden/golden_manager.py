"""Golden Image 管理 (任务书 §十四 / Phase 8)。

存储: data/golden/<PCB_NAME>/golden.png + metadata.json
创建流程: 摄像头拍照 -> Mark 定位 -> 对齐 -> 保存标准图;
         无法自动 Mark 时允许手动传入 Mark 点(不阻塞流程)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from src.config.config_manager import ConfigManager
from src.pcb.alignment import Aligner
from src.pcb.mark_detector import MarkDetector
from src.utils.exceptions import GoldenImageError, MarkDetectionError
from src.utils.image_utils import ensure_dir, load_image, save_image
from src.utils.logger import get_logger

logger = get_logger("golden_manager")


class GoldenManager:
    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.pcb_name = str(cfg.get("pcb.name", "DEMO_PCB"))
        self.golden_dir = (cfg.data_dir()
                           / str(cfg.get("golden.dir_name", "golden"))
                           / self.pcb_name)

    @property
    def golden_path(self) -> Path:
        return self.golden_dir / "golden.png"

    @property
    def metadata_path(self) -> Path:
        return self.golden_dir / "metadata.json"

    # ---- 保存 / 加载 ----------------------------------------------------
    def save_golden(self, aligned_image: np.ndarray,
                    camera_index: int | None = None,
                    extra_meta: dict | None = None) -> Path:
        """保存已对齐的标准图 + metadata.json。"""
        if aligned_image is None or aligned_image.size == 0:
            raise GoldenImageError("Golden 图像为空,拒绝保存")
        ensure_dir(self.golden_dir)
        path = save_image(aligned_image, self.golden_path)
        meta = {
            "pcb_name": self.pcb_name,
            "image_width": int(aligned_image.shape[1]),
            "image_height": int(aligned_image.shape[0]),
            "camera_index": camera_index,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        if extra_meta:
            meta.update(extra_meta)
        self.metadata_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Golden saved: %s (%dx%d)",
                    path, meta["image_width"], meta["image_height"])
        return path

    def load_golden(self) -> tuple[np.ndarray, dict]:
        """加载 golden + metadata;缺失/尺寸不符抛 GoldenImageError。"""
        if not self.golden_path.exists():
            raise GoldenImageError(
                f"Golden 不存在: {self.golden_path}(请先 --create-golden)")
        img = load_image(self.golden_path)
        meta: dict = {}
        if self.metadata_path.exists():
            meta = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        # 尺寸必须与当前配置的标准图一致
        aligner = Aligner(self.cfg)
        w, h = aligner.aligned_size
        if img.shape[1] != w or img.shape[0] != h:
            raise GoldenImageError(
                f"Golden 尺寸 {img.shape[1]}x{img.shape[0]} 与配置标准图 {w}x{h} 不一致")
        logger.info("Golden loaded: %s", self.golden_path)
        return img, meta

    def exists(self) -> bool:
        return self.golden_path.exists()

    # ---- 创建流程 --------------------------------------------------------
    def create_golden(self, capture_image: np.ndarray,
                      camera_index: int | None = None,
                      manual_marks: np.ndarray | None = None) -> Path:
        """从一张拍摄图创建 Golden: Mark 定位 -> 对齐 -> 保存。
        manual_marks: 自动 Mark 失败时的手动点(TL,TR,BR,BL, 像素)。"""
        detector = MarkDetector(self.cfg)
        aligner = Aligner(self.cfg)
        if manual_marks is not None:
            marks = np.asarray(manual_marks, dtype=np.float64)
            logger.info("使用手动 Mark 点创建 Golden")
        else:
            try:
                marks = detector.detect(capture_image)
            except MarkDetectionError as e:
                raise GoldenImageError(
                    f"自动 Mark 定位失败({e});请提供 manual_marks 手动点") from e
        aligned = aligner.align(capture_image, marks)
        return self.save_golden(aligned, camera_index=camera_index,
                                extra_meta={"mark_points": np.round(marks, 1).tolist()})
