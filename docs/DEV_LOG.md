# PCBA AOI MVP — 开发日志 / Development Log

每个 Phase 完成后在此记录:完成内容、创建文件、运行命令、测试结果、发现的问题、解决方法、下一阶段。

---

## PHASE 0 COMPLETE — 环境检查

**日期:** 2026-10-08

**完成内容:**
- Python / pip / 依赖检查
- 摄像头枚举与真实 Frame 抓取
- 创建 `requirements.txt`
- 项目目录初始化 + git 仓库

**环境事实(实测):**

| 项目 | 结果 |
|---|---|
| Python | 3.10.21 (conda env `aoi-app`: `D:\miniforge3\envs\aoi-app\python.exe`) |
| opencv-python | 5.0.0.93 ✅ |
| numpy | 2.2.6 ✅ |
| pandas | 2.3.3 ✅ |
| openpyxl | 3.1.5 ✅ (本次安装) |
| Pillow | 12.3.0 ✅ |
| PySide6 | 6.11.2 ✅ (本次安装) |
| PyYAML | 6.0.3 ✅ |
| pytest | 9.1.1 ✅ (本次安装) |
| scikit-image | 未安装(可选,暂不引入) |

**摄像头(实测):**

| 项目 | 结果 |
|---|---|
| 可用 index | **0** (1/2/3 无法打开) |
| 后端 | DirectShow (`cv2.CAP_DSHOW`) |
| 分辨率 | 请求 1920×1080,实际稳定 **1280×720** → 按任务规则使用实际最高稳定分辨率 |
| 真实 Frame | ✅ 已保存 `data/captures/phase0_camera_probe.jpg`(真实场景画面,非黑帧) |

**注意:** 当前摄像头为笔记本前置摄像头,无真实 PCB 治具。按任务书 §二十七/§三十三:
核心算法验证走 **Synthetic Test** 路线(合成 PCB + Mark + 元件 + 锡珠/锡渣异常),
摄像头链路用真实 Frame 验证。

**发现的问题:** 无阻塞问题。

**下一阶段:** Phase 1 — 摄像头模块(camera.py / camera_manager.py,SPACE 拍照 / ESC 退出)。

**运行命令记录:**
```bash
python --version            # 3.10.21
pip install openpyxl pytest PySide6
# 摄像头探测脚本: 遍历 index 0-3, 保存真实 frame
```

---

## PHASE 1 COMPLETE — 摄像头模块

**完成内容:**
- `config.yaml`(§二十八全部配置段)、`ConfigManager`(点号路径读取)
- 结构化异常 `src/utils/exceptions.py`(§二十四 7 类)、日志 `src/utils/logger.py`(控制台+`logs/aoi.log`)
- `src/utils/image_utils.py`(中文路径安全存图/灰度/亮度归一化/CLAHE)
- `src/camera/camera.py`(Camera: open/read/capture_to/measure_fps,无效帧抛 CameraError)
- `src/camera/camera_manager.py`(probe 0-3 / find_working_camera / create_camera_from_config)
- `tools/camera_test.py` 交互预览(SPACE 拍照 / ESC 退出,叠加 index/分辨率/FPS)

**运行命令:** `python -c "..."`(ConfigManager + Camera 真实打开拍照)

**测试结果(实测):**
- Camera opened: index=0, 1280x720 @30fps, 实测 ~10fps(前置摄像头 USB 带宽)
- 保存 `data/captures/phase1_camera_test.jpg`(133814 bytes,目验为真实场景画面,非黑帧)

**发现的问题:** git bash 中 `D:\...` 路径需写 `/d/...`;请求 1920x1080 不被支持,按 Phase 0 结论固定 1280x720。

**解决方法:** 全部命令改用 git bash 路径;分辨率以实际稳定值为准写入 config.yaml。

**下一阶段:** Phase 2 — MarkDetector(模板匹配+HoughCircles)+ synthetic_pcb_generator。
