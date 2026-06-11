import pydicom
import numpy as np
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class DicomParseException(Exception):
    """自定义异常：DICOM 文件解析失败"""
    pass


class DicomParser:
    """
    DICOM 文件解析器。
    负责读取 DICOM 文件，提取元数据，并将其转换为通用的 PNG 图像格式。
    """

    def __init__(self, file_path: str):
        """
        初始化解析器并读取 DICOM 文件。

        Args:
            file_path: DICOM 文件路径。

        Raises:
            DicomParseException: 文件读取或解析失败。
        """
        try:
            self.ds = pydicom.dcmread(file_path)
        except Exception as e:
            raise DicomParseException(f"读取 DICOM 文件失败: {e}")

        # 提取核心元数据
        self.patient_id = getattr(self.ds, 'PatientID', 'Unknown')
        self.study_uid = getattr(self.ds, 'StudyInstanceUID', 'Unknown')
        self.photometric = getattr(self.ds, 'PhotometricInterpretation', 'Unknown')
        self.rows = getattr(self.ds, 'Rows', 0)
        self.cols = getattr(self.ds, 'Columns', 0)

        # 保存完整的 DICOM Tags 为字典，供后续数据库存储
        self.metadata_dict = self.ds.to_json_dict(bulk_data_threshold=1024)

    def _normalize_grayscale(self, pixel_array: np.ndarray) -> np.ndarray:
        """
        灰度图像归一化处理。
        应用 DICOM 标准的 RescaleSlope 和 RescaleIntercept 将原始像素值映射到 Hounsfield Unit (HU) 或灰度值，
        然后归一化至 0-255。
        """
        slope = float(getattr(self.ds, 'RescaleSlope', 1.0))
        intercept = float(getattr(self.ds, 'RescaleIntercept', 0.0))

        # 线性变换
        pixel_array = pixel_array.astype(np.float64) * slope + intercept

        # 归一化到 0-255
        min_val = np.min(pixel_array)
        max_val = np.max(pixel_array)

        if max_val == min_val:
            return np.zeros_like(pixel_array, dtype=np.uint8)

        pixel_array = (pixel_array - min_val) / (max_val - min_val) * 255
        return pixel_array.astype(np.uint8)

    def get_png_image(self) -> Image.Image:
        """
        获取 PIL Image 对象（核心色彩还原逻辑）。

        策略说明：
        1. 单通道图 (MONOCHROME1/2)：严格遵循标签逻辑，应用斜率/截距校正，并对 MONOCHROME1 进行黑白反转。
        2. 多通道图 (RGB/YBR)：由于皮肤镜数据集（如 SIIM-ISIC）常存在标签与实际存储不符的情况（标注为 YBR 但实际为 RGB），
           此处采用防御性策略：直接按位深映射像素值至 0-255，强制视为 RGB 输出，避免错误的色彩空间转换导致偏色。

        Returns:
            Image.Image: PIL RGB 图像对象。

        Raises:
            DicomParseException: 像素数据提取失败。
        """
        try:
            pixel_array = self.ds.pixel_array
        except Exception as e:
            raise DicomParseException(f"提取像素数据失败: {e}")

        # ------------------------------------------------
        # 1. 灰度图像处理
        # ------------------------------------------------
        if self.photometric in ['MONOCHROME1', 'MONOCHROME2'] or pixel_array.ndim == 2:
            normalized_array = self._normalize_grayscale(pixel_array)

            if self.photometric == 'MONOCHROME1':
                # MONOCHROME1: 0 代表白色，高值代表黑色（如底片），需反转
                image_array = 255 - normalized_array
            else:
                image_array = normalized_array

            # 扩展为三通道以统一格式
            image_array = np.stack([image_array] * 3, axis=-1)
            return Image.fromarray(image_array, 'RGB')

        # ------------------------------------------------
        # 2. 彩色图像处理 (防御性直接映射)
        # ------------------------------------------------
        # 绝大多数现代皮肤镜设备输出 3 通道数据，底层即为 RGB。
        # 强制执行 YBR->RGB 转换反而会导致图像严重发绿或发蓝。

        if pixel_array.dtype == np.uint8:
            # 8位图：直接使用
            image_array = pixel_array
        else:
            # 16位图或其他：按比例缩放至 8位
            image_array = (pixel_array / 256).clip(0, 255).astype(np.uint8)

        # 确保只取前 3 个通道 (RGB)，丢弃可能的 Alpha 通道
        if image_array.ndim == 3 and image_array.shape[2] >= 3:
            image_array = image_array[:, :, :3]
        else:
            # 兜底：如果形状异常，降级按灰度处理
            logger.warning(f"未知的数组形状: {image_array.shape}，降级按灰度处理")
            normalized_array = self._normalize_grayscale(pixel_array)
            image_array = np.stack([normalized_array] * 3, axis=-1)

        return Image.fromarray(image_array, 'RGB')

    def save_as_png(self, output_path: str) -> Image.Image:
        """
        执行转码并保存为 PNG 文件。

        Args:
            output_path: 输出的 PNG 文件路径。

        Returns:
            Image.Image: 生成的 PIL 图像对象，可用于获取宽高信息。
        """
        image = self.get_png_image()
        image.save(output_path, 'PNG')
        logger.info(f"DICOM 转码 PNG 成功，保存至: {output_path}")
        return image