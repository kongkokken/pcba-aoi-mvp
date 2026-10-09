"""配置管理: 加载 config.yaml,支持点号路径访问 (任务书 §二十八)。

用法:
    cfg = ConfigManager()               # 默认加载项目根目录 config.yaml
    cfg.get("camera.index")             # -> 0
    cfg.get("difference.threshold", 25) # 带默认值
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 项目根目录 = src/config/ 的上两级
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class ConfigManager:
    """YAML 配置的轻量封装,所有阈值 / 路径统一从这里读取。"""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            self._data: dict[str, Any] = yaml.safe_load(f) or {}

    def get(self, key_path: str, default: Any = None) -> Any:
        """点号路径读取,如 'camera.index'。键不存在时返回 default。"""
        node: Any = self._data
        for key in key_path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, key_path: str) -> Any:
        """必须存在的配置项,缺失直接抛 KeyError。"""
        sentinel = object()
        value = self.get(key_path, sentinel)
        if value is sentinel:
            raise KeyError(f"配置缺失: {key_path} ({self.config_path})")
        return value

    def as_dict(self) -> dict[str, Any]:
        """返回完整配置字典(用于结果快照,§19 配置版本追溯)。"""
        return dict(self._data)

    @property
    def root(self) -> Path:
        return PROJECT_ROOT

    def data_dir(self) -> Path:
        return self.root / str(self.get("paths.data_dir", "data"))

    def output_dir(self) -> Path:
        return self.root / str(self.get("paths.output_dir", "output"))

    def logs_dir(self) -> Path:
        return self.root / str(self.get("paths.logs_dir", "logs"))
