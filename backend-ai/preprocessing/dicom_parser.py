import pydicom
import numpy as np
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class DicomParseException(Exception):
    """DICOM 文件解析失败。"""
    pass


class DicomParser:
    """DICOM 文件解析器，负责读取 DICOM 文件并转换为 PNG 图像。"""

    def __init__(self, file_path: str):
        try:
            self.ds = pydicom.dcmread(file_path)
        except Exception as e:
            raise DicomParseException(f"读取 DICOM 文件失败: {e}")

        self.patient_id = getattr(self.ds, 'PatientID', 'Unknown')
        self.study_uid = getattr(self.ds, 'StudyInstanceUID', 'Unknown')
        self.photometric = getattr(self.ds, 'PhotometricInterpretation', 'Unknown')
        self.rows = getattr(self.ds, 'Rows', 0)
        self.cols = getattr(self.ds, 'Columns', 0)
        self.metadata_dict = self.ds.to_json_dict(bulk_data_threshold=1024)

    def _normalize_grayscale(self, pixel_array: np.ndarray) -> np.ndarray:
        """灰度图像归一化：应用 RescaleSlope/RescaleIntercept 并映射至 0-255。"""
        slope = float(getattr(self.ds, 'RescaleSlope', 1.0))
        intercept = float(getattr(self.ds, 'RescaleIntercept', 0.0))
        pixel_array = pixel_array.astype(np.float64) * slope + intercept

        min_val = np.min(pixel_array)
        max_val = np.max(pixel_array)
        if max_val == min_val:
            return np.zeros_like(pixel_array, dtype=np.uint8)

        pixel_array = (pixel_array - min_val) / (max_val - min_val) * 255
        return pixel_array.astype(np.uint8)

    def get_png_image(self) -> Image.Image:
        """
        获取 PIL Image 对象。

        灰度图 (MONOCHROME1/2)：应用斜率/截距校正，MONOCHROME1 需做黑白反转。
        彩色图：部分皮肤镜数据集标签与实际存储不符（标注 YBR 但实际 RGB），
        此处采用防御性直接映射策略，避免错误的色彩空间转换。
        """
        try:
            pixel_array = self.ds.pixel_array
        except Exception as e:
            raise DicomParseException(f"提取像素数据失败: {e}")

        if self.photometric in ['MONOCHROME1', 'MONOCHROME2'] or pixel_array.ndim == 2:
            normalized_array = self._normalize_grayscale(pixel_array)

            if self.photometric == 'MONOCHROME1':
                image_array = 255 - normalized_array
            else:
                image_array = normalized_array

            image_array = np.stack([image_array] * 3, axis=-1)
            return Image.fromarray(image_array, 'RGB')

        # 彩色图：强制执行 YBR->RGB 转换反而会导致发绿或发蓝，直接按位深映射
        if pixel_array.dtype == np.uint8:
            image_array = pixel_array
        else:
            image_array = (pixel_array / 256).clip(0, 255).astype(np.uint8)

        if image_array.ndim == 3 and image_array.shape[2] >= 3:
            image_array = image_array[:, :, :3]
        else:
            logger.warning(f"未知的数组形状: {image_array.shape}，降级按灰度处理")
            normalized_array = self._normalize_grayscale(pixel_array)
            image_array = np.stack([normalized_array] * 3, axis=-1)

        return Image.fromarray(image_array, 'RGB')

    def save_as_png(self, output_path: str) -> Image.Image:
        """转码并保存为 PNG 文件。"""
        image = self.get_png_image()
        image.save(output_path, 'PNG')
        logger.info(f"DICOM 转码 PNG 成功，保存至: {output_path}")
        return image
