"""PCBA AOI MVP 入口 (任务书 §二十九)。

用法:
    python main.py                  启动 GUI
    python main.py --camera 0       指定摄像头启动 GUI
    python main.py --test           执行 pytest 自动测试
    python main.py --create-golden  从摄像头创建 Golden(可加 --source 用图片代替)
    python main.py --synthetic-test 运行合成 PCB 全流程检测
    python main.py --camera-test    headless 摄像头链路验证(打开/拍照/释放)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.config_manager import ConfigManager  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger("main")


def cmd_test() -> int:
    """执行 pytest 测试套件。"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=PROJECT_ROOT).returncode


def cmd_synthetic_test(cfg: ConfigManager) -> int:
    """合成 PCB 全流程: 生成 -> golden -> OK/NG/shifted 三次检测。"""
    from src.golden.golden_manager import GoldenManager
    from src.inspection.inspection_engine import InspectionEngine
    from src.synthetic.synthetic_pcb_generator import SyntheticPcbGenerator
    from src.utils.image_utils import load_image

    print("=== Synthetic Test: 生成合成 PCB 图像集 ===")
    syn = SyntheticPcbGenerator(cfg).generate_all()

    print("=== 创建 Golden(自动 Mark 定位 + 对齐) ===")
    gm = GoldenManager(cfg)
    gm.create_golden(load_image(syn.capture_ok),
                     camera_index=int(cfg.get("camera.index", 0)))
    print(f"golden: {gm.golden_path}")

    engine = InspectionEngine(cfg)
    expected = {"capture_ok": "PASS", "capture_ng": "NG", "capture_shifted": "NG"}
    ok = True
    for name, want in expected.items():
        img = load_image(cfg.data_dir() / "synthetic" / f"{name}.jpg")
        result = engine.inspect(img, save_output=True)
        got = result.overall_status
        mark = "✓" if got == want else "✗"
        print(f"[{mark}] {name}: {got} (期望 {want}), "
              f"defects={result.solder_defect_count}, output={result.output_dir}")
        for d in result.defects:
            print(f"      {d.type} @({d.x},{d.y}) {d.width}x{d.height} "
                  f"area={d.area} score={d.score}")
        ok = ok and (got == want)
    print("=== Synthetic Test", "通过 ===" if ok else "存在不符 ===")
    return 0 if ok else 1


def cmd_create_golden(cfg: ConfigManager, source: str | None) -> int:
    """创建 Golden: 默认摄像头拍照;--source 指定图片则离线创建。"""
    from src.camera.camera_manager import create_camera_from_config
    from src.golden.golden_manager import GoldenManager
    from src.utils.image_utils import load_image

    gm = GoldenManager(cfg)
    if source:
        frame = load_image(source)
        cam_index = None
    else:
        with create_camera_from_config(cfg) as cam:
            cam_index = cam.index
            frame = cam.read_frame()
    path = gm.create_golden(frame, camera_index=cam_index)
    print(f"Golden 已创建: {path}")
    return 0


def cmd_camera_test(cfg: ConfigManager, index: int | None) -> int:
    """headless 摄像头链路验证: 打开 -> 信息 -> 拍照 -> 释放。"""
    from src.camera.camera_manager import create_camera_from_config

    with create_camera_from_config(cfg, index=index) as cam:
        print(f"Camera index={cam.index} {cam.width}x{cam.height} "
              f"fps={cam.fps:.0f} (实测 {cam.measure_fps(20):.1f})")
        path = cam.capture_to(cfg.data_dir() / "captures" / "camera_test.jpg")
        print(f"拍照已保存: {path}")
    print("摄像头链路验证通过(已释放)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PCBA AOI MVP")
    parser.add_argument("--camera", type=int, default=None, help="摄像头索引")
    parser.add_argument("--test", action="store_true", help="运行 pytest")
    parser.add_argument("--create-golden", action="store_true", help="创建 Golden")
    parser.add_argument("--synthetic-test", action="store_true", help="合成 PCB 测试")
    parser.add_argument("--camera-test", action="store_true", help="headless 摄像头验证")
    parser.add_argument("--source", type=str, default=None,
                        help="--create-golden 的离线图片源")
    args = parser.parse_args()

    setup_logging()
    cfg = ConfigManager()

    if args.test:
        return cmd_test()
    if args.synthetic_test:
        return cmd_synthetic_test(cfg)
    if args.create_golden:
        return cmd_create_golden(cfg, args.source)
    if args.camera_test:
        return cmd_camera_test(cfg, args.camera)

    # 默认: 启动 GUI
    from src.gui.main_window import run_gui
    return run_gui(camera_index=args.camera)


if __name__ == "__main__":
    raise SystemExit(main())
