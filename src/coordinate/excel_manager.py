"""坐标文件解析与语义确认 (融合版 §10)。

支持格式: .xlsx / .xls(xlrd) / .csv(§10.1)。
可追溯性: 每条记录保留源文件、源工作表、源行号和原始字段值(raw)。
字段映射: config coordinate_import.field_mapping (canonical -> 源列名),
避免把客户不同格式硬编码进程序。

坐标语义门控(§10.2,不可违反):
- 绝不因字段名是 X/Y 就默认是绝对 PCB 坐标
- CoordinateMeaningConfirmed=NO(或空/无法识别) -> coord_confirmed=False,
  保留原始值并在 notes 列出待确认问题;ROI 层据此标 UNCONFIGURED (§12.9)
- 不得用猜测值补齐坐标或封装尺寸
- 语义列缺失的旧格式文件: 回退全局 coordinate.coordinate_meaning_confirmed,
  并在 notes 记录该回退(可追溯)

配置表(§10.3): 自动创建 data/pcb_config.xlsx,Components 工作表,
基础 16 字段 + 扩展字段(PartNumber/X_Offset/Y_Offset/TeachX/TeachY/
TeachAngle/CoordinateSystem/CoordinateMeaningConfirmed/BoardID/SourceFile/
SourceSheet/SourceRow/Notes)。字段含义/单位/默认值见 README「坐标配置表」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.config_manager import ConfigManager
from src.synthetic.synthetic_pcb_generator import SYNTHETIC_COMPONENTS
from src.utils.exceptions import ExcelConfigError
from src.utils.logger import get_logger

logger = get_logger("excel_manager")

# §10.3 基础字段(任务书规定顺序)
BASE_COLUMNS = ["Ref", "Type", "X", "Y", "Width", "Height", "Angle",
                "Inspect", "OCR", "ExpectedValue", "Mask", "Algorithm",
                "PositionTolerance", "SizeTolerance", "AngleTolerance",
                "RoiExpand"]

# §10.3 扩展字段(适配真实坐标报告;原始坐标与确认后绝对坐标分开保存)
EXTENDED_COLUMNS = ["PartNumber", "X_Offset", "Y_Offset",
                    "TeachX", "TeachY", "TeachAngle",
                    "CoordinateSystem", "CoordinateMeaningConfirmed",
                    "BoardID", "SourceFile", "SourceSheet", "SourceRow",
                    "Notes"]

COLUMNS = BASE_COLUMNS + EXTENDED_COLUMNS

# 可识别为"已确认"的取值(其余一律按未确认处理,保守原则)
_CONFIRMED_TOKENS = {"yes", "y", "true", "1", "confirmed", "是"}


@dataclass
class Component:
    """一个元件的坐标记录(单位 mm / 度;扩展字段见 §10.3)。

    coord_confirmed=False 的记录不得用于最终 ROI 定位 (§10.2)。
    raw 保留原始字段值,source_* 保留来源,确保可追溯。
    """
    ref: str
    type: str
    x: float                 # 确认后的绝对 PCB 坐标 (mm)
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
    # ---- §10.3 扩展(均有默认值,旧格式文件可缺省) ----
    part_number: str = ""            # 物料编号
    x_offset: float = 0.0            # 原始偏移量(与绝对坐标分开保存)
    y_offset: float = 0.0
    teach_x: float | None = None     # 示教值(缺失为 None,不猜测补齐)
    teach_y: float | None = None
    teach_angle: float | None = None
    coordinate_system: str = ""      # 坐标系声明(如 pcb_absolute_mm)
    coord_confirmed: bool = False    # CoordinateMeaningConfirmed
    board_id: str = "BOARD_1"
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    notes: str = ""
    raw: dict = field(default_factory=dict, repr=False)


def default_rows() -> pd.DataFrame:
    """默认模板行: 合成板元件表(自建几何,语义由生成器定义 -> YES)+ 示例字段值。

    诚实性说明: 合成模板的 CoordinateMeaningConfirmed=YES 合法 —— 坐标系
    (绝对坐标/mm/左上原点/Y向下)由 synthetic_pcb_generator 明确定义;
    真实坐标报告必须由人工逐字段确认后自行置 YES (§10.2)。
    """
    meta = {
        ("R", False): dict(ExpectedValue="10K", Algorithm="Geometry"),
        ("C", True): dict(ExpectedValue="104", Algorithm="OCR"),
        ("IC", True): dict(ExpectedValue="STM32", Algorithm="OCR"),
    }
    rows = []
    for idx, (ref, ctype, x, y, w, h, ang) in enumerate(SYNTHETIC_COMPONENTS):
        m = meta.get((ctype, ctype != "R"), meta[("R", False)])
        rows.append({
            "Ref": ref, "Type": ctype, "X": x, "Y": y,
            "Width": w, "Height": h, "Angle": ang,
            "Inspect": 1, "OCR": 1 if ctype != "R" else 0,
            "ExpectedValue": m["ExpectedValue"], "Mask": 1,
            "Algorithm": m["Algorithm"],
            "PositionTolerance": 0.5, "SizeTolerance": "20%",
            "AngleTolerance": 10, "RoiExpand": 0.2,
            "PartNumber": "", "X_Offset": 0.0, "Y_Offset": 0.0,
            "TeachX": x, "TeachY": y, "TeachAngle": ang,
            "CoordinateSystem": "pcb_absolute_mm",
            "CoordinateMeaningConfirmed": "YES",
            "BoardID": "BOARD_1",
            "SourceFile": "", "SourceSheet": "", "SourceRow": idx + 2,
            "Notes": "合成模板(自建几何,语义已定义)",
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def _parse_confirmed(value) -> bool:
    """CoordinateMeaningConfirmed 解析: 仅明确肯定取值算确认(保守)。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in _CONFIRMED_TOKENS


def _opt_float(value) -> float | None:
    """可选数值: 空值 -> None(不猜测补齐, §10.2)。"""
    if value is None or (isinstance(value, float) and pd.isna(value)) \
            or str(value).strip() == "":
        return None
    return float(value)


class ExcelManager:
    def __init__(self, cfg: ConfigManager) -> None:
        self.cfg = cfg
        self.path: Path = cfg.data_dir() / "pcb_config.xlsx"
        self.sheet_name = str(cfg.get("coordinate_import.sheet_name",
                                      "Components"))
        self.field_mapping: dict = dict(
            cfg.get("coordinate_import.field_mapping", {}) or {})
        # 语义列缺失时的回退(旧格式文件);记录进 notes 保证可追溯
        self.global_confirmed = bool(
            cfg.get("coordinate.coordinate_meaning_confirmed", False))

    # ---- 模板 (§10.3) -----------------------------------------------------
    def create_template(self, overwrite: bool = False) -> Path:
        """自动创建 Excel 模板(基础+扩展字段);已存在且不覆盖时直接返回。"""
        if self.path.exists() and not overwrite:
            logger.info("Excel 已存在,跳过创建: %s", self.path)
            return self.path
        df = default_rows()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(self.path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Components", index=False)
        logger.info("Excel 模板已创建: %s (%d 行, %d 字段)",
                    self.path, len(df), len(df.columns))
        return self.path

    # ---- 读取 (§10.1) ------------------------------------------------------
    def _read_table(self, p: Path) -> tuple[pd.DataFrame, str]:
        """按扩展名读取表格,返回 (DataFrame, 实际工作表名)。"""
        suffix = p.suffix.lower()
        try:
            if suffix == ".csv":
                for enc in ("utf-8-sig", "gbk"):
                    try:
                        return pd.read_csv(p, encoding=enc), ""
                    except UnicodeDecodeError:
                        continue
                raise ExcelConfigError(f"CSV 编码无法识别(已试 utf-8-sig/gbk): {p}")
            if suffix in (".xlsx", ".xlsm"):
                xl = pd.ExcelFile(p, engine="openpyxl")
            elif suffix == ".xls":
                xl = pd.ExcelFile(p, engine="xlrd")
            else:
                raise ExcelConfigError(
                    f"不支持的坐标文件格式: {p.suffix}(支持 .xlsx/.xls/.csv)")
            sheet = self.sheet_name if self.sheet_name in xl.sheet_names \
                else xl.sheet_names[0]
            if sheet != self.sheet_name:
                logger.warning("工作表 %s 不存在,回退第一个工作表 %s",
                               self.sheet_name, sheet)
            return xl.parse(sheet), sheet
        except ExcelConfigError:
            raise
        except Exception as e:  # pandas/openpyxl/xlrd 异常类型多样,统一封装
            raise ExcelConfigError(f"坐标文件读取失败: {p}: {e}") from e

    def _apply_field_mapping(self, df: pd.DataFrame) -> pd.DataFrame:
        """字段映射(§10.1): canonical <- 源列名,避免硬编码客户格式。"""
        df = df.copy()
        for canonical, source in self.field_mapping.items():
            if source in df.columns and canonical not in df.columns:
                df[canonical] = df[source]
                logger.info("字段映射: %s <- %s", canonical, source)
        return df

    def load_components(self, path: Path | str | None = None) -> list[Component]:
        """读取并校验元件表,非法即抛 ExcelConfigError(§10.1 检查清单)。"""
        p = Path(path) if path else self.path
        if not p.exists():
            raise ExcelConfigError(f"坐标文件不存在: {p}(请先 create_template)")
        df, sheet = self._read_table(p)
        df = self._apply_field_mapping(df)

        missing = [c for c in BASE_COLUMNS if c not in df.columns]
        if missing:
            raise ExcelConfigError(
                f"坐标文件缺少必需字段: {missing}"
                f"(可用 coordinate_import.field_mapping 映射客户列名)")
        if df.empty:
            raise ExcelConfigError("坐标文件无元件行")
        has_semantics_col = "CoordinateMeaningConfirmed" in df.columns
        if not has_semantics_col:
            logger.warning("语义列 CoordinateMeaningConfirmed 缺失,回退全局配置"
                           " coordinate_meaning_confirmed=%s",
                           self.global_confirmed)

        components: list[Component] = []
        for i, row in df.iterrows():
            excel_row = i + 2  # 表头占第 1 行
            raw = {str(k): (None if pd.isna(v) else v)
                   for k, v in row.to_dict().items()}
            try:
                x = float(row["X"])
                y = float(row["Y"])
            except (TypeError, ValueError) as e:
                raise ExcelConfigError(
                    f"第 {excel_row} 行坐标为空或非法: {e}"
                    "(不得猜测补齐,请修正源文件)") from e
            if not (np.isfinite(x) and np.isfinite(y)):
                raise ExcelConfigError(
                    f"第 {excel_row} 行坐标为空或非法: X={row['X']}, "
                    f"Y={row['Y']}(不得猜测补齐,请修正源文件)")
            try:
                angle = float(row["Angle"])
                comp = Component(
                    ref=str(row["Ref"]).strip(),
                    type=str(row["Type"]).strip(),
                    x=x, y=y,
                    width=float(row["Width"]), height=float(row["Height"]),
                    angle=angle,
                    inspect=bool(int(row["Inspect"])),
                    ocr=bool(int(row["OCR"])),
                    expected_value="" if pd.isna(row["ExpectedValue"])
                    else str(row["ExpectedValue"]),
                    mask=bool(int(row["Mask"])),
                    algorithm=str(row["Algorithm"]).strip(),
                    position_tolerance=float(row["PositionTolerance"]),
                    size_tolerance=str(row["SizeTolerance"]),
                    angle_tolerance=float(row["AngleTolerance"]),
                    roi_expand=float(row["RoiExpand"]),
                )
            except (TypeError, ValueError) as e:
                raise ExcelConfigError(f"第 {excel_row} 行数据非法: {e}") from e
            if not comp.ref or comp.ref.lower() == "nan":
                raise ExcelConfigError(f"第 {excel_row} 行 Ref 为空")
            if comp.width <= 0 or comp.height <= 0:
                raise ExcelConfigError(f"第 {excel_row} 行 {comp.ref} 尺寸非法")
            if abs(angle) > 360:
                raise ExcelConfigError(
                    f"第 {excel_row} 行 {comp.ref} 角度异常: {angle}(|angle|>360)")

            # ---- §10.3 扩展字段 + §10.1 可追溯性 ----
            comp.part_number = self._opt_str(row, "PartNumber")
            comp.x_offset = _opt_float(row.get("X_Offset")) or 0.0
            comp.y_offset = _opt_float(row.get("Y_Offset")) or 0.0
            comp.teach_x = _opt_float(row.get("TeachX"))
            comp.teach_y = _opt_float(row.get("TeachY"))
            comp.teach_angle = _opt_float(row.get("TeachAngle"))
            comp.coordinate_system = self._opt_str(row, "CoordinateSystem")
            comp.board_id = self._opt_str(row, "BoardID") or "BOARD_1"
            comp.notes = self._opt_str(row, "Notes")
            comp.source_file = p.name
            comp.source_sheet = sheet
            comp.source_row = excel_row
            comp.raw = raw
            # ---- §10.2 语义门控 ----
            if has_semantics_col:
                comp.coord_confirmed = _parse_confirmed(
                    row.get("CoordinateMeaningConfirmed"))
                if not comp.coord_confirmed:
                    comp.notes = (comp.notes + ";" if comp.notes else "") \
                        + "待确认: 坐标语义/单位/原点/方向未确认" \
                          "(CoordinateMeaningConfirmed!=YES)"
            else:
                comp.coord_confirmed = self.global_confirmed
                comp.notes = (comp.notes + ";" if comp.notes else "") \
                    + f"语义列缺失,回退全局确认状态={self.global_confirmed}"
            components.append(comp)

        refs = [c.ref for c in components]
        dups = sorted({r for r in refs if refs.count(r) > 1})
        if dups:
            raise ExcelConfigError(f"Ref 重复: {dups}")
        n_unconf = sum(1 for c in components if not c.coord_confirmed)
        if n_unconf:
            logger.warning("坐标语义未确认元件: %d/%d(ROI 将标 UNCONFIGURED)",
                           n_unconf, len(components))
        logger.info("坐标文件加载完成: %d 个元件 (%s/%s)",
                    len(components), p.name, sheet or "(csv)")
        return components

    @staticmethod
    def _opt_str(row, key: str) -> str:
        v = row.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()
