import os
import json
import logging
import re
from openai import OpenAI

logger = logging.getLogger(__name__)

# 严格对齐实验方案的标准空 Schema
EMPTY_CLINICAL_SCHEMA = {
    "demographics": {"age": None, "gender": None, "skin_phototype": None},
    "lesion": {"location": None, "diameter_mm": None, "duration_months": None, "elevation": None, "evolution": None},
    "history": {"family_melanoma": None, "sun_exposure": None, "previous_cancer": None},
    "symptoms": {"bleeding": None, "itching": None, "pain": None, "ulceration": None},
    "abcd": {"asymmetry": None, "border_irregular": None, "color_variegation": None, "diameter_gt6mm": None,
             "evolution": None}
}


def _clean_llm_json_response(text: str) -> str:
    """清洗 LLM 返回的 Markdown 格式包裹的 JSON"""
    text = text.strip()
    # 匹配 ```json ... ``` 或 ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_clinical_data(clinical_json_str: str = None, clinical_text: str = None) -> dict:
    """
    双通道病历解析
    :param clinical_json_str: 前端传入的结构化 JSON 字符串
    :param clinical_text: 前端传入的自由文本
    :return: 统一的标准 Schema 字典
    """
    # 通道 1：结构化 JSON 直接映射
    if clinical_json_str:
        try:
            data = json.loads(clinical_json_str)
            mapped_data = EMPTY_CLINICAL_SCHEMA.copy()

            # 安全映射逻辑
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

    # 通道 2：自由文本 LLM 提取
    if clinical_text:
        try:
            client = OpenAI(
                api_key=os.getenv("INTEGRATION_API_KEY", os.getenv("VLM_API_KEY")),
                base_url=os.getenv("INTEGRATION_BASE_URL", os.getenv("VLM_BASE_URL"))
            )
            prompt = f"""
你是一个严谨的皮肤病专科病历结构化提取助手。请从以下自由文本中提取关键临床特征，并严格按照提供的 JSON Schema 输出。
如果文本中未提及某字段，请将该字段设为 null。严禁输出任何诊断结论，只提取客观描述。

输出 Schema 格式如下：
{json.dumps(EMPTY_CLINICAL_SCHEMA, ensure_ascii=False)}

待提取的自由文本：
{clinical_text}
"""
            response = client.chat.completions.create(
                model=os.getenv("INTEGRATION_MODEL", "deepseek-chat"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result_str = response.choices[0].message.content
            cleaned_str = _clean_llm_json_response(result_str)
            parsed_data = json.loads(cleaned_str)

            logger.info("Successfully extracted clinical_text using LLM.")
            return parsed_data

        except Exception as e:
            logger.error(f"LLM clinical extraction failed: {e}")
            return EMPTY_CLINICAL_SCHEMA

    # 什么数据都没传，返回空 Schema
    return EMPTY_CLINICAL_SCHEMA