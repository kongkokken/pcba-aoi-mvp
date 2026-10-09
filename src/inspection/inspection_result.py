"""检测结果数据结构 (融合版 §19)。

判定状态: PASS / NG / REVIEW / ERROR。
REVIEW: 坐标/标定/定位未确认、置信度不足、检测条件不一致 (§18)。
所有结果标记 result_grade=MVP_CANDIDATE: 未经产线验证,不得冒充放行系统。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# 结果等级: 本系统未经真实产线样本验证 (§18/§23)
RESULT_GRADE = "MVP_CANDIDATE"


@dataclass
class DefectRecord:
    """单个缺陷记录 (§19)。"""
    type: str
    ref: str              # 关联元件位号(非元件区缺陷为 "")
    board_id: str         # 所属单板编号(单板为 BOARD_1)
    x: int
    y: int
    width: int
    height: int
    area: float
    score: float          # 候选排序分数,非统计概率 (§17)
    message: str


@dataclass
class InspectionResult:
    pcb_name: str
    timestamp: str
    overall_status: str             # PASS / NG / REVIEW / ERROR
    alignment_status: str           # OK / FAILED
    calibration_status: str         # valid / identity_skip / disabled / invalid:...
    coordinate_mapping_status: str  # confirmed / unconfirmed
    components_total: int
    components_pass: int
    components_ng: int
    solder_defect_count: int
    defects: list[DefectRecord] = field(default_factory=list)
    config_versions: dict = field(default_factory=dict)  # 各配置/参数版本 (§19)
    review_reasons: list[str] = field(default_factory=list)
    result_grade: str = RESULT_GRADE
    output_dir: str = ""
    message: str = ""

    @classmethod
    def now(cls, pcb_name: str) -> "InspectionResult":
        return cls(pcb_name=pcb_name,
                   timestamp=datetime.now().isoformat(timespec="seconds"),
                   overall_status="ERROR", alignment_status="FAILED",
                   calibration_status="unknown",
                   coordinate_mapping_status="unknown",
                   components_total=0, components_pass=0, components_ng=0,
                   solder_defect_count=0)

    def to_json(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path
