import os
import cv2
import numpy as np
import logging
import onnxruntime as ort
from config import settings

logger = logging.getLogger(__name__)

# ==========================================================
# 预处理常量
# ==========================================================
# 注意：必须与模型训练时的预处理参数完全对齐。
# 此处采用 ImageNet 标准化，用于归一化输入图像。
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class LesionExtractor:
    """
    病灶提取器。
    基于 ONNX Runtime 执行分割推理，并计算病灶的面积占比与方位特征。
    """

    def __init__(self):
        self.session = None
        # 尝试加载 ONNX 权重文件
        model_path = os.path.join(os.path.dirname(__file__), "unet_weights.onnx")

        if os.path.exists(model_path):
            try:
                # 针对 CPU 环境的 Session 优化配置
                sess_options = ort.SessionOptions()
                sess_options.intra_op_num_threads = 2
                sess_options.inter_op_num_threads = 1
                self.session = ort.InferenceSession(
                    model_path,
                    sess_options=sess_options,
                    providers=['CPUExecutionProvider']
                )
                logger.info(f"Successfully loaded ONNX model from {model_path}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}. Falling back to Gaussian placeholder.")
                self.session = None
        else:
            logger.warning(f"ONNX model not found at {model_path}. Falling back to Gaussian placeholder.")

    def generate(self, input_path: str, output_path: str, cancel_event=None) -> dict:
        """
        生成病灶掩膜图与热力图，并提取几何特征。

        Args:
            input_path: 原始图像路径。
            output_path: 生成的热力图保存路径。
            cancel_event: 用于中断推理的事件对象。

        Returns:
            dict: 包含 coverage (病灶占比) 和 location (方位) 的字典。
        """
        if cancel_event and cancel_event.is_set():
            raise InterruptedError()

        # 根据模型加载情况选择推理策略
        if self.session:
            return self._generate_onnx(input_path, output_path, cancel_event)
        else:
            return self._generate_gaussian_placeholder(input_path, output_path, cancel_event)

    def _generate_onnx(self, input_path: str, output_path: str, cancel_event=None) -> dict:
        """执行真实的 ONNX 模型推理"""
        try:
            # 1. 读取与预处理
            img = cv2.imread(input_path)
            if img is None:
                raise ValueError(f"Failed to read image: {input_path}")

            orig_h, orig_w = img.shape[:2]

            # 调整大小至模型输入尺寸 (如 384x384)
            input_img = cv2.resize(img, (384, 384))

            # 归一化：Scale -> Subtract Mean -> Divide Std
            input_img = input_img.astype(np.float32) / 255.0
            input_img = (input_img - IMAGENET_MEAN) / IMAGENET_STD

            # 调整维度顺序: HWC -> CHW -> Batch(1)
            input_img = np.transpose(input_img, (2, 0, 1))
            input_img = np.expand_dims(input_img, axis=0)

            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            # 2. ONNX 推理
            input_name = self.session.get_inputs()[0].name
            # 注意：导出的模型已封装 Sigmoid，输出为概率图 [0, 1]
            output = self.session.run(None, {input_name: input_img})[0][0][0]

            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            # 3. 后处理
            # 防御性截断：确保数值在 [0, 1] 范围内，防止精度溢出
            probs = np.clip(output, 0.0, 1.0)

            # 二值化：阈值 0.5
            mask = (probs > 0.5).astype(np.uint8) * 255

            # 还原至原图尺寸 (使用最近邻插值保持像素级边缘)
            mask_resized = cv2.resize(mask, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

            # 4. 最大连通域提取 (去噪)
            # 目的：剔除离散的假阳性噪点，保留最大的主病灶区域
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_resized, connectivity=8)

            final_mask = mask_resized
            max_label = -1

            if num_labels > 1:
                # stats[0] 是背景，从 stats[1] 开始找最大面积
                max_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
                final_mask = np.where(labels == max_label, 255, 0).astype(np.uint8)

            # 5. 特征计算
            total_pixels = orig_h * orig_w
            lesion_pixels = np.sum(final_mask > 0)
            coverage = lesion_pixels / total_pixels if total_pixels > 0 else 0.0

            # 方位判定：基于病灶重心 (九宫格逻辑)
            location = "中心"
            if lesion_pixels > 0 and max_label != -1:
                cx, cy = centroids[max_label]
                rel_x, rel_y = cx / orig_w, cy / orig_h

                # 定义中心区域阈值 (0.4 - 0.6)，其余为边缘
                if rel_x < 0.4 and rel_y < 0.4:
                    location = "左上"
                elif rel_x > 0.6 and rel_y < 0.4:
                    location = "右上"
                elif rel_x < 0.4 and rel_y > 0.6:
                    location = "左下"
                elif rel_x > 0.6 and rel_y > 0.6:
                    location = "右下"
                elif rel_x < 0.4:
                    location = "左"
                elif rel_x > 0.6:
                    location = "右"
                elif rel_y < 0.4:
                    location = "上"
                elif rel_y > 0.6:
                    location = "下"

            # 6. 可视化输出
            # 生成 Jet 色图并以 50% 透明度叠加在原图上
            colored_mask = cv2.applyColorMap(final_mask, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img, 0.5, colored_mask, 0.5, 0)

            cv2.imwrite(output_path, overlay)

            return {
                "coverage": round(float(coverage), 4),
                "location": location
            }

        except InterruptedError:
            raise
        except Exception as e:
            logger.error(f"ONNX inference failed: {e}. Falling back to Gaussian.")
            return self._generate_gaussian_placeholder(input_path, output_path, cancel_event)

    def _generate_gaussian_placeholder(self, input_path: str, output_path: str, cancel_event=None) -> dict:
        """
        生成高斯模糊掩膜占位符 (降级兜底策略)。
        当模型不可用时，生成一个位于图像中心的模拟病灶，确保系统可演示。
        """
        logger.warning("Using Gaussian placeholder for lesion extraction.")

        img = cv2.imread(input_path)
        if img is None:
            raise ValueError(f"Failed to read image: {input_path}")

        h, w = img.shape[:2]
        mask = np.zeros(img.shape[:2], dtype=np.float32)

        # 在图像中心绘制一个椭圆作为模拟病灶
        center = (int(w * 0.5), int(h * 0.5))
        axes = (int(w * 0.3), int(h * 0.3))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)

        # 高斯模糊边缘
        mask = cv2.GaussianBlur(mask, (51, 51), 0)
        mask = (mask * 255).astype(np.uint8)

        # 生成与真实模型一致的 Jet 色图叠加
        colored_mask = cv2.applyColorMap(mask, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img, 0.5, colored_mask, 0.5, 0)

        cv2.imwrite(output_path, overlay)

        return {
            "coverage": 0.25,
            "location": "中心"
        }