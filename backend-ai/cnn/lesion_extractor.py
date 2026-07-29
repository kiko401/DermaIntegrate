import os
import cv2
import numpy as np
import logging
import onnxruntime as ort
from config import settings

logger = logging.getLogger(__name__)

# 与模型训练时的预处理参数对齐
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class LesionExtractor:
    """基于 ONNX Runtime 执行分割推理，计算病灶面积占比与方位特征。"""

    def __init__(self):
        self.session = None
        model_path = os.path.join(os.path.dirname(__file__), "unet_weights.onnx")

        if os.path.exists(model_path):
            try:
                sess_options = ort.SessionOptions()
                sess_options.intra_op_num_threads = 2
                sess_options.inter_op_num_threads = 1
                # 优先使用 CUDA provider（GPU 加速），若不可用则回退到 CPU
                available_providers = ort.get_available_providers()
                if 'CUDAExecutionProvider' in available_providers:
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                    logger.info("Using CUDAExecutionProvider for ONNX inference.")
                else:
                    providers = ['CPUExecutionProvider']
                    logger.info("CUDA not available, using CPUExecutionProvider.")
                self.session = ort.InferenceSession(
                    model_path,
                    sess_options=sess_options,
                    providers=providers
                )
                logger.info(f"Successfully loaded ONNX model from {model_path}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}. Falling back to Gaussian placeholder.")
                self.session = None
        else:
            logger.warning(f"ONNX model not found at {model_path}. Falling back to Gaussian placeholder.")

    def generate(self, input_path: str, output_path: str, cancel_event=None) -> dict:
        """生成病灶掩膜图与热力图，并提取几何特征。"""
        if cancel_event and cancel_event.is_set():
            raise InterruptedError()

        if self.session:
            return self._generate_onnx(input_path, output_path, cancel_event)
        else:
            return self._generate_gaussian_placeholder(input_path, output_path, cancel_event)

    def _generate_onnx(self, input_path: str, output_path: str, cancel_event=None) -> dict:
        """执行 ONNX 模型推理。"""
        try:
            img = cv2.imread(input_path)
            if img is None:
                raise ValueError(f"Failed to read image: {input_path}")

            orig_h, orig_w = img.shape[:2]

            input_img = cv2.resize(img, (384, 384))
            input_img = input_img.astype(np.float32) / 255.0
            input_img = (input_img - IMAGENET_MEAN) / IMAGENET_STD
            input_img = np.transpose(input_img, (2, 0, 1))
            input_img = np.expand_dims(input_img, axis=0)

            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            input_name = self.session.get_inputs()[0].name
            output = self.session.run(None, {input_name: input_img})[0][0][0]

            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            probs = np.clip(output, 0.0, 1.0)
            mask = (probs > 0.5).astype(np.uint8) * 255
            mask_resized = cv2.resize(mask, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

            # 最大连通域去噪
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_resized, connectivity=8)

            final_mask = mask_resized
            max_label = -1

            if num_labels > 1:
                max_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
                final_mask = np.where(labels == max_label, 255, 0).astype(np.uint8)

            # 特征计算
            total_pixels = orig_h * orig_w
            lesion_pixels = np.sum(final_mask > 0)
            coverage = lesion_pixels / total_pixels if total_pixels > 0 else 0.0

            # 方位判定（九宫格）
            location = "中心"
            if lesion_pixels > 0 and max_label != -1:
                cx, cy = centroids[max_label]
                rel_x, rel_y = cx / orig_w, cy / orig_h

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

            # Jet 色图叠加输出
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
        """高斯模糊占位符，用于模型不可用时确保系统可演示。"""
        logger.warning("Using Gaussian placeholder for lesion extraction.")

        img = cv2.imread(input_path)
        if img is None:
            raise ValueError(f"Failed to read image: {input_path}")

        h, w = img.shape[:2]
        mask = np.zeros(img.shape[:2], dtype=np.float32)

        center = (int(w * 0.5), int(h * 0.5))
        axes = (int(w * 0.3), int(h * 0.3))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)

        mask = cv2.GaussianBlur(mask, (51, 51), 0)
        mask = (mask * 255).astype(np.uint8)

        colored_mask = cv2.applyColorMap(mask, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img, 0.5, colored_mask, 0.5, 0)

        cv2.imwrite(output_path, overlay)

        return {
            "coverage": 0.25,
            "location": "中心"
        }
