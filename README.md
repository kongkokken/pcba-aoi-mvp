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

## 6. Excel 配置

`data/pcb_config.xlsx`(Sheet: Components)由程序自动创建,也可手工编辑。
字段: Ref / Type / X / Y / Width / Height / Angle / Inspect / OCR / ExpectedValue /
Mask / Algorithm / PositionTolerance / SizeTolerance / AngleTolerance / RoiExpand。
X/Y/Width/Height 单位为 mm(板左上角原点),Angle 为度。

## 7. Mark 配置

- `config.yaml` `pcb.marks_mm`: 4 个角 Mark 的 PCB mm 坐标(TL/TR/BR/BL)
- `data/templates/mark_template_1..4.png`: 模板匹配用 Mark 模板(合成测试自动生成)
- 阈值: `mark.template_threshold`,备用路径 HoughCircles 参数同在 `mark` 段

## 8. Golden 创建

```bash
python main.py --create-golden                    # 摄像头 -> 自动 Mark -> 对齐 -> 保存
python main.py --create-golden --source a.jpg     # 离线图片创建
```

保存到 `data/golden/<PCB_NAME>/golden.png` + `metadata.json`
(pcb_name/分辨率/camera_index/timestamp/mark_points)。自动 Mark 失败时支持手动 Mark 点。

## 9. 检测流程

GUI: 打开摄像头(Live) → 拍照 → 开始检测(Inspection) → 右视图 overlay + 异常表 + PASS/NG。
CLI: `python main.py --synthetic-test` 演示完整流程。

## 10. 参数调整

全部阈值在 `config.yaml`:
`difference`(threshold/min_area/max_area/blur/morphology/min_mean_diff/edge_exclusion_px)、
`solder`(min_area/max_area/min_circularity/max_aspect_ratio)、
`illumination`(blur/normalize_brightness/clahe)、`roi.default_expand`。

## 11. 输出文件

每次检测保存到 `output/<YYYYMMDD_HHMMSS>/`:
`original.jpg`(原图) `aligned.jpg`(对齐图) `mask.png`(检测区掩膜)
`diff.png`(差分图) `overlay.jpg`(绿=PASS ROI,红=NG 缺陷框) `result.json`(§二十结构)。

## 12. 错误处理

结构化异常(`src/utils/exceptions.py`): CameraError / AlignmentError /
MarkDetectionError / ExcelConfigError / ROIError / GoldenImageError / InspectionError。
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

Web 端功能: 合成演示(零硬件一键跑通 PASS/NG/NG)、浏览器摄像头 / 上传图片检测、
Golden 管理(查看/上传良品板重建)、元件坐标表查看/下载/校验替换。
注意: 云端摄像头走浏览器 `st.camera_input`(HTTPS 下可用),
不使用 `cv2.VideoCapture`;文件系统为临时存储,重启后 output/ 清空。

---

## 测试与验收状态(本机实测)

- `python main.py --test`: **33 passed**
- `python main.py --synthetic-test`: 3/3 场景符合(PASS/NG/NG),六件产物齐全
- `python main.py --camera-test`: 真实摄像头打开/拍照/释放通过(1280x720)
- 开发日志: `docs/DEV_LOG.md`(Phase 0-15 全记录)

**限制**: 核心算法已通过 Synthetic Test,但真实 PCB 检测仍需要真实 PCB 图像/坐标/Mark 数据
进行现场参数标定。本 MVP 不声称达到工业 AOI 精度。
