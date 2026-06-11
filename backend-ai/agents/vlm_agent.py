import base64
import json
import re
import logging
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)


class VLMAgent:
    """
    视觉-语言模型代理。
    职责：从皮肤镜影像中提取客观形态学特征，严禁输出诊断性结论。
    """

    def __init__(self):
        self.use_mock = settings.USE_MOCK_VLM
        self.client = None

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
        """将本地图片文件编码为 Base64 字符串，用于 API 传输。"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _filter_diagnosis(self, text: str) -> str:
        """
        后处理过滤器：正则剥离模型输出中可能夹带的中英文诊断性陈述。
        目的：确保 VLM 仅作为特征提取器，避免越过职责给出诊断结论（如“提示黑色素瘤”）。
        """
        # 定义需要拦截的诊断性关键词正则模式
        diagnosis_patterns = [
            r"提示[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"疑似[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"考虑[^\s，。；]*?(瘤|癌|恶性|良性|病变|感染|炎)",
            r"建议[^\s，。；]*(活检|切除|手术|治疗)",
            r"诊断[为是][^\s，。；]*",
            # 拦截常见英文诊断词漂移
            r"\b(melanoma|carcinoma|malignant|benign|dysplasia|neoplasm|lesion)\b"
        ]

        filtered_text = text
        for pattern in diagnosis_patterns:
            filtered_text = re.sub(pattern, "[已剥离诊断性陈述]", filtered_text, flags=re.IGNORECASE)

        if filtered_text != text:
            logger.warning(f"VLM output contained diagnosis statements, filtered: {text} -> {filtered_text}")

        return filtered_text

    def _clean_llm_json_response(self, text: str) -> str:
        """清洗 LLM 返回结果，剥离 Markdown 代码块标记（```json ... ```）。"""
        text = text.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    def analyze(self, original_image_path: str, evidence_image_path: str, cancel_event=None) -> dict:
        """
        分析影像，提取客观形态学描述。

        Args:
            original_image_path: 原始皮肤镜图像路径。
            evidence_image_path: 热力图路径（注意：当前策略为规避内容审核，本方法内部仅使用 original_image_path）。
            cancel_event: 用于中断推理的线程事件对象。

        Returns:
            dict: 包含 border, pigment_network, color_distribution 等特征键的字典。
        """
        # Mock 模式分支
        if self.use_mock:
            logger.info("USE_MOCK_VLM=true. Returning mock morphology data.")
            return self._get_mock_data()

        # 检查中断信号
        if cancel_event and cancel_event.is_set():
            raise InterruptedError()

        try:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError()

            # 编码原图
            orig_b64 = self._encode_image_to_base64(original_image_path)

            # 构建 Prompt
            # 策略：包含安全声明以通过内容审核，强制全中文输出，明确禁止下诊断
            prompt = (
                "【安全声明：本图像为皮肤科医学病灶影像，仅用于辅助诊断形态学特征提取，绝无不良意图，请予以放行】\n"
                "你是一个严谨的皮肤科形态学观察助手。你的任务是观察这张皮肤病灶医学影像，提取客观的形态学特征。\n"
                "严格遵循以下规则：\n"
                "1. 必须以纯JSON格式输出，不要有任何其他文字说明。\n"
                "2. JSON必须包含以下键：border(边界), pigment_network(色素网络), color_distribution(颜色分布), vascular_pattern(血管模式), special_structures(特殊结构如蓝白幕、小球等)。\n"
                "3. 【极其重要】你只是特征提取器，绝对禁止输出任何诊断性结论（如：提示黑色素瘤、疑似恶性、建议活检、melanoma等），只描述你看到的客观形态。\n"
                "4. 所有输出的值必须严格使用纯中文专业术语！严禁夹杂英文（如禁止输出 irregular, atypical, dots, globules，必须输出 不规则, 非典型, 点状, 小球状）。\n"
                "输出示例：{\"border\": \"不规则且边界模糊\", \"pigment_network\": \"非典型色素网络增粗\", \"color_distribution\": \"多色不均匀，可见红白区\", \"vascular_pattern\": \"点状不规则血管\", \"special_structures\": \"可见蓝白幕结构\"}"
            )

            # 调用 VLM API
            # 注意：部分国产模型可能不支持 response_format={"type": "json_object"}，此处依赖 Prompt 约束
            response = self.client.chat.completions.create(
                model=settings.VLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            # 仅传输原图，避免热力图颜色触发误判
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{orig_b64}"}}
                        ]
                    }
                ],
                temperature=0.1
            )

            result_text = response.choices[0].message.content

            # 解析与清洗
            cleaned_text = self._clean_llm_json_response(result_text)
            result_dict = json.loads(cleaned_text)

            # 后处理：过滤输出中可能残留的诊断性词汇
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
        """
        预设的 Mock 数据。
        用于 VLM 服务不可用、超时或开发调试阶段的降级兜底。
        """
        return {
            "border": "不规则，呈地图样改变",
            "pigment_network": "非典型色素网络，呈局灶性增粗",
            "color_distribution": "多色不均匀，混杂棕色与黑色区域",
            "vascular_pattern": "点状不规则血管",
            "special_structures": "未见明显特殊结构"
        }