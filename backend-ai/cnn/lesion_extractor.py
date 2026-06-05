import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


class LesionExtractor:
    """
    病灶视觉定位提取器。
    当前版本：使用高斯模糊伪掩码作为占位符，验证工程管线。
    未来版本：加载训练好的 U-Net 权重，执行精确的像素级分割推理。
    """

    def __init__(self):
        # TODO: 未来在这里加载 U-Net 模型权重
        # self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        # self.model = UNet().to(self.device)
        # self.model.load_state_dict(torch.load('unet_weights.pth'))
        # self.model.eval()
        logger.info("LesionExtractor initialized (Currently using MOCK Gaussian Mask).")

    def generate(self, image_path: str, output_path: str) -> str:
        """
        提取病灶视觉证据并保存叠加图
        :param image_path: 输入原图路径
        :param output_path: 叠加图输出路径
        :return: 输出路径
        """
        img_cv2 = cv2.imread(image_path)
        if img_cv2 is None:
            raise ValueError(f"无法读取图片: {image_path}")

        h, w = img_cv2.shape[:2]

        # ================= 核心占位逻辑：生成伪 Mask =================
        # 在图像中心生成一个椭圆形的高斯概率分布，模拟 U-Net 输出的概率图
        center_x, center_y = w // 2, h // 2
        axes_length = (w // 3, h // 3)  # 椭圆长短轴

        # 创建空白 mask
        mask = np.zeros((h, w), dtype=np.float32)

        # 绘制一个粗椭圆作为基底
        cv2.ellipse(mask, (center_x, center_y), axes_length, 0, 0, 360, 1.0, -1)

        # 高斯模糊平滑边缘，模拟概率图的渐变
        mask = cv2.GaussianBlur(mask, (51, 51), 0)

        # 二值化，设定阈值为 0.3，大于 0.3 的区域被认为是病灶
        _, binary_mask = cv2.threshold(mask, 0.3, 1.0, cv2.THRESH_BINARY)
        # ===========================================================

        # TODO: 未来替换为真实 U-Net 推理逻辑
        # input_tensor = self.transform(img_cv2).unsqueeze(0).to(self.device)
        # with torch.no_grad():
        #     pred_mask = self.model(input_tensor).squeeze().cpu().numpy()
        # binary_mask = (pred_mask > 0.5).astype(np.float32)

        # 将 Mask 转为红色半透明蒙版叠加到原图
        overlay = img_cv2.copy()
        # 构建红色蒙版 (B=0, G=0, R=255)
        red_overlay = np.zeros_like(img_cv2)
        red_overlay[:, :, 2] = 255  # R通道

        # 只在 mask 为 1 的区域叠加红色
        mask_3channel = np.stack([binary_mask] * 3, axis=-1).astype(np.uint8)
        overlay = cv2.bitwise_and(red_overlay, red_overlay, mask=mask_3channel[:, :, 0].astype(np.uint8))

        # 加权混合原图和红色蒙版
        alpha = 0.4  # 红色透明度
        superimposed_img = cv2.addWeighted(img_cv2, 1, overlay, alpha, 0)

        # 保存结果
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, superimposed_img)

        logger.info(f"Lesion evidence image generated and saved to: {output_path}")
        return output_path