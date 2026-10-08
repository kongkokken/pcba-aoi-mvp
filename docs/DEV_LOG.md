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

---

## PHASE 2 COMPLETE — Mark 定位 + 合成 PCB 生成器

**完成内容:**
- `src/synthetic/synthetic_pcb_generator.py`: 标准板渲染(基材/走线/焊盘/丝印/R/C/IC/位号/4角Mark)、
  模拟拍摄(透视变换+高斯模糊+噪声+亮度变化,default/shifted 两种姿态)、
  缺陷变体(圆形亮斑=锡珠, 不规则斑块=锡渣,位于非元件区域)、Mark 模板自动裁剪
- `src/pcb/mark_detector.py`: 模板匹配(多模板+NMS)主路径 + HoughCircles 备用路径;
  合法性检查(数量/重复/共线/越界)失败抛 MarkDetectionError; 点集自动排序 TL/TR/BR/BL

**运行命令:** `python -c "(SyntheticPcbGenerator.generate_all + MarkDetector.detect)"`

**测试结果(实测):**
- 生成 golden.png(800x560) / capture_ok.jpg / capture_ng.jpg / capture_shifted.jpg(1280x720) + 4 个 mark_template
- capture_ok: 4 Mark 检出,与真值最大误差 **0.97 px**
- capture_shifted(平移+旋转姿态): 4 Mark 检出,最大误差 **1.15 px**
- 目验: 板面/元件/Mark/缺陷均正确渲染,缺陷位于非元件区域

**发现的问题:** 无。

**下一阶段:** Phase 3 — alignment.py(findHomography + warpPerspective + 有效性检查)。

---

## PHASE 3 COMPLETE — Homography 对齐 + PCB 定位

**完成内容:**
- `src/pcb/alignment.py`: 4 点 findHomography(精确解) / 3 点 getAffineTransform 退化;
  有效性检查(有限值/非奇异/重投影误差上限),失败抛 AlignmentError
- `src/pcb/pcb_locator.py`: 拍摄图板轮廓自动检测(HSV 阈值+minAreaRect),
  标准图 pcb_mask 生成(全板减配置边距)

**运行命令:** `python -c "(detect -> align -> MAE vs golden + 失败路径)"`

**测试结果(实测):**
- capture_ok 对齐: 800x560,与 golden 灰度 MAE = 7.46(成像退化导致,合理)
- capture_shifted(平移+旋转)对齐: MAE = 7.64,目验元件/Mark 位置与 golden 完全重合 → Homography 恢复能力验证通过
- 失败路径: 共线点→AlignmentError("接近奇异"); 2 点→AlignmentError("数量非法"); 空图→AlignmentError
- PcbLocator 自动检出板四边形 [[1150,640],[128,640],[128,58],[1150,58]]; pcb_mask 有效率 97.6%

**发现的问题:** 无。

**下一阶段:** Phase 4 — coordinate_transform.py(PCB mm ↔ 图像 px,回环误差 ≤0.1mm)。
