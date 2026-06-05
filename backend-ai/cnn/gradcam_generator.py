import torch
import torch.nn.functional as F
from torchvision import models, transforms
from PIL import Image
import numpy as np
import cv2
import logging
import os

logger = logging.getLogger(__name__)


class GradCAMGenerator:
    def __init__(self):
        # 设备自适应：有 GPU 用 GPU，没有用 CPU
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"Grad-CAM using device: {self.device}")

        # 加载预训练 ResNet50
        self.model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1).to(self.device)
        self.model.eval()

        # 图像预处理管线
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

        self.gradients = None
        self.activations = None

    def _backward_hook(self, module, grad_input, grad_output):
        """反向传播 Hook：抓取梯度"""
        self.gradients = grad_output[0].detach()

    def _forward_hook(self, module, input, output):
        """前向传播 Hook：抓取特征图"""
        self.activations = output.detach()

    def generate(self, image_path: str, output_path: str) -> str:
        """
        生成 Grad-CAM 热力图并叠加原图保存
        :param image_path: 输入原图路径
        :param output_path: 热力图输出路径
        :return: 输出路径
        """
        # 1. 读取并预处理图像
        img = Image.open(image_path).convert('RGB')
        input_tensor = self.transform(img).unsqueeze(0).to(self.device)

        # 2. 注册 Hook 到 ResNet 最后一个卷积层 (layer4)
        target_layer = self.model.layer4[-1]
        # 关键修正：使用 register_full_backward_hook 替代废弃的 register_backward_hook
        handle_fw = target_layer.register_forward_hook(self._forward_hook)
        handle_bw = target_layer.register_full_backward_hook(self._backward_hook)

        # 3. 前向推理
        output = self.model(input_tensor)
        # 获取预测概率最高的类别索引
        target_class = output.argmax(dim=1).item()

        # 4. 反向传播计算梯度
        self.model.zero_grad()
        output[0, target_class].backward(retain_graph=False)

        # 5. 计算 Grad-CAM 权重与热力图
        # 全局平均池化梯度得到权重
        pooled_gradients = torch.mean(self.gradients, dim=[0, 2, 3])
        activations = self.activations

        # 权重乘以特征图
        for i in range(activations.shape[1]):
            activations[:, i, :, :] *= pooled_gradients[i]

        # 计算热力图并 ReLU
        heatmap = torch.mean(activations, dim=1).squeeze().cpu().numpy()
        heatmap = np.maximum(heatmap, 0)
        # 归一化到 0-1
        max_val = np.max(heatmap)
        heatmap /= max_val if max_val != 0 else 1

        # 6. 叠加到原图上
        img_cv2 = cv2.imread(image_path)
        # 将热力图 resize 到原图尺寸
        heatmap_resized = cv2.resize(heatmap, (img_cv2.shape[1], img_cv2.shape[0]))
        # 转为 0-255 的 uint8 并应用伪彩色映射
        heatmap_colored = cv2.applyColorMap(np.uint8(255 * heatmap_resized), cv2.COLORMAP_JET)

        # 原图与热力图按比例融合
        superimposed_img = cv2.addWeighted(img_cv2, 0.6, heatmap_colored, 0.4, 0)

        # 7. 保存结果
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, superimposed_img)

        # 清理 Hook
        handle_fw.remove()
        handle_bw.remove()

        logger.info(f"Grad-CAM heatmap generated and saved to: {output_path}")
        return output_path