import base64
import json
import re
import logging
from pathlib import Path
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)


class VLMAgent:
    """视觉-语言模型代理，负责从皮肤镜影像中提取客观形态学特征。"""

    def __init__(self):
        self.use_mock = settings.USE_MOCK_VLM
        self.client = None
        self._prompt_template = (
            Path(__file__).parent.parent / "prompts" / "vlm_analyze.txt"
        ).read_text(encoding="utf-8")

        if not self.use_mock:
            try:
                self.client = OpenAI(
                    api_key=settings.VLM_API_KEY,
                    base_url=settings.VLM_BASE_URL
                )
                logger.info("VLM Client initialized for REAL API calls.")
            except Exception as e:
                logger.error(f"Failed to init VLM Client: {e}. Falling back to MOCK.")
                self.use_mock = True

    def _encode_image_to_base64(self, image_path: str) -> str:
        """将本地图片编码为 base64 字符串。"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _filter_diagnosis(self, text: str) -> str:
        """后处理过滤：剔除模型输出中可能夹带的诊断性陈述（如"提示黑色素瘤"等）。"""
        diagnosis_patterns = [
            r"提示[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"疑似[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"考虑[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"建议[^\s，。；]*(活检|切除|手术|治疗)",
            r"诊断[为是][^\s，。；]*",
            r"\b(melanoma|carcinoma|malignant|benign|dysplasia|neoplasm|lesion)\b"
        ]

        filtered_text = text
        for pattern in diagnosis_patterns:
            filtered_text = re.sub(pattern, "[已剥离诊断性陈述]", filtered_text, flags=re.IGNORECASE)

        if filtered_text != text:
            logger.warning(f"VLM output contained diagnosis statements, filtered: {text} -> {filtered_text}")

        return filtered_text

    def _clean_llm_json_response(self, text: str) -> str:
        """剥离 Markdown 代码块标记和思考过程。"""
        text = text.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"(\{[\s\S]*\})", text)
        if match:
            return match.group(1).strip()
        return text

    def analyze(self, original_image_path: str, evidence_image_path: str, cancel_event=None) -> dict:
        """
        分析影像并提取客观形态学描述。

        Args:
            original_image_path: 原始皮肤镜图像路径。
            evidence_image_path: 热力图路径（当前版本中仅使用 original_image_path）。
            cancel_event: 用于中断推理的线程事件对象。

        Returns:
            dict: 包含 border, pigment_network, color_distribution 等特征的字典。
        """
        if self.use_mock:
            logger.info("USE_MOCK_VLM=true. Returning mock morphology data.")
            return self._get_mock_data()

        if cancel_event and cancel_event.is_set():
            raise InterruptedError()

        try:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            orig_b64 = self._encode_image_to_base64(original_image_path)

            # 注意：部分国产模型需在 Prompt 中附带安全声明方可放行图像
            prompt = self._prompt_template

            response = self.client.chat.completions.create(
                model=settings.VLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            # 仅传原图，避免热力图触发误判
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{orig_b64}"}}
                        ]
                    }
                ],
                temperature=0.1
            )

            result_text = response.choices[0].message.content
            cleaned_text = self._clean_llm_json_response(result_text)
            result_dict = json.loads(cleaned_text)

            # 后处理：过滤残留的诊断性词汇
            for key, value in result_dict.items():
                if isinstance(value, str):
                    result_dict[key] = self._filter_diagnosis(value)

            logger.info(f"VLM Analysis successful: {result_dict}")
            return result_dict

        except Exception as e:
            if isinstance(e, InterruptedError):
                raise e
            logger.error(f"VLM API call failed or parsing error: {e}. Falling back to MOCK data.")
            return self._get_mock_data()

    def _get_mock_data(self) -> dict:
        """Mock 降级数据，用于 VLM 不可用或开发调试阶段。"""
        return {
            "border": "不规则，呈地图样改变",
            "pigment_network": "非典型色素网络，呈局灶性增粗",
            "color_distribution": "多色不均匀，混杂棕色与黑色区域",
            "vascular_pattern": "点状不规则血管",
            "special_structures": "未见明显特殊结构"
        }
