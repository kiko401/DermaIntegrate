import pydicom
import numpy as np
from PIL import Image

# 注意前面加了 r，防止 Windows 路径的 \ 被转义，结尾补上了引号
DICOM_PATH = r"D:\myProjects\DermaIntegrate\backend-ai\test_data\ISIC_1182408.dcm"

ds = pydicom.dcmread(DICOM_PATH)
pixel_array = ds.pixel_array

print(f"--- 诊断信息 ---")
print(f"PhotometricInterpretation: {ds.PhotometricInterpretation}")
print(f"像素数据类型: {pixel_array.dtype}")
print(f"像素形状: {pixel_array.shape}")
print(f"最大值: {np.max(pixel_array)}, 最小值: {np.min(pixel_array)}")

# 尝试三种方式保存，看哪种颜色对
# 方式1：直接当 RGB 输出（无视 YBR 标签）
if pixel_array.dtype == np.uint8:
    img_rgb_direct = Image.fromarray(pixel_array, 'RGB')
    img_rgb_direct.save("diagnose_1_direct_rgb.png")
    print("✅ 已生成 diagnose_1_direct_rgb.png (直接当RGB处理)")

# 方式2：强制用 pydicom 的转换
if 'YBR' in ds.PhotometricInterpretation:
    from pydicom.pixel_data_handlers.util import convert_color_space
    converted = convert_color_space(pixel_array, ds.PhotometricInterpretation, 'RGB')
    img_ybr_to_rgb = Image.fromarray(converted, 'RGB')
    img_ybr_to_rgb.save("diagnose_2_ybr_convert.png")
    print("✅ 已生成 diagnose_2_ybr_convert.png (强制YBR转RGB)")

# 方式3：按位深截断当 RGB 输出（针对16位图）
if pixel_array.dtype != np.uint8:
    scaled = (pixel_array / 256).clip(0, 255).astype(np.uint8)
    img_scaled_rgb = Image.fromarray(scaled, 'RGB')
    img_scaled_rgb.save("diagnose_3_scaled_rgb.png")
    print("✅ 已生成 diagnose_3_scaled_rgb.png (16位缩放当RGB处理)")