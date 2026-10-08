"""检测结果数据结构 (任务书 §二十)。

InspectionResult: 一次完整检测的结构化结果,可序列化为 JSON。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class DefectRecord:
    """单个缺陷记录(JSON 输出字段与任务书一致)。"""
    type: str
    ref: str           # 关联元件位号(非元件区缺陷为 "")
    x: int
    y: int
    width: int
    height: int
    area: float
    score: float
    message: str


@dataclass
class InspectionResult:
    pcb_name: str
    timestamp: str
    overall_status: str          # PASS / NG / ERROR
    alignment_status: str        # OK / FAILED
    components_total: int
    components_pass: int
    components_ng: int
    solder_defect_count: int
    defects: list[DefectRecord] = field(default_factory=list)
    output_dir: str = ""
    message: str = ""

    @classmethod
    def now(cls, pcb_name: str) -> "InspectionResult":
        return cls(pcb_name=pcb_name,
                   timestamp=datetime.now().isoformat(timespec="seconds"),
                   overall_status="ERROR", alignment_status="FAILED",
                   components_total=0, components_pass=0, components_ng=0,
                   solder_defect_count=0)

    def to_json(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path
