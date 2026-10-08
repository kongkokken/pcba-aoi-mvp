"""pytest 共享夹具: 项目根入 path;合成数据 + golden 会话级准备。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.config_manager import ConfigManager  # noqa: E402
from src.golden.golden_manager import GoldenManager  # noqa: E402
from src.synthetic.synthetic_pcb_generator import SyntheticPcbGenerator  # noqa: E402
from src.utils.image_utils import load_image  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402


@pytest.fixture(scope="session")
def cfg() -> ConfigManager:
    setup_logging()
    return ConfigManager()


@pytest.fixture(scope="session")
def synthetic(cfg: ConfigManager):
    """确保合成图像集存在(缺失时生成)。"""
    syn_dir = cfg.data_dir() / "synthetic"
    if not (syn_dir / "capture_ok.jpg").exists():
        SyntheticPcbGenerator(cfg).generate_all()
    return syn_dir


@pytest.fixture(scope="session")
def golden_image(cfg: ConfigManager, synthetic: Path):
    """确保 golden 存在(由 capture_ok 自动 Mark 创建)。"""
    gm = GoldenManager(cfg)
    if not gm.exists():
        gm.create_golden(load_image(synthetic / "capture_ok.jpg"))
    img, meta = gm.load_golden()
    return img
