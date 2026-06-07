import os
import cv2
import numpy as np
import logging
import onnxruntime as ort
from config import settings

logger = logging.getLogger(__name__)


class LesionExtractor:
    def __init__(self):
        self.session = None
        # 尝试加载 ONNX 模型
        model_path = os.path.join(os.path.dirname(__file__), "unet_weights.onnx")

        if os.path.exists(model_path):
            try:
                # 针对 CPU 优化
                sess_options = ort.SessionOptions()
                sess_options.intra_op_num_threads = 2
                sess_options.inter_op_num_threads = 1
                self.session = ort.InferenceSession(model_path, sess_options=sess_options,
                                                    providers=['CPUExecutionProvider'])
                logger.info(f"Successfully loaded ONNX model from {model_path}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}. Falling back to Gaussian placeholder.")
                self.session = None
        else:
            logger.warning(f"ONNX model not found at {model_path}. Falling back to Gaussian placeholder.")

    def generate(self, input_path: str, output_path: str, cancel_event=None):
        """生成病灶定位图与特征提取"""
        if cancel_event and cancel_event.is_set(): raise InterruptedError()

        if self.session:
            return self._generate_onnx(input_path, output_path, cancel_event)
        else:
            return self._generate_gaussian_placeholder(input_path, output_path, cancel_event)

    def _generate_onnx(self, input_path: str, output_path: str, cancel_event=None):
        """真实的 ONNX UNet 推理逻辑"""
        try:
            # 1. 读取并预处理原图
            img = cv2.imread(input_path)
            if img is None: raise ValueError(f"Failed to read image: {input_path}")

            orig_h, orig_w = img.shape[:2]
            input_img = cv2.resize(img, (384, 384))
            input_img = input_img.astype(np.float32) / 255.0
            input_img = np.transpose(input_img, (2, 0, 1))  # HWC -> CHW
            input_img = np.expand_dims(input_img, axis=0)  # Add batch dim

            if cancel_event and cancel_event.is_set(): raise InterruptedError()

            # 2. ONNX 推理
            input_name = self.session.get_inputs()[0].name
            output = self.session.run(None, {input_name: input_img})[0][0][0]  # 取出概率图

            if cancel_event and cancel_event.is_set(): raise InterruptedError()

            # 3. 后处理：Sigmoid -> 阈值 -> Resize回原尺寸
            probs = 1 / (1 + np.exp(-output))  # Sigmoid
            mask = (probs > 0.5).astype(np.uint8) * 255
            mask_resized = cv2.resize(mask, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

            # 4. 最大连通域提取 (极重要：剔除离散假阳性噪声)
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_resized, connectivity=8)

            final_mask = mask_resized
            max_label = -1

            if num_labels > 1:
                # 找到面积最大的连通域 (排除背景0)
                max_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
                final_mask = np.where(labels == max_label, 255, 0).astype(np.uint8)

            # 5. 特征计算
            total_pixels = orig_h * orig_w
            lesion_pixels = np.sum(final_mask > 0)
            coverage = lesion_pixels / total_pixels if total_pixels > 0 else 0.0

            # 计算重心确定位置 (严格输出纯中文方位)
            location = "中心"
            if lesion_pixels > 0:
                # 使用最大连通域的重心，如果没有则用图像中心
                cx, cy = centroids[max_label] if max_label != -1 else (orig_w / 2, orig_h / 2)
                rel_x, rel_y = cx / orig_w, cy / orig_h

                # 优化后的九宫格方位判定逻辑 (0.4 和 0.6 作为边界阈值)
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
                # 其他情况默认保持 "中心"

            # 6. 热力图叠加：Jet 色图 + 0.5 透明度叠加
            colored_mask = cv2.applyColorMap(final_mask, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img, 0.5, colored_mask, 0.5, 0)

            cv2.imwrite(output_path, overlay)

            # 返回特征字典 (对齐全中文契约)
            return {
                "coverage": round(float(coverage), 4),
                "location": location
            }

        except InterruptedError:
            raise
        except Exception as e:
            logger.error(f"ONNX inference failed: {e}. Falling back to Gaussian.")
            return self._generate_gaussian_placeholder(input_path, output_path, cancel_event)

    def _generate_gaussian_placeholder(self, input_path: str, output_path: str, cancel_event=None):
        """高斯模糊掩膜占位符逻辑 (降级兜底)"""
        logger.warning("Using Gaussian placeholder for lesion extraction.")
        img = cv2.imread(input_path)
        if img is None:
            raise ValueError(f"Failed to read image: {input_path}")

        h, w = img.shape[:2]
        mask = np.zeros(img.shape[:2], dtype=np.float32)

        # 生成随机高斯椭圆
        center = (int(w * 0.5), int(h * 0.5))
        axes = (int(w * 0.3), int(h * 0.3))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)

        mask = cv2.GaussianBlur(mask, (51, 51), 0)
        mask = (mask * 255).astype(np.uint8)

        # 改为 Jet 色图叠加，与真实模型输出对齐
        colored_mask = cv2.applyColorMap(mask, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img, 0.5, colored_mask, 0.5, 0)

        cv2.imwrite(output_path, overlay)

        # 兜底时返回占位特征 (对齐全中文契约)
        return {
            "coverage": 0.25,
            "location": "中心"
        }