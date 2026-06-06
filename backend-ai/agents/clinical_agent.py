import json
import logging
import re
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 2  # 最大重试次数

# 严格对齐实验方案的标准空 Schema
EMPTY_CLINICAL_SCHEMA = {
    "demographics": {"age": None, "gender": None, "skin_phototype": None},
    "lesion": {"location": None, "diameter_mm": None, "duration_months": None, "elevation": None, "evolution": None},
    "history": {"family_melanoma": None, "sun_exposure": None, "previous_cancer": None},
    "symptoms": {"bleeding": None, "itching": None, "pain": None, "ulceration": None},
    "abcd": {"asymmetry": None, "border_irregular": None, "color_variegation": None, "diameter_gt6mm": None,
             "evolution": None}
}

# 定义常见英文漂移的黑名单 (小写)
ENGLISH_BLACKLIST = ["male", "female", "left", "right", "sole", "palm", "yes", "no", "true", "false"]


def _validate_clinical_data(data: dict) -> str:
    """
    校验 LLM 输出的临床数据是否符合规范。
    返回错误信息字符串，如果无误则返回空字符串。
    """
    if not isinstance(data, dict):
        return "输出不是有效的 JSON 字典"

    # 1. 检查是否包含必须的顶层键
    required_keys = ["demographics", "lesion", "history", "symptoms", "abcd"]
    for key in required_keys:
        if key not in data:
            return f"缺少必须的顶层键: {key}"

    # 2. 语义漂移检查：严禁英文输出
    json_str = json.dumps(data, ensure_ascii=False).lower()
    for word in ENGLISH_BLACKLIST:
        # 简单粗暴但有效：检查 JSON 字符串中是否包含黑名单词汇
        if f'"{word}"' in json_str or f": {word}" in json_str or f": \"{word}" in json_str:
            return f"检测到非法英文输出: '{word}'，必须严格使用中文"

    return ""  # 验证通过


def _clean_llm_json_response(text: str) -> str:
    """清洗 LLM 返回的 Markdown 格式包裹的 JSON"""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_clinical_data(clinical_json_str: str = None, clinical_text: str = None) -> dict:
    """
    双通道病历解析 (含 LLM 自重试与校验机制)
    """
    # 通道 1：结构化 JSON 直接映射 (逻辑不变)
    if clinical_json_str:
        try:
            data = json.loads(clinical_json_str)
            mapped_data = EMPTY_CLINICAL_SCHEMA.copy()

            demographics = data.get("demographics", {})
            if demographics:
                mapped_data["demographics"]["age"] = demographics.get("age")
                mapped_data["demographics"]["gender"] = demographics.get("gender")
                mapped_data["demographics"]["skin_phototype"] = demographics.get("skin_phototype")

            lesion = data.get("lesion", {})
            if lesion:
                mapped_data["lesion"]["location"] = lesion.get("location")
                mapped_data["lesion"]["diameter_mm"] = lesion.get("diameter_mm")
                mapped_data["lesion"]["duration_months"] = lesion.get("duration_months")
                mapped_data["lesion"]["elevation"] = lesion.get("elevation")
                mapped_data["lesion"]["evolution"] = lesion.get("evolution")

            history = data.get("history", {})
            if history:
                mapped_data["history"]["family_melanoma"] = history.get("family_melanoma")
                mapped_data["history"]["sun_exposure"] = history.get("sun_exposure")
                mapped_data["history"]["previous_cancer"] = history.get("previous_cancer")

            symptoms = data.get("symptoms", {})
            if symptoms:
                mapped_data["symptoms"]["bleeding"] = symptoms.get("bleeding")
                mapped_data["symptoms"]["itching"] = symptoms.get("itching")
                mapped_data["symptoms"]["pain"] = symptoms.get("pain")
                mapped_data["symptoms"]["ulceration"] = symptoms.get("ulceration")

            logger.info("Successfully parsed structured clinical_json.")
            return mapped_data
        except Exception as e:
            logger.error(f"Failed to parse clinical_json: {e}. Falling back to empty schema.")
            return EMPTY_CLINICAL_SCHEMA

    # 通道 2：自由文本 LLM 提取 (加入自重试机制)
    if clinical_text:
        client = OpenAI(
            api_key=settings.INTEGRATION_API_KEY,
            base_url=settings.INTEGRATION_BASE_URL
        )

        base_prompt = f"""
你是一个严谨的皮肤病专科病历结构化提取助手。请从以下自由文本中提取关键临床特征，并严格按照提供的 JSON Schema 输出。
如果文本中未提及某字段，请将该字段设为 null。严禁输出任何诊断结论，只提取客观描述。

严格遵循以下规则：
1. 必须以纯JSON格式输出，不要有任何其他文字说明。
2. JSON必须包含以下键：demographics, lesion, history, symptoms, abcd (及其子键)。
3. 绝对禁止输出任何诊断性结论（如：提示黑色素瘤、疑似恶性等），只描述你看到的客观形态。
4. 【极其重要】所有提取的值必须使用中文输出（如“男”、“左足底”），严禁将中文翻译为英文（如禁止输出 male, left sole）！

输出 Schema 格式如下：
{json.dumps(EMPTY_CLINICAL_SCHEMA, ensure_ascii=False)}

待提取的自由文本：
{clinical_text}
"""

        feedback_msg = ""  # 初始化反馈信息

        for attempt in range(MAX_LLM_RETRIES):
            try:
                # 拼接反馈信息到 Prompt
                current_prompt = base_prompt
                if feedback_msg:
                    current_prompt += f"\n\n【重要纠正】：你上一次的输出违反了规则，错误原因为：'{feedback_msg}'。请务必修正并重新输出！"

                response = client.chat.completions.create(
                    model=settings.INTEGRATION_MODEL,
                    messages=[{"role": "user", "content": current_prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )

                result_str = response.choices[0].message.content
                cleaned_str = _clean_llm_json_response(result_str)
                parsed_data = json.loads(cleaned_str)

                # ===== 核心校验逻辑 =====
                validation_error = _validate_clinical_data(parsed_data)
                if not validation_error:
                    logger.info(f"Successfully extracted clinical_text using LLM (Attempt {attempt + 1}).")
                    return parsed_data
                else:
                    # 校验失败，准备重试
                    feedback_msg = validation_error
                    logger.warning(f"Validation failed (Attempt {attempt + 1}): {validation_error}. Retrying...")

            except Exception as e:
                logger.error(f"LLM clinical extraction API error (Attempt {attempt + 1}): {e}")
                feedback_msg = f"API调用或解析异常: {str(e)}"

        # 如果达到最大重试次数仍然失败，降级兜底
        logger.error(f"Max retries ({MAX_LLM_RETRIES}) reached. Falling back to EMPTY schema.")
        return EMPTY_CLINICAL_SCHEMA

    # 什么数据都没传，返回空 Schema
    return EMPTY_CLINICAL_SCHEMA