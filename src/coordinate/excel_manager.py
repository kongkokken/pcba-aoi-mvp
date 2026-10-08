"""Excel 元件坐标管理 (任务书 §十一 / Phase 5)。

- create_template(): 程序自动创建 data/pcb_config.xlsx (Sheet: Components),
  字段与任务书一致;行数据来自合成板元件表(坐标不写死在加载逻辑里)。
- load_components(): 读取并校验,非法行抛 ExcelConfigError。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.config.config_manager import ConfigManager
from src.synthetic.synthetic_pcb_generator import SYNTHETIC_COMPONENTS
from src.utils.exceptions import ExcelConfigError
from src.utils.logger import get_logger

logger = get_logger("excel_manager")

# 任务书规定的字段顺序
COLUMNS = ["Ref", "Type", "X", "Y", "Width", "Height", "Angle",
           "Inspect", "OCR", "ExpectedValue", "Mask", "Algorithm",
           "PositionTolerance", "SizeTolerance", "AngleTolerance", "RoiExpand"]


@dataclass
class Component:
    """一个元件的坐标记录(单位 mm / 度)。"""
    ref: str
    type: str
    x: float
    y: float
    width: float
    height: float
    angle: float
    inspect: bool
    ocr: bool
    expected_value: str
    mask: bool
    algorithm: str
    position_tolerance: float
    size_tolerance: str
    angle_tolerance: float
    roi_expand: float


def default_rows() -> pd.DataFrame:
    """默认模板行: 合成板元件表 + 任务书示例字段值。"""
    meta = {
        ("R", False): dict(ExpectedValue="10K", Algorithm="Geometry"),
        ("C", True): dict(ExpectedValue="104", Algorithm="OCR"),
        ("IC", True): dict(ExpectedValue="STM32", Algorithm="OCR"),
    }
    rows = []
    for ref, ctype, x, y, w, h, ang in SYNTHETIC_COMPONENTS:
        m = meta.get((ctype, ctype != "R"), meta[("R", False)])
        rows.append({
            "Ref": ref, "Type": ctype, "X": x, "Y": y,
            "Width": w, "Height": h, "Angle": ang,
            "Inspect": 1, "OCR": 1 if ctype != "R" else 0,
            "ExpectedValue": m["ExpectedValue"], "Mask": 1,
            "Algorithm": m["Algorithm"],
            "PositionTolerance": 0.5, "SizeTolerance": "20%",
            "AngleTolerance": 10, "RoiExpand": 0.2,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


class ExcelManager:
    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.path: Path = cfg.data_dir() / "pcb_config.xlsx"

    def create_template(self, overwrite: bool = False) -> Path:
        """自动创建 Excel 模板;已存在且不覆盖时直接返回。"""
        if self.path.exists() and not overwrite:
            logger.info("Excel 已存在,跳过创建: %s", self.path)
            return self.path
        df = default_rows()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(self.path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Components", index=False)
        logger.info("Excel 模板已创建: %s (%d 行)", self.path, len(df))
        return self.path

    def load_components(self, path: Path | str | None = None) -> list[Component]:
        """读取并校验元件表,非法即抛 ExcelConfigError。"""
        p = Path(path) if path else self.path
        if not p.exists():
            raise ExcelConfigError(f"Excel 不存在: {p}(请先 create_template)")
        try:
            df = pd.read_excel(p, sheet_name="Components")
        except Exception as e:  # pandas/openpyxl 异常类型多样,统一封装
            raise ExcelConfigError(f"Excel 读取失败: {p}: {e}") from e

        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ExcelConfigError(f"Excel 缺少字段: {missing}")
        if df.empty:
            raise ExcelConfigError("Excel 无元件行")

        components: list[Component] = []
        for i, row in df.iterrows():
            try:
                comp = Component(
                    ref=str(row["Ref"]).strip(),
                    type=str(row["Type"]).strip(),
                    x=float(row["X"]), y=float(row["Y"]),
                    width=float(row["Width"]), height=float(row["Height"]),
                    angle=float(row["Angle"]),
                    inspect=bool(int(row["Inspect"])),
                    ocr=bool(int(row["OCR"])),
                    expected_value=str(row["ExpectedValue"]),
                    mask=bool(int(row["Mask"])),
                    algorithm=str(row["Algorithm"]).strip(),
                    position_tolerance=float(row["PositionTolerance"]),
                    size_tolerance=str(row["SizeTolerance"]),
                    angle_tolerance=float(row["AngleTolerance"]),
                    roi_expand=float(row["RoiExpand"]),
                )
            except (TypeError, ValueError) as e:
                raise ExcelConfigError(f"第 {i + 2} 行数据非法: {e}") from e
            if not comp.ref:
                raise ExcelConfigError(f"第 {i + 2} 行 Ref 为空")
            if comp.width <= 0 or comp.height <= 0:
                raise ExcelConfigError(f"第 {i + 2} 行 {comp.ref} 尺寸非法")
            components.append(comp)

        refs = [c.ref for c in components]
        if len(set(refs)) != len(refs):
            raise ExcelConfigError(f"Ref 重复: {refs}")
        logger.info("Excel 加载完成: %d 个元件 (%s)", len(components), p)
        return components
