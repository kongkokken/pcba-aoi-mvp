"""PySide6 主界面 (任务书 §二十二/§二十三 / Phase 11)。

布局: 顶部(PCB型号/Camera/系统状态) - 中部(左 Camera Image / 右 Inspection Image)
底部按钮: 打开摄像头 / 拍照 / 创建Golden / 开始检测 / 保存结果
结果区: PASS/NG 状态 + 异常列表(Ref/Defect/X/Y/Area/Score)

Live 模式: QTimer 定时取帧;Inspection 模式: 拍照 -> 引擎检测 -> 显示 overlay。
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from src.camera.camera import Camera
from src.camera.camera_manager import create_camera_from_config
from src.config.config_manager import ConfigManager
from src.golden.golden_manager import GoldenManager
from src.inspection.inspection_engine import InspectionEngine
from src.inspection.inspection_result import InspectionResult
from src.utils.exceptions import AOIError, CameraError
from src.utils.image_utils import save_image
from src.utils.logger import get_logger

logger = get_logger("gui")


def cv_to_pixmap(image: np.ndarray, max_w: int = 560) -> QPixmap:
    """BGR numpy -> QPixmap(按宽度缩放)。"""
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    pix = QPixmap.fromImage(qimg.copy())
    if w > max_w:
        pix = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
    return pix


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigManager, camera_index: int | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.engine = InspectionEngine(cfg)
        self.golden_mgr = GoldenManager(cfg)
        self.camera: Camera | None = None
        self.camera_index = (camera_index if camera_index is not None
                             else int(cfg.get("camera.index", 0)))
        self.last_frame: np.ndarray | None = None
        # 当前帧来源(§27.5 判定门控依赖): 摄像头取帧为 camera;
        # 测试注入合成帧时由调用方置 "synthetic"(identity 豁免仅合成可用)
        self.frame_source: str = "camera"
        self.last_result: InspectionResult | None = None

        self.setWindowTitle("PCBA AOI MVP")
        self.resize(1200, 760)
        self._build_ui()

        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self._on_live_tick)

    # ---- UI 构建 ---------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 顶部: PCB 型号 / Camera / 系统状态
        top = QHBoxLayout()
        top.addWidget(QLabel(f"PCB型号: {self.cfg.get('pcb.name', 'DEMO_PCB')}"))
        top.addWidget(QLabel("Camera:"))
        self.cam_spin = QSpinBox()
        self.cam_spin.setRange(0, 8)
        self.cam_spin.setValue(self.camera_index)
        top.addWidget(self.cam_spin)
        self.status_label = QLabel("系统状态: 就绪")
        top.addWidget(self.status_label)
        # 标定/坐标映射状态(§8/§10.2: REVIEW 门控来源,必须可见)
        self.calib_label = QLabel("标定: -  坐标映射: -")
        self.calib_label.setStyleSheet("color:#888;")
        top.addWidget(self.calib_label)
        top.addStretch(1)
        root.addLayout(top)

        # 中部: 左 Camera / 右 Inspection
        mid = QHBoxLayout()
        self.camera_view = QLabel("Camera Image")
        self.camera_view.setMinimumSize(560, 400)
        self.camera_view.setStyleSheet("background:#202020;color:#888;")
        self.camera_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_view = QLabel("Inspection Image")
        self.result_view.setMinimumSize(560, 400)
        self.result_view.setStyleSheet("background:#202020;color:#888;")
        self.result_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mid.addWidget(self.camera_view)
        mid.addWidget(self.result_view)
        root.addLayout(mid)

        # 结果: 判定(PASS 绿/NG 红/REVIEW 琥珀, §18) + 产物切换 + 异常列表
        result_row = QHBoxLayout()
        self.result_label = QLabel("结果: -")
        self.result_label.setStyleSheet("font-size:20px;font-weight:bold;")
        result_row.addWidget(self.result_label)
        result_row.addWidget(QLabel("产物:"))
        self.artifact_combo = QComboBox()
        # §19 产物清单(切换查看 result_view)
        for name in ["overlay.jpg", "aligned.jpg", "undistorted.jpg",
                     "roi_overlay.jpg", "masks_color.png", "diff.png",
                     "original.jpg"]:
            self.artifact_combo.addItem(name)
        self.artifact_combo.currentTextChanged.connect(self._on_artifact_changed)
        result_row.addWidget(self.artifact_combo)
        result_row.addStretch(1)
        root.addLayout(result_row)
        self.defect_table = QTableWidget(0, 8)
        self.defect_table.setHorizontalHeaderLabels(
            ["Ref", "BoardID", "Defect", "X", "Y", "Area", "Score", "Message"])
        self.defect_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.defect_table.setMaximumHeight(160)
        root.addWidget(self.defect_table)

        # 底部按钮
        bottom = QHBoxLayout()
        for text, slot in [("打开摄像头", self.on_open_camera),
                           ("拍照", self.on_capture),
                           ("创建Golden", self.on_create_golden),
                           ("开始检测", self.on_inspect),
                           ("保存结果", self.on_save_result)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bottom.addWidget(btn)
        root.addLayout(bottom)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(f"系统状态: {text}")
        logger.info("GUI 状态: %s", text)

    # ---- Live 模式 --------------------------------------------------------
    def on_open_camera(self) -> None:
        """打开摄像头并进入 Live 模式。"""
        try:
            if self.camera is None:
                self.camera = create_camera_from_config(
                    self.cfg, index=self.cam_spin.value())
                self.camera.open()
            self.live_timer.start(33)  # ~30fps 刷新
            self._set_status(
                f"Live: cam{self.camera.index} {self.camera.width}x{self.camera.height}")
        except CameraError as e:
            self._set_status(f"摄像头错误: {e}")

    def _on_live_tick(self) -> None:
        try:
            frame = self.camera.read_frame() if self.camera else None
        except CameraError as e:
            self.live_timer.stop()
            self._set_status(f"取流中断: {e}")
            return
        if frame is not None:
            self.last_frame = frame
            self.frame_source = "camera"
            self.camera_view.setPixmap(cv_to_pixmap(frame))

    def _stop_live(self) -> None:
        self.live_timer.stop()

    # ---- Inspection 模式 ---------------------------------------------------
    def on_capture(self) -> None:
        """拍照: 保存当前帧到 data/captures/。"""
        if self.last_frame is None:
            self._set_status("无图像(请先打开摄像头)")
            return
        path = self.cfg.data_dir() / "captures" / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        save_image(self.last_frame, path)
        self._set_status(f"已拍照: {path.name}")

    def on_create_golden(self) -> None:
        """由当前帧创建 Golden(自动 Mark,失败提示)。"""
        if self.last_frame is None:
            self._set_status("无图像(请先打开摄像头并拍照)")
            return
        try:
            path = self.golden_mgr.create_golden(
                self.last_frame, camera_index=self.cam_spin.value())
            self._set_status(f"Golden 已创建: {path.name}")
        except AOIError as e:
            self._set_status(f"Golden 创建失败: {e}")

    def on_inspect(self) -> None:
        """开始检测: 当前帧 -> 完整 AOI 流程 -> 显示 overlay + 异常列表。"""
        if self.last_frame is None:
            self._set_status("无图像(请先打开摄像头)")
            return
        self._set_status("检测中...")
        result = self.engine.inspect(self.last_frame, save_output=True,
                                     source=self.frame_source)
        self.last_result = result
        self._show_result(result)

    # 判定颜色(§18/§19): PASS 绿 / NG 红 / REVIEW 琥珀 / ERROR 灰
    _STATUS_COLORS = {"PASS": "#0a0", "NG": "#d22",
                      "REVIEW": "#e6a800", "ERROR": "#888"}

    def _show_result(self, result: InspectionResult) -> None:
        color = self._STATUS_COLORS.get(result.overall_status, "#888")
        text = f"结果: {result.overall_status}"
        if result.overall_status == "REVIEW" and result.review_reasons:
            text += f"({len(result.review_reasons)} 项待复核)"
        self.result_label.setText(text)
        self.result_label.setStyleSheet(
            f"font-size:20px;font-weight:bold;color:{color};")
        self.calib_label.setText(
            f"标定: {result.calibration_status}  "
            f"坐标映射: {result.coordinate_mapping_status}")
        self.calib_label.setStyleSheet(
            "color:#888;" if result.calibration_status == "valid"
            else "color:#e6a800;")
        self.defect_table.setRowCount(len(result.defects))
        for i, d in enumerate(result.defects):
            for j, v in enumerate([d.ref or "-", d.board_id, d.type,
                                   d.x, d.y, f"{d.area:.0f}",
                                   f"{d.score:.2f}", d.message]):
                self.defect_table.setItem(i, j, QTableWidgetItem(str(v)))
        # 默认显示 overlay;可通过产物下拉切换
        self.artifact_combo.setCurrentText("overlay.jpg")
        self._show_artifact("overlay.jpg")
        self._set_status(f"检测完成: {result.overall_status} "
                         f"({result.solder_defect_count} 个疑似缺陷) {result.message}")

    def _on_artifact_changed(self, name: str) -> None:
        self._show_artifact(name)

    def _show_artifact(self, name: str) -> None:
        """从本次输出目录加载所选产物到 Inspection Image 区 (§19)。"""
        if not (self.last_result and self.last_result.output_dir):
            return
        path = Path(self.last_result.output_dir) / name
        if not path.exists():
            return
        img = cv2.imdecode(np.fromfile(str(path), np.uint8),
                           cv2.IMREAD_UNCHANGED)
        if img is None:
            return
        if img.ndim == 2:  # 单通道 mask/diff 转灰度显示
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        self.result_view.setPixmap(cv_to_pixmap(img))

    def on_save_result(self) -> None:
        """结果在检测时已自动保存;此按钮提示保存位置。"""
        if self.last_result and self.last_result.output_dir:
            self._set_status(f"结果已保存: {self.last_result.output_dir}")
        else:
            self._set_status("暂无检测结果可保存")

    # ---- 关闭 --------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._stop_live()
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        super().closeEvent(event)


def run_gui(camera_index: int | None = None) -> int:
    """启动 GUI(阻塞)。"""
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    win = MainWindow(ConfigManager(), camera_index=camera_index)
    win.show()
    return app.exec()
