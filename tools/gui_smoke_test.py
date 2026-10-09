"""GUI 离屏冒烟测试: QT_QPA_PLATFORM=offscreen 下自动走完
打开界面 -> 注入合成 NG 帧 -> 开始检测 -> 校验结果 -> 自动关闭。
用法: set QT_QPA_PLATFORM=offscreen && python tools/gui_smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.config.config_manager import ConfigManager  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.image_utils import load_image  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    cfg = ConfigManager()
    win = MainWindow(cfg)

    # 注入合成 NG 帧(代替摄像头);来源必须如实声明为 synthetic
    # (identity 标定豁免仅对合成来源放行, §27.5)
    win.last_frame = load_image(cfg.data_dir() / "synthetic" / "capture_ng.jpg")
    win.frame_source = "synthetic"

    def scenario() -> None:
        win.on_inspect()  # 触发完整检测
        r = win.last_result
        assert r is not None, "无检测结果"
        assert r.overall_status == "NG", f"期望 NG, 实际 {r.overall_status}"
        assert r.solder_defect_count == 3, f"期望 3 缺陷, 实际 {r.solder_defect_count}"
        assert win.defect_table.rowCount() == 3
        assert "NG" in win.result_label.text()
        # 产物切换: roi_overlay / masks_color 可加载
        for artifact in ["roi_overlay.jpg", "masks_color.png", "diff.png"]:
            win.artifact_combo.setCurrentText(artifact)
        win.on_save_result()
        print("GUI smoke test PASSED:",
              r.overall_status, r.solder_defect_count, r.output_dir)

        # REVIEW 门控场景: 同一帧伪装成相机来源,identity 标定不得放行 (§27.5)
        win.frame_source = "camera"
        win.on_inspect()
        r2 = win.last_result
        assert r2.overall_status == "REVIEW", \
            f"相机来源+identity 标定应 REVIEW, 实际 {r2.overall_status}"
        assert "REVIEW" in win.result_label.text()
        assert r2.review_reasons, "REVIEW 必须给出理由"
        print("GUI REVIEW gating PASSED:", r2.review_reasons[0])
        win.close()
        app.quit()

    win.show()
    QTimer.singleShot(300, scenario)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
