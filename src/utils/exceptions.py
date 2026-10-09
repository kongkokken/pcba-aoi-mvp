"""AOI 结构化异常定义 (任务书 §二十四)。

所有业务异常继承 AOIError,禁止裸 except: pass,
捕获后必须记录日志并向上抛出结构化异常。
"""


class AOIError(Exception):
    """AOI 系统异常基类"""


class CameraError(AOIError):
    """摄像头打开 / 取流 / 拍照失败"""


class CalibrationError(AOIError):
    """相机标定失败 / 标定参数无效 / 分辨率不匹配 / 样本不足 (§8)"""


class AlignmentError(AOIError):
    """Homography / 仿射对齐失败或结果无效"""


class MarkDetectionError(AOIError):
    """Mark 数量不足 / 重复 / 共线 / 坐标不合理"""


class CoordinateConfigError(AOIError):
    """坐标文件缺失 / 格式非法 / 字段映射错误 / 坐标语义未确认 (§10)"""


class ExcelConfigError(CoordinateConfigError):
    """Excel 坐标文件错误(向后兼容别名,语义并入 CoordinateConfigError)"""


class ROIError(AOIError):
    """ROI 生成失败或越界"""


class GoldenImageError(AOIError):
    """Golden Image 缺失 / 尺寸不一致 / 无法加载"""


class InspectionError(AOIError):
    """检测流程整体失败"""
