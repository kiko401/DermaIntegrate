import pydicom
import numpy as np
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class DicomParseException(Exception):
    """DICOM 解析异常"""
    pass


class DicomParser:
    def __init__(self, file_path: str):
        try:
            self.ds = pydicom.dcmread(file_path)
        except Exception as e:
            raise DicomParseException(f"读取 DICOM 文件失败: {e}")

        # 提取核心 Metadata
        self.patient_id = getattr(self.ds, 'PatientID', 'Unknown')
        self.study_uid = getattr(self.ds, 'StudyInstanceUID', 'Unknown')
        self.photometric = getattr(self.ds, 'PhotometricInterpretation', 'Unknown')
        self.rows = getattr(self.ds, 'Rows', 0)
        self.cols = getattr(self.ds, 'Columns', 0)

        # 保存完整 tags 供后续写入数据库
        self.metadata_dict = self.ds.to_json_dict(bulk_data_threshold=1024)

    def _normalize_grayscale(self, pixel_array: np.ndarray) -> np.ndarray:
        """专门处理灰度图像的归一化，应用 RescaleSlope/Intercept"""
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
        色彩还原关键点：防御性获取 PIL Image 对象。
        针对皮肤镜 DICOM 常见的标签不规范现象（标记为 YBR 实际存为 RGB），
        对于 3 通道图像，不再盲目信任标签进行转换，而是根据位深直接映射，
        彻底规避伪 YBR 标签导致的偏色问题。
        """
        try:
            pixel_array = self.ds.pixel_array
        except Exception as e:
            raise DicomParseException(f"提取像素数据失败: {e}")

        # 1. 灰度图：严格遵守标签逻辑
        if self.photometric in ['MONOCHROME1', 'MONOCHROME2'] or pixel_array.ndim == 2:
            normalized_array = self._normalize_grayscale(pixel_array)
            if self.photometric == 'MONOCHROME1':
                # 0为白，255为黑，需反转
                image_array = 255 - normalized_array
            else:
                image_array = normalized_array

            # 复制为三通道 RGB
            image_array = np.stack([image_array] * 3, axis=-1)
            return Image.fromarray(image_array, 'RGB')

        # 2. 彩色图（RGB 或 伪标签的 YBR）：防御性直接映射
        # 绝大多数现代皮肤镜数据（如 SIIM-ISIC）底层存储的就是 RGB，
        # 强制根据标签做 YBR->RGB 转换反而会导致严重的蓝绿偏色。
        if pixel_array.dtype == np.uint8:
            # 8位图：直接作为 RGB 原样输出
            image_array = pixel_array
        else:
            # 16位或其他位深：按比例缩放截断到 0-255
            image_array = (pixel_array / 256).clip(0, 255).astype(np.uint8)

        # 确保只取前 3 个通道 (丢弃可能存在的 Alpha 通道)
        if image_array.ndim == 3 and image_array.shape[2] >= 3:
            image_array = image_array[:, :, :3]
        else:
            # 兜底：未知格式按灰度处理
            logger.warning(f"未知的数组形状: {image_array.shape}，尝试按灰度处理")
            normalized_array = self._normalize_grayscale(pixel_array)
            image_array = np.stack([normalized_array] * 3, axis=-1)

        return Image.fromarray(image_array, 'RGB')

    def save_as_png(self, output_path: str) -> Image.Image:
        """调用 get_png_image 得到 PIL Image，保存至目标路径，并返回该对象供获取宽高"""
        image = self.get_png_image()
        image.save(output_path, 'PNG')
        logger.info(f"DICOM 转码 PNG 成功，保存至: {output_path}")
        return image