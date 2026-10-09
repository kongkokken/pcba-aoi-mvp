# PCBA AOI MVP

基于 **PCB 坐标文件 + Mark 定位 + Homography 对齐 + ROI + 元件 Mask + Golden Image 差分 + 锡珠/锡渣检测** 的 PCBA 自动光学检测最小可行产品。第一阶段不使用深度学习。

## 1. 项目简介

检测闭环: USB 摄像头 → 拍照 → Mark 定位(模板匹配+Hough 备用) → Homography 对齐 →
读取 Excel 元件坐标 → 建立 PCB mm 坐标系 → 自动生成旋转 ROI → 元件 Mask →
与 Golden Image 差分(仅 PCB 非元件区) → 疑似锡珠/锡渣检测(圆度/长宽比/面积评分) →
OK/NG + overlay/差分/Mask 图 + JSON 结果。

## 2. 环境要求

- Python 3.10+(本机实测 conda env `aoi-app`, `D:\miniforge3\envs\aoi-app\python.exe`)
- Windows + DirectShow USB 摄像头(本机 index 0, 稳定 1280x720)
- 依赖见 `requirements.txt`(opencv-python / numpy / pandas / openpyxl / Pillow / PySide6 / PyYAML / pytest)

## 3. 安装依赖

```bash
pip install -r requirements.txt
```

## 4. 启动

```bash
python main.py                  # 启动 GUI
python main.py --camera 0       # 指定摄像头
python main.py --test           # pytest 自动测试
python main.py --create-golden  # 摄像头拍照创建 Golden(--source <图片> 可离线)
python main.py --synthetic-test # 合成 PCB 全流程检测(无需真实 PCB)
python main.py --camera-test    # headless 摄像头链路验证
```

## 5. 摄像头配置

`config.yaml` 的 `camera` 段: `index / width / height / fps / backend / warmup_frames`。
本机实测仅 index 0 可用;请求 1920x1080 不被支持时自动使用实际稳定分辨率(1280x720)。

## 6. 坐标配置表(§10)

`data/pcb_config.xlsx`(Sheet: Components)由程序自动创建,也可手工编辑;
加载器同时支持 **.xlsx / .xls / .csv**。

**基础字段(必需,16 个)**: Ref / Type / X / Y / Width / Height / Angle / Inspect /
OCR / ExpectedValue / Mask / Algorithm / PositionTolerance / SizeTolerance /
AngleTolerance / RoiExpand。X/Y/Width/Height 单位 mm(板左上角原点),Angle 为度。

**扩展字段(可选,13 个)**: PartNumber / X_Offset / Y_Offset / TeachX / TeachY /
TeachAngle / CoordinateSystem / CoordinateMeaningConfirmed / BoardID /
SourceFile / SourceSheet / SourceRow / Notes。
原始坐标字段(偏移/示教值)与确认后的绝对坐标(X/Y)分开保存;缺失的示教值保留空,
程序不会猜测补齐。

**坐标语义门控(§10.2,不可违反)**: 绝不因字段名叫 X/Y 就默认是绝对 PCB 坐标。
`CoordinateMeaningConfirmed` 仅 YES/Y/TRUE/1/confirmed/是 视为已确认;
其余(含空值)一律未确认 → 该元件 ROI 标 **UNCONFIGURED**,不参与最终定位,
整板判定升级为 **REVIEW**。旧格式文件(无语义列)回退全局配置
`coordinate.coordinate_meaning_confirmed` 并在元件 notes 中记录该回退。
客户列名不同(如 RefDes/PosX)时用 `config.yaml` 的
`coordinate_import.field_mapping` 映射,不改程序。

## 7. Mark 配置

- `config.yaml` `pcb.marks_mm`: 4 个角 Mark 的 PCB mm 坐标(TL/TR/BR/BL)
- `data/templates/mark_template_1..4.png`: 模板匹配用 Mark 模板(合成测试自动生成)
- 阈值: `mark.template_threshold`,备用路径 HoughCircles 参数同在 `mark` 段

## 8. Golden 创建

```bash
python main.py --create-golden                    # 摄像头 -> 自动 Mark -> 对齐 -> 保存
python main.py --create-golden --source a.jpg     # 离线图片创建
```

保存到 `data/golden/<PCB_NAME>/golden.png` + `metadata.json`(§14 可追溯元数据:
pcb_name/分辨率/camera_index/timestamp/mark_points/creation_method +
**calibration 快照**(参数文件/RMS/是否 identity)/undistort_status/
coordinate_file/coordinate_meaning_confirmed/transform_version/
roi_config_version/panel_config)。
检测时引擎比对 Golden 元数据与当前标定/变换版本,不一致判 REVIEW,
绝不静默差分。自动 Mark 失败时支持手动 Mark 点。

## 8.1 相机标定与畸变校正(§8)

`src/calibration/calibration.py`: 棋盘格角点 → calibrateCamera →
参数存 `data/calibration/camera_calibration.json`(含 RMS/每样本残差/分辨率/时间戳)。
检测流水线第 0 级校验参数并做畸变校正(undistort),产物含 `undistorted.jpg`。
合成演示使用文档化的 **identity 豁免**(合成图按构造无畸变);
豁免仅对 `source="synthetic"` 放行,真实相机/上传来源持 identity 参数一律 REVIEW。

## 8.2 判定等级与门控(§18)

判定优先级 **REVIEW > NG > PASS**,全部结果为 MVP 候选
(result.json 中 `result_grade=MVP_CANDIDATE`)。以下任一成立即 REVIEW
(琥珀色显示,附 review_reasons): 无有效相机标定 / 坐标语义未确认 /
Golden 与当前条件不一致 / 存在 UNCONFIGURED ROI / 缺陷落在待复核 ROI。
GUI 与 Web 端均显示标定与坐标映射状态。

## 8.3 拼板(§9.1)

`config.yaml` `panel` 段: `mode: single/grid/auto`,grid 模式按
rows/cols/spacing/rotation 生成 BOARD_1..N(row_major 编号);
缺陷记录自动归属单板编号(board_id);`roi_overlay.jpg` 叠加拼板边界。
auto 模式为验证钩子,轮廓数 ≤1 时退化 single 并警告。

## 9. 检测流程

GUI: 打开摄像头(Live) → 拍照 → 开始检测(Inspection) → 右视图产物切换
(overlay/roi_overlay/masks_color/diff 等) + 异常表(Ref/BoardID/Defect/.../Message)
+ 判定(PASS 绿/NG 红/REVIEW 琥珀)。
CLI: `python main.py --synthetic-test` 演示完整流程。

## 10. 参数调整

全部阈值在 `config.yaml`:
`difference`(threshold/min_area/max_area/blur/morphology/min_mean_diff/edge_exclusion_px)、
`solder`(min_area/max_area/min_circularity/max_aspect_ratio)、
`illumination`(blur/normalize_brightness/clahe)、`roi.default_expand`。

## 11. 输出文件

每次检测保存到 `output/<YYYYMMDD_HHMMSS>/`(§19 共 12 件产物):
`original.jpg`(原图) `undistorted.jpg`(畸变校正图) `aligned.jpg`(对齐图)
`roi_overlay.jpg`(拼板边界+ROI 状态着色) `pcb_mask.png` `component_mask.png`
`valid_inspection_mask.png`(三掩膜,255=区域为真) `masks_color.png`
(彩色可视化: 绿=检测区/红=元件/灰=板外) `diff.png`(差分图)
`overlay.jpg`(判定叠加图) `result.json` `config_snapshot.yaml`
(配置+H 矩阵+留出重投影误差+拼板 placements+ROI 摘要快照)。

## 12. 错误处理

结构化异常(`src/utils/exceptions.py`): CameraError / AlignmentError /
MarkDetectionError / CalibrationError / CoordinateConfigError(ExcelConfigError
为其子类) / ROIError / GoldenImageError / InspectionError。
全部记录到 `logs/aoi.log`,检测失败返回 ERROR 结果而不崩溃。

## 13. Synthetic Test

`src/synthetic/synthetic_pcb_generator.py` 生成: 合成 PCB(基材/走线/焊盘/丝印/
R/C/IC/位号/4 角 Mark)、模拟拍摄图(透视+模糊+噪声+亮度变化,default/shifted 两姿态)、
缺陷变体(圆形亮斑=锡珠,拉长不规则斑块=锡渣,位于非元件区)。
`python main.py --synthetic-test` 实测: capture_ok→PASS,capture_ng/shifted→NG(各 3 缺陷全中)。

## 14. 后续 PaddleOCR

`src/inspection/ocr_engine.py` 预留 `OcrEngine.recognize(image, roi)` 接口与
`PaddleOcrEngine` 占位。Excel 中 OCR=1 的元件将读取 ExpectedValue 做 Expected vs Detected 判定。

## 15. 后续 YOLO

MVP 闭环稳定后,AI 仅用于: 未知元件/未知缺件/复杂缺陷/异常物体/无 CAD 坐标元件,
不替代既有 PCB 坐标系统。第一阶段禁止引入 YOLO/PyTorch/TensorFlow/CUDA。

## 16. 后续工业相机

`src/camera/camera.py` 后端参数化(dshow/msmf/any);接工业相机(GigE/USB3 Vision)
时新增 backend 适配层即可,上游 Mark/对齐/检测链路不变。

## 17. 后续多 PCB 型号支持

按型号隔离: `config.yaml` 的 `pcb` 段 + `data/pcb_config.xlsx`(每型号一份) +
`data/golden/<PCB_NAME>/` + `data/templates/`。GUI 顶部 PCB 型号切换为扩展点。

## 18. Streamlit Cloud 部署

仓库根目录自带 `streamlit_app.py`(Web 前端)与 `packages.txt`(OpenCV 需要的
Debian 库: `libgl1` / `libglib2.0-0`),`requirements.txt` 已含 `streamlit>=1.35`。

部署步骤:

1. 打开 [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repository: `kongkokken/pcba-aoi-mvp` → Branch: `main` →
   Main file path: `streamlit_app.py`
3. **Deploy**(packages.txt 已包含,无需额外配置)

本地运行:

```bash
streamlit run streamlit_app.py
```

Web 端功能: 合成演示(零硬件一键跑通 PASS/NG/NG)、浏览器摄像头 / 上传图片检测
(真实来源在 identity 标定下判 REVIEW 并列出原因,§27.5)、判定门控状态侧边栏、
产物切换查看(overlay/roi_overlay/masks_color 等)、Golden 管理(查看/上传良品板重建)、
元件坐标表查看/下载/校验替换(.xlsx/.xls/.csv)。
注意: 云端摄像头走浏览器 `st.camera_input`(HTTPS 下可用),
不使用 `cv2.VideoCapture`;文件系统为临时存储,重启后 output/ 清空。

---

## 测试与验收状态(本机实测,五级验证 §23)

| 级别 | 内容 | 状态 |
|---|---|---|
| 1. 单元测试 | `python main.py --test` | ✅ **87 passed**(标定/坐标回环/留出重投影/拼板/ROI/Mask/差分/判定门控/坐标导入语义) |
| 2. 合成图像测试 | `python main.py --synthetic-test` | ✅ 3/3 场景符合: capture_ok=PASS,capture_ng=NG(3 缺陷),capture_shifted=NG(3 缺陷,验证 Homography 对齐恢复);12 件产物齐全 |
| 3. GUI 离屏冒烟 | `QT_QPA_PLATFORM=offscreen python tools/gui_smoke_test.py` | ✅ NG 检出 + REVIEW 门控(identity 标定对相机来源不放行)双场景通过 |
| 4. 真实摄像头链路 | `python main.py --camera-test` | ✅ 打开/取流/释放通过(1280x720);⚠️ 真实 PCB 标定 **PENDING**(缺实体标定板) |
| 5. 真实样本验证 | 真实 PCB 图片 + 客户坐标报告 | ⛔ **BLOCKED**: `Abus-913-13339001-00C-TOP.jpg` 与 `Report_913-13339001-00C-A.xls` 未提供,按 §27.9 不依赖它们的模块已完成,相关集成点留 PENDING 标记 |

**判定门控说明(§18/§27.5)**: 合成测试的绿色判定依赖文档化的 identity 标定豁免
(合成图按构造无镜头畸变);同一组参数对 camera/upload 来源不放行(强制 REVIEW)。
坐标语义未确认、Golden 条件不一致、UNCONFIGURED ROI 存在时同样强制 REVIEW。

**限制**: 核心算法已通过 Synthetic Test,但真实 PCB 检测仍需要实体标定板标定、
真实 PCB 图像/坐标/Mark 数据进行现场确认。本 MVP 不声称达到工业 AOI 精度,
所有结果均为 MVP 候选(result_grade=MVP_CANDIDATE)。

开发日志: `docs/DEV_LOG.md`(Phase 0-15 + 融合版包 A/B/C/D 全记录)
