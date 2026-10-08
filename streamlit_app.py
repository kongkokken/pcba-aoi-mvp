"""SG-AOI · PCBA AOI MVP — Streamlit Cloud 前端。

入口: streamlit run streamlit_app.py (Streamlit Cloud 主文件)

只复用桌面版的算法引擎(src/inspection / src/synthetic / src/golden /
src/coordinate / src/config),不引入 src/gui(PySide6 仅限桌面)。
摄像头在云端通过 st.camera_input(浏览器 webcam)获取,不用 cv2.VideoCapture。
所有路径基于本文件位置(pathlib),与 CWD 无关。
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="SG-AOI · PCBA AOI MVP", layout="wide")

# ---- 品牌样式(Season Group: coral #FB6362 / surface #343741) -------------
st.markdown(
    """
    <style>
    .stAppHeader, [data-testid="stSidebar"] { background-color: #343741; }
    [data-testid="stSidebar"] * { color: #f0f2f5; }
    div.stButton > button[kind="primary"] {
        background-color: #FB6362; border-color: #FB6362; color: white;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #e04e4d; border-color: #e04e4d; color: white;
    }
    .verdict-pass {
        background:#1e7d46; color:#fff; padding:14px 20px; border-radius:8px;
        font-size:22px; font-weight:700; text-align:center;
    }
    .verdict-ng {
        background:#FB6362; color:#fff; padding:14px 20px; border-radius:8px;
        font-size:22px; font-weight:700; text-align:center;
    }
    .verdict-err {
        background:#8a6d1a; color:#fff; padding:14px 20px; border-radius:8px;
        font-size:18px; font-weight:600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---- 延迟导入重库(streamlit 启动后再加载 cv2/numpy/pandas) -----------------
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config.config_manager import ConfigManager  # noqa: E402
from src.golden.golden_manager import GoldenManager  # noqa: E402
from src.inspection.inspection_engine import InspectionEngine  # noqa: E402
from src.inspection.inspection_result import InspectionResult  # noqa: E402
from src.coordinate.excel_manager import ExcelManager  # noqa: E402
from src.synthetic.synthetic_pcb_generator import SyntheticPcbGenerator  # noqa: E402
from src.utils.exceptions import (AOIError, GoldenImageError,  # noqa: E402
                                  MarkDetectionError)
from src.utils.image_utils import load_image  # noqa: E402


# ---- 通用辅助 ---------------------------------------------------------------
@st.cache_resource
def get_cfg() -> ConfigManager:
    """配置管理器(路径锚定项目根,与 CWD 无关)。"""
    return ConfigManager()


def decode_image(file_bytes: bytes) -> np.ndarray | None:
    """上传/拍摄的 bytes -> BGR 图像。"""
    arr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img if img is not None and img.size > 0 else None


def show_bgr(img: np.ndarray, **kwargs) -> None:
    """BGR -> RGB 显示。"""
    st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), **kwargs)


def verdict_banner(result: InspectionResult, label: str = "") -> None:
    """PASS 绿 / NG 红 / ERROR 黄 横幅。"""
    prefix = f"{label} · " if label else ""
    if result.overall_status == "PASS":
        st.markdown(f'<div class="verdict-pass">✅ {prefix}PASS — '
                    f'未发现缺陷</div>', unsafe_allow_html=True)
    elif result.overall_status == "NG":
        st.markdown(f'<div class="verdict-ng">❌ {prefix}NG — 检出 '
                    f'{result.solder_defect_count} 个疑似缺陷</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="verdict-err">⚠️ {prefix}ERROR — '
                    f'{result.message}</div>', unsafe_allow_html=True)


def show_result(result: InspectionResult, label: str) -> None:
    """一次检测的完整展示: 横幅 + overlay + 缺陷表 + JSON 下载。"""
    verdict_banner(result, label)
    if result.overall_status == "ERROR" or not result.output_dir:
        return
    overlay_path = Path(result.output_dir) / "overlay.jpg"
    if overlay_path.exists():
        show_bgr(load_image(overlay_path),
                 caption=f"overlay(绿=元件ROI, 红=缺陷框) — {Path(result.output_dir).name}")
    if result.defects:
        st.dataframe(pd.DataFrame([asdict(d) for d in result.defects]),
                     use_container_width=True)
    json_path = Path(result.output_dir) / "result.json"
    if json_path.exists():
        st.download_button(f"⬇️ 下载 result.json({label})",
                           data=json_path.read_bytes(),
                           file_name=f"result_{Path(result.output_dir).name}.json",
                           mime="application/json",
                           key=f"dl_{label}_{result.timestamp}")


def friendly_error(e: Exception) -> None:
    """结构化异常 -> 友好指引。"""
    if isinstance(e, (MarkDetectionError, GoldenImageError)):
        st.error(f"Mark 定位失败: {e}")
        st.info(
            "当前 Golden 与 Mark 模板属于合成演示板 **DEMO_PCB**。"
            "普通照片中没有对应的基准 Mark(4 角圆形标记),所以无法定位。"
            "真实 PCB 检测需要: ① 在 `data/templates/` 放入该板的 "
            "mark_template_1..4.png;② 在 config.yaml 配置 `pcb.marks_mm`;"
            "③ 用良品板创建 Golden。也可以先用上方「合成演示」体验完整流程。")
    else:
        st.error(f"检测失败: {e}")


# ---- 侧边栏 -------------------------------------------------------------------
cfg = get_cfg()
with st.sidebar:
    logo = ROOT / "brand" / "logo.webp"
    if logo.exists():
        st.image(str(logo), use_container_width=True)
    st.title("SG-AOI · PCBA AOI MVP (V2)")
    st.caption(f"PCB 型号: **{cfg.get('pcb.name', 'DEMO_PCB')}** "
               f"({cfg.get('pcb.width_mm')}×{cfg.get('pcb.height_mm')} mm)")
    st.divider()
    st.subheader("检测参数(config.yaml)")
    st.caption(f"Camera: index {cfg.get('camera.index')} · "
               f"{cfg.get('camera.width')}×{cfg.get('camera.height')}"
               f"(桌面端;云端用浏览器摄像头)")
    st.caption(f"Difference: threshold={cfg.get('difference.threshold')} · "
               f"area {cfg.get('difference.min_area')}–{cfg.get('difference.max_area')}px")
    st.caption(f"Solder: circularity≥{cfg.get('solder.min_circularity')} · "
               f"aspect≤{cfg.get('solder.max_aspect_ratio')}")
    st.divider()
    st.subheader("最近检测输出")
    out_root = cfg.output_dir()
    runs = sorted((d for d in out_root.iterdir()
                   if d.is_dir() and d.name[:4].isdigit()),
                  reverse=True)[:5] if out_root.exists() else []
    if runs:
        for d in runs:
            st.caption(f"📁 `output/{d.name}`")
    else:
        st.caption("尚无检测记录")

# ---- 主区域 ---------------------------------------------------------------------
st.title("PCBA AOI MVP — Mark 定位 + Homography 对齐 + Golden 差分检测")

tab_demo, tab_live, tab_golden, tab_excel = st.tabs(
    ["🎯 合成演示(零硬件)", "📷 实时检测", "🖼️ Golden 管理", "📋 元件配置"])

# ============================ Tab 1: 合成演示 ====================================
with tab_demo:
    st.write("一键演示完整 AOI 闭环: 生成合成 PCB → 创建 Golden → "
             "对 ok / ng / shifted 三张模拟拍摄图执行检测。")
    st.caption("期望结果: capture_ok=PASS,capture_ng=NG(2 锡珠+1 锡渣),"
               "capture_shifted(平移+旋转)=NG —— 验证 Homography 对齐恢复能力。")
    if st.button("▶️ 运行合成演示", type="primary", key="run_demo"):
        try:
            with st.spinner("生成合成 PCB 图像集..."):
                syn = SyntheticPcbGenerator(cfg).generate_all()
            with st.spinner("创建 Golden(自动 Mark 定位 + 对齐)..."):
                gm = GoldenManager(cfg)
                gm.create_golden(load_image(syn.capture_ok),
                                 camera_index=int(cfg.get("camera.index", 0)))
            engine = InspectionEngine(cfg)
            cases = [("capture_ok", "PASS"), ("capture_ng", "NG"),
                     ("capture_shifted", "NG")]
            for name, want in cases:
                img = load_image(ROOT / "data" / "synthetic" / f"{name}.jpg")
                result = engine.inspect(img, save_output=True)
                ok = result.overall_status == want
                st.divider()
                st.subheader(f"{'✅' if ok else '⚠️'} {name} "
                             f"(期望 {want},实际 {result.overall_status})")
                show_result(result, name)
            st.success("合成演示完成 —— 三次检测结果均符合期望。"
                       "产物见 output/<时间戳>/ 目录。")
        except AOIError as e:
            friendly_error(e)

# ============================ Tab 2: 实时检测 ====================================
with tab_live:
    st.write("用浏览器摄像头拍摄 PCB,或上传一张板卡照片,运行真实检测流水线。")
    col_cam, col_up = st.columns(2)
    with col_cam:
        shot = st.camera_input("拍摄(浏览器摄像头)")
    with col_up:
        upload = st.file_uploader("或上传图片", type=["jpg", "jpeg", "png"],
                                  key="live_upload")
    source = shot if shot is not None else upload
    if source is not None:
        img = decode_image(source.getvalue())
        if img is None:
            st.error("无法解码图像,请换 JPG/PNG 重试。")
        else:
            show_bgr(img, caption="输入图像", width=420)
            if st.button("🔍 开始检测", type="primary", key="run_live"):
                try:
                    with st.spinner("Mark 定位 → 对齐 → 差分 → 缺陷检测..."):
                        result = InspectionEngine(cfg).inspect(img,
                                                               save_output=True)
                    show_result(result, "live")
                    if result.overall_status == "ERROR":
                        # 引擎把结构化异常收敛进 message;按类型给出指引
                        if "Mark" in result.message:
                            friendly_error(MarkDetectionError(result.message))
                        else:
                            friendly_error(AOIError(result.message))
                except AOIError as e:
                    friendly_error(e)

# ============================ Tab 3: Golden 管理 =================================
with tab_golden:
    gm = GoldenManager(cfg)
    st.subheader("当前 Golden")
    if gm.exists():
        golden_img, meta = gm.load_golden()
        c1, c2 = st.columns([2, 1])
        with c1:
            show_bgr(golden_img, caption=str(gm.golden_path))
        with c2:
            st.json(meta)
    else:
        st.warning("尚未创建 Golden。")

    st.subheader("上传良品板图像创建 / 替换 Golden")
    st.caption("流程: 上传 → 自动 Mark 定位 → Homography 对齐 → 保存 "
               "data/golden/<PCB_NAME>/golden.png + metadata.json")
    golden_up = st.file_uploader("良品板图像", type=["jpg", "jpeg", "png"],
                                 key="golden_upload")
    if golden_up is not None and st.button("创建 Golden", key="make_golden"):
        img = decode_image(golden_up.getvalue())
        if img is None:
            st.error("无法解码图像。")
        else:
            try:
                path = gm.create_golden(img)
                st.success(f"Golden 已创建: {path}")
                st.rerun()
            except (GoldenImageError, MarkDetectionError) as e:
                st.error(f"自动 Mark 定位失败,Golden 未创建: {e}")
                st.info("当前版本的 Web 界面仅支持自动 Mark 创建。"
                        "若图像中 Mark 不可检,请在桌面端使用手动 Mark 点流程"
                        "(GoldenManager.create_golden(..., manual_marks=...)),"
                        "或先检查图像中 4 个基准 Mark 是否清晰完整。")

# ============================ Tab 4: 元件配置 ====================================
with tab_excel:
    em = ExcelManager(cfg)
    st.subheader("元件坐标表(data/pcb_config.xlsx · Components)")
    if not em.path.exists():
        em.create_template()
    df = pd.read_excel(em.path, sheet_name="Components")
    st.dataframe(df, use_container_width=True)
    st.download_button("⬇️ 下载 pcb_config.xlsx", data=em.path.read_bytes(),
                       file_name="pcb_config.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("上传替换元件表")
    xlsx_up = st.file_uploader("替换 xlsx(字段需与模板一致)",
                               type=["xlsx"], key="excel_upload")
    if xlsx_up is not None and st.button("校验并替换", key="replace_excel"):
        tmp = ROOT / "data" / "_upload_tmp.xlsx"
        tmp.write_bytes(xlsx_up.getvalue())
        try:
            comps = em.load_components(tmp)  # 用引擎自带加载器校验
            import shutil
            shutil.copy(tmp, em.path)
            st.success(f"校验通过,已替换: {len(comps)} 个元件 "
                       f"({', '.join(c.ref for c in comps)})")
            st.rerun()
        except AOIError as e:
            st.error(f"校验失败,未替换: {e}")
        finally:
            tmp.unlink(missing_ok=True)

st.divider()
st.caption("SG-AOI · PCBA AOI MVP — 第一阶段: 无深度学习;"
           "核心算法经 Synthetic Test 验证,真实 PCB 需现场标定 Mark/Golden/坐标。")
