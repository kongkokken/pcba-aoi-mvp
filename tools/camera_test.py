"""Phase 1 交互式摄像头测试 (任务书 §七)。

实时预览 + Camera Index / Resolution / FPS 叠加显示;
SPACE 拍照到 data/captures/,ESC 退出。
用法: python tools/camera_test.py [index]
无显示环境请使用 main.py --camera-test-headless。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.camera.camera_manager import create_camera_from_config  # noqa: E402
from src.config.config_manager import ConfigManager  # noqa: E402
from src.utils.image_utils import save_image  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402


def main() -> int:
    setup_logging()
    cfg = ConfigManager()
    index = int(sys.argv[1]) if len(sys.argv) > 1 else int(cfg.get("camera.index", 0))
    cap_dir = cfg.data_dir() / "captures"

    with create_camera_from_config(cfg, index=index) as cam:
        print(f"Camera index={cam.index}, {cam.width}x{cam.height} @ {cam.fps:.0f}fps")
        prev = time.perf_counter()
        fps_show = 0.0
        while True:
            frame = cam.read_frame()
            now = time.perf_counter()
            fps_show = 0.9 * fps_show + 0.1 * (1.0 / max(now - prev, 1e-6))
            prev = now

            cv2.putText(frame, f"Cam {cam.index}  {cam.width}x{cam.height}  "
                        f"FPS {fps_show:.1f}", (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.imshow("AOI Camera Test (SPACE=capture, ESC=quit)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break
            if key == 32:  # SPACE
                path = cap_dir / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                save_image(frame, path)
                print(f"saved: {path}")
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
