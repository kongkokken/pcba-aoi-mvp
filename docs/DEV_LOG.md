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

---

## PHASE 4 COMPLETE — PCB 坐标系统

**完成内容:**
- `src/coordinate/coordinate_transform.py`: pcb_to_image / image_to_pcb(单点+批量),
  支持原点偏移/比例尺/旋转/可选 Homography(拍摄图->标准图->mm 完整链路)

**运行命令:** `python -c "(roundtrip tests)"`

**测试结果(实测):**
- 无旋转回环最大误差: 0.0 mm;带原点+3.5°旋转回环: 1.4e-14 mm(要求 ≤0.1 mm,余量巨大)
- 批量接口与单点接口完全一致
- Homography 链路: 拍摄图 Mark(203,123) -> PCB (6.00, 6.00) mm,正确

**发现的问题:** 无。

**下一阶段:** Phase 5 — Excel 元件坐标(程序自动创建 pcb_config.xlsx 模板 + 加载校验)。

---

## PHASE 5 COMPLETE — Excel 元件坐标

**完成内容:**
- `src/coordinate/excel_manager.py`: create_template()(程序自动生成 `data/pcb_config.xlsx`,
  Sheet=Components, 字段=任务书 §十一 全部 16 列) + load_components()(类型/空Ref/尺寸/重复Ref 校验,
  失败抛 ExcelConfigError)
- 模板行来自 `SYNTHETIC_COMPONENTS`(与合成板几何严格一致,坐标不写死在加载逻辑)

**运行命令:** `python -c "(create_template + load_components + 失败路径)"`

**测试结果(实测):**
- 生成 6 行(R101/R102/C101/C102/U101/U102),加载回读字段全部正确
- 缺文件/缺列均正确抛 ExcelConfigError

**发现的问题:** 无。

**下一阶段:** Phase 6 — ROI(旋转矩形 + boxPoints + 越界检查)。

---

## PHASE 6 COMPLETE — ROI

**完成内容:**
- `src/roi/roi.py`: Roi 旋转矩形(boxPoints 顶点/外接框/裁剪/包含测试/绘制)
- `src/roi/roi_manager.py`: Excel 元件 -> ROI 批量生成,RoiExpand 外扩,越界裁剪,完全越界抛 ROIError

**运行命令:** `python -c "(create_rois + draw_all + 越界/边缘用例)"`

**测试结果(实测):**
- 6 个 ROI 全部生成,目验 `output/phase6_rois.png`: 旋转框与元件本体/丝印精确对齐(90° 元件方向正确)
- 完全越界元件(200,200)mm -> ROIError;边缘元件(99.5,69)mm -> 顶点裁剪后有效

**发现的问题:** 无。

**下一阶段:** Phase 7 — Component Mask(Mask=1 元件 -> component_mask,检测区 = pcb_mask AND NOT component_mask)。

---

## PHASE 7 COMPLETE — Component Mask

**完成内容:**
- `src/mask/component_mask.py`: component_mask(Mask=1 元件 ROI 填充,支持额外外扩)、
  detection_mask = pcb_mask AND NOT component_mask

**测试结果(实测):**
- component_mask 覆盖 3.7%,detection_mask 有效区 93.9%
- 3 个合成缺陷(锡珠x2/锡渣x1)位置全部落在检测区内 ✅
- 6 个元件中心全部被排除在检测区外 ✅
- 输出 output/phase7_component_mask.png / phase7_detection_mask.png

**发现的问题:** 无。

**下一阶段:** Phase 8 — GoldenManager(create/load/save + metadata.json)。

---

## PHASE 8 COMPLETE — Golden Image

**完成内容:**
- `src/golden/golden_manager.py`: create_golden(拍摄图->自动/手动Mark->对齐->保存)、
  save_golden/load_golden,存储 `data/golden/DEMO_PCB/golden.png` + metadata.json
  (pcb_name/image_width/image_height/camera_index/timestamp/mark_points);尺寸校验

**测试结果(实测):**
- 自动 Mark 创建 Golden: 成功,metadata 完整;load_golden 回读 800x560
- 手动 Mark 退化路径: 成功
- 空图保存 -> GoldenImageError;100x100 尺寸不一致 -> GoldenImageError;已恢复正确 golden

**发现的问题:** 无。

**下一阶段:** Phase 9 — ImageDifferenceDetector(光照预处理+差分+形态学+连通域)。

---

## PHASE 9 COMPLETE — Image Difference(含光照预处理 §十七)

**完成内容:**
- `src/difference/image_difference.py`: 尺寸检查 -> 光照预处理(CLAHE可选/灰度域亮度归一化/高斯模糊)
  -> absdiff -> threshold -> 形态学开+闭 -> 掩膜(pcb AND NOT component) -> golden边缘排除
  -> 连通域 -> 面积/区域平均差值过滤 -> DiffRegion 列表
- `MarkDetector` 增加亮斑质心亚像素精化(消除整像素匹配抖动导致的 warp 边缘重影)

**调试过程(真实问题):**
1. OK 图出现 12 个假区域 -> 根因: 模板匹配整像素位置在进程间抖动 -> 质心亚像素精化,两进程结果逐位一致
2. NG 图 44 个假区域 -> 根因: normalize_brightness 在 BGR 彩色域取均值,与灰度目标均值量纲不一致
   (实测自差均值 16.3 灰度级) -> 改为灰度域归一化
3. 边缘排除最初同时排除 current 独有边缘,吃掉 r=4 小锡珠 -> 改为仅排除 golden 边缘(膨胀1px)

**测试结果(实测):**
- capture_ok(同姿态无缺陷): **0** 个区域(无误报)
- capture_ng: **3** 个区域 = 3 个真实缺陷 (700,316)/(514,378)/(153,434),全部命中,无漏报无误报
- capture_shifted(平移+旋转姿态): **3** 个区域,同样全部命中 → 对齐+差分全链路验证

**下一阶段:** Phase 10 — SolderDefectDetector(圆度/长宽比/面积评分)。

---

## PHASE 10 COMPLETE — 锡珠/锡渣检测

**完成内容:**
- `src/solder/solder_detector.py`: SuspectedSolderDefect(type/x/y/w/h/area/aspect_ratio/
  circularity/mean_gray/score),圆度=4πA/P²,几何过滤(min_area/max_area/min_circularity/
  max_aspect_ratio),综合评分=面积0.4+圆度0.3+灰度差0.3
- 生成器锡渣改为拉长不规则多边形(圆度0.6 vs 锡珠0.9),让几何分类真正被检验

**测试结果(实测):**
- capture_ok: 0 缺陷;capture_ng / capture_shifted: 各 3 缺陷
- 分类: 2x suspected_solder_ball(circ 0.83-0.91) + 1x suspected_debris(circ 0.57-0.62, aspect 2.4-2.6),全部正确

**发现的问题:** 初版合成锡渣近圆(circ 0.88)被误分为锡珠 -> 生成器修正为拉长多边形。

**下一阶段:** Phase 11 — PySide6 GUI(offscreen 自动化验证)。

---

## PHASE 11 COMPLETE — GUI (PySide6)

**完成内容:**
- `src/inspection/inspection_result.py`(§二十 InspectionResult/DefectRecord + JSON 序列化)
- `src/inspection/ocr_engine.py`(§三十五 OcrEngine 预留接口 + PaddleOcrEngine 占位)
- `src/inspection/inspection_engine.py`(完整检测流程 + overlay 绘制 + output/<ts>/ 产物保存,先行供 GUI 使用)
- `src/gui/main_window.py`: 顶部 PCB型号/Camera/状态;左 Camera 右 Inspection 双视图;
  底部 打开摄像头/拍照/创建Golden/开始检测/保存结果;PASS/NG 大字结果 + 异常表格;
  Live 模式(QTimer 33ms)/Inspection 模式分离;closeEvent 释放摄像头
- `tools/gui_smoke_test.py`: offscreen 自动化验证(注入合成 NG 帧 -> 检测 -> 断言)

**运行命令:** `QT_QPA_PLATFORM=offscreen python tools/gui_smoke_test.py`

**测试结果(实测):**
- PASSED: NG / 3 缺陷 / 缺陷表 3 行 / 结果落盘 output/20261008_152945;无残留进程
- 修复: QHeaderWidget -> QHeaderView(导入错误)

**下一阶段:** Phase 12 — pytest 测试套件(§二十六 10 项)。

---

## PHASE 12 COMPLETE — pytest 测试套件

**完成内容:**
- `tests/conftest.py`(cfg/合成数据/golden 会话级夹具)
- `tests/test_camera.py`(帧有效性/错误路径/选择逻辑,9 项,不依赖真实硬件)
- `tests/test_coordinate.py`(回环 ≤0.1mm/带旋转原点/批量一致性/Homography 链路,5 项)
- `tests/test_roi.py`(ROI 生成/外扩/旋转/越界/裁剪/Mask/检测区/尺寸不符,10 项)
- `tests/test_difference.py`(同图无差/空图/尺寸不一致/人为亮斑/Homography 三类失败/合成端到端,9 项)

**运行命令:** `python -m pytest tests/ -v`

**测试结果(实测): 33 passed in 0.87s** —— §二十六 10 项要求全覆盖。

**发现的问题:** 无。

**下一阶段:** Phase 13 — main.py CLI(--test/--synthetic-test/--create-golden/--camera) + 完整检测验收。

---

## PHASE 13 COMPLETE — 完整检测闭环 + CLI

**完成内容:**
- `main.py`: 5 个命令(--test / --synthetic-test / --create-golden [--source] / --camera-test / 默认 GUI + --camera)
- InspectionEngine 输出目录同秒冲突修复(_2/_3 序号)
- 端到端: capture_ok -> PASS(0 缺陷); capture_ng / capture_shifted -> NG(各 3 缺陷,分类正确)

**运行命令与实测结果:**
- `python main.py --synthetic-test`: 3/3 场景符合期望;每次检测落盘
  output/<ts>/{original.jpg, aligned.jpg, mask.png, diff.png, overlay.jpg, result.json} 六件齐全
- overlay 目验: 绿 ROI + 红缺陷框 + 顶部状态条正确;result.json 字段符合 §二十
- `python main.py --camera-test`: 真实摄像头打开 1280x720@30,拍照保存,已释放
- `python main.py --create-golden --source data/synthetic/capture_ok.jpg`: Golden 创建成功

**发现的问题:** 同秒多次检测目录冲突 -> 序号后缀修复。

**下一阶段:** Phase 14 — 代码整理;Phase 15 — README + 最终验收。
