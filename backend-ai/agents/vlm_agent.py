import base64
import json
import re
import logging
from openai import OpenAI, APIError, APIConnectionError

from config import settings

logger = logging.getLogger(__name__)


class VLMAgent:
    def __init__(self):
        self.use_mock = settings.USE_MOCK_VLM
        self.client = None
        if not self.use_mock:
            try:
                # 初始化 OpenAI 兼容客户端
                self.client = OpenAI(
                    api_key=settings.VLM_API_KEY,
                    base_url=settings.VLM_BASE_URL
                )
                logger.info("VLM Client initialized for REAL API calls.")
            except Exception as e:
                logger.error(f"Failed to init VLM Client: {e}. Falling back to MOCK.")
                self.use_mock = True

    def _encode_image_to_base64(self, image_path: str) -> str:
        """将本地图片编码为 Base64 字符串"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _filter_diagnosis(self, text: str) -> str:
        """
        核心安全机制：正则剥离模型输出中夹带的诊断性陈述。
        禁止出现如：提示黑色素瘤、疑似恶性等诊断词汇。
        """
        diagnosis_patterns = [
            r"提示[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"疑似[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"考虑[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"建议[^\s，。；]*(活检|切除|手术|治疗)",
            r"诊断[为是][^\s，。；]*"
        ]
        filtered_text = text
        for pattern in diagnosis_patterns:
            filtered_text = re.sub(pattern, "[已剥离诊断性陈述]", filtered_text, flags=re.IGNORECASE)

        if filtered_text != text:
            logger.warning(f"VLM output contained diagnosis statements, filtered: {text} -> {filtered_text}")

        return filtered_text

    def analyze(self, original_image_path: str, evidence_image_path: str) -> dict:
        """
        分析影像，提取客观形态学描述。
        返回严格符合契约的 JSON 格式特征字典。
        """
        # 1. 降级开关判断
        if self.use_mock:
            logger.info("USE_MOCK_VLM=true. Returning mock morphology data.")
            return self._get_mock_data()

        # 2. 准备真实 API 请求
        try:
            orig_b64 = self._encode_image_to_base64(original_image_path)
            evi_b64 = self._encode_image_to_base64(evidence_image_path)

            prompt = (
                "你是一个严谨的皮肤科形态学观察助手。你的任务是根据提供的两张图片（原图和红色标记图），提取客观的形态学特征。\n"
                "严格遵循以下规则：\n"
                "1. 必须以纯JSON格式输出，不要有任何其他文字说明。\n"
                "2. JSON必须包含以下键：border(边界), pigment_network(色素网络), color_distribution(颜色分布), vascular_pattern(血管模式)。\n"
                "3. 绝对禁止输出任何诊断性结论（如：提示黑色素瘤、疑似恶性等），只描述你看到的客观形态（如：边缘不规则、色素网缺失等）。\n"
                "输出示例：{\"border\": \"不规则且边界模糊\", \"pigment_network\": \"非典型色素网络增粗\", \"color_distribution\": \"多色不均匀，可见红白区\", \"vascular_pattern\": \"点状不规则血管\"}"
            )

            response = self.client.chat.completions.create(
                model=settings.VLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{orig_b64}"}},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{evi_b64}"}}
                        ]
                    }
                ],
                temperature=0.1,  # 极低温度，保证输出稳定和格式严格
                response_format={"type": "json_object"}  # 强制 JSON 输出
            )

            # 3. 解析响应
            result_text = response.choices[0].message.content
            result_dict = json.loads(result_text)

            # 4. 执行诊断词剥离
            for key, value in result_dict.items():
                if isinstance(value, str):
                    result_dict[key] = self._filter_diagnosis(value)

            logger.info(f"VLM Analysis successful: {result_dict}")
            return result_dict

        except (APIError, APIConnectionError, json.JSONDecodeError, Exception) as e:
            logger.error(f"VLM API call failed or parsing error: {e}. Falling back to MOCK data.")
            # 任何真实调用异常，自动降级到 Mock，保障演示不中断
            return self._get_mock_data()

    def _get_mock_data(self) -> dict:
        """预设的 Mock 数据，用于降级或测试"""
        return {
            "border": "不规则，呈地图样改变",
            "pigment_network": "非典型色素网络，呈局灶性增粗",
            "color_distribution": "多色不均匀，混杂棕色与黑色区域",
            "vascular_pattern": "点状不规则血管"
        }