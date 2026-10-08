"""统一日志模块 (任务书 §二十五)。

所有模块通过 get_logger(__name__) 获取 logger,
日志同时输出到控制台与 logs/aoi.log (RotatingFileHandler)。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_INITIALIZED = False


def setup_logging(log_dir: Path | str = "logs", log_file: str = "aoi.log") -> None:
    """初始化全局日志: 控制台 + 文件双输出,幂等。"""
    global _INITIALIZED
    if _INITIALIZED:
        return
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger("aoi")
    root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(
        log_dir / log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """获取 aoi 命名空间下的子 logger。"""
    return logging.getLogger(f"aoi.{name}")
