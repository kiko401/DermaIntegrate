import json
import logging
import re
import copy
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 2  # 最大重试次数

# ==========================================================
# 1. 对齐 PAD-UFES-20 的标准空 Schema (v3.1 契约)
# ==========================================================
EMPTY_CLINICAL_SCHEMA = {
    "patient_info": {"age": None, "gender": None, "fitzpatrick_skin_type": None},
    "lifestyle_history": {"smoke": None, "drink": None, "pesticide_exposure": None},
    "family_history": {"background_father": None, "background_mother": None},
    "personal_history": {"skin_cancer_history": None, "other_cancer_history": None},
    "lesion_clinical": {
        "region": None, "diameter_1_mm": None, "diameter_2_mm": None,
        "elevation": None, "biopsed": None
    },
    "lesion_symptoms": {"itch": None, "hurt": None, "changed": None, "bleed": None, "grew": None}
}

# ==========================================================
# 2. 强制中文映射表 (核心防漂移与跨模态依赖保障)
# ==========================================================
GENDER_MAP = {"male": "男", "female": "女", "m": "男", "f": "女"}
REGION_MAP = {
    "ABDOMEN": "腹部", "BACK": "背部", "CHEST": "胸部", "FACE": "面部",
    "FOOT": "足部", "FOREARM": "前臂", "HAND": "手部", "LATERAL CHEST": "侧胸",
    "LOWER LIMB": "下肢", "NECK": "颈部", "NOSE": "鼻部", "SCALP": "头皮",
    "THIGH": "大腿", "UPPER LIMB": "上肢", "EAR": "耳部", "LIP": "唇部",
    "ORAL": "口腔", "NASAL": "鼻腔", "GENITAL": "生殖器",
    # 🚨 新增：补全 LLM 常见自由文本输出与大词的映射，确保病理 Agent 触发
    "SOLE": "足底", "PALM": "手掌", "HEEL": "足跟",
    "FINGER": "手指", "TOE": "足趾", "NAIL": "甲床", "THUMB": "拇指",
    "BIG TOE": "拇趾", "GREAT TOE": "拇趾"
}

# 扩充英文漂移黑名单 (针对 PAD-UFES-20 常见英文字段)
ENGLISH_BLACKLIST = [
    "male", "female",  # 移除了 "m" 和 "f"，防止误伤布尔值缩写
    "left", "right", "sole", "palm", "scalp", "face", "abdomen", "back", "foot", "hand",
    "yes", "no", "neck", "ear", "chest", "arm", "leg"
    # 注意：移除了 "true" 和 "false"，防止误拦 JSON 原生布尔值
]

# 🚨 新增：后置部位语义清洗映射表（极重要：确保跨模态触发词 100% 对齐）
# 将口语/俗称/细粒度词，清洗为包含病理 Agent 触发核心词的规范中文
REGION_NORMALIZATION_MAP = {
    "脚": "足", "脚底": "足底", "脚跟": "足跟", "脚趾": "足趾", "脚背": "足背",
    "大拇趾": "拇趾", "大脚趾": "拇趾",
    "手掌心": "手掌", "手心": "手掌", "手指头": "手指", "大拇指": "拇指",
    "鼻翼": "鼻部", "鼻侧": "鼻部", "鼻腔内": "鼻腔",
    "口腔内": "口腔", "嘴唇": "唇部", "下唇": "唇部", "上唇": "唇部",
}


def _is_truthy(value) -> bool:
    """防御性布尔值判定，兼容各种变体"""
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value > 0
    if isinstance(value, str): return value.strip().lower() in ["true", "1", "有", "是", "yes"]
    return False


def _map_gender(raw_gender) -> str:
    """性别强制中文映射"""
    if not raw_gender: return None
    val = str(raw_gender).lower().strip()
    return GENDER_MAP.get(val, raw_gender)  # 映射命中返中文，未命中保留原值(可能是中文)


def _normalize_region_for_triggers(region_str: str) -> str:
    """
    后置语义清洗：将 LLM 输出的细粒度/口语部位，清洗为包含病理触发核心词的规范中文。
    例如："左脚底" -> "左足底" (确保包含"足"字，触发肢端逻辑)
    """
    if not region_str:
        return None

    for old, new in REGION_NORMALIZATION_MAP.items():
        region_str = region_str.replace(old, new)

    return region_str


def _map_region(raw_region) -> str:
    """部位强制中文映射 + 触发词深度清洗"""
    if not raw_region: return None
    val = str(raw_region).upper().strip()

    # 1. 先查静态映射表 (针对结构化 JSON 输入的大词，如 FOOT->足部)
    mapped = REGION_MAP.get(val, raw_region)

    # 2. 如果没命中映射表（说明是 LLM 自由文本输出的中文，如"左脚底"），进行后置语义清洗
    if mapped == raw_region:
        mapped = _normalize_region_for_triggers(mapped)

    return mapped


def _validate_clinical_data(data: dict) -> str:
    """
    校验 LLM 输出的临床数据是否符合规范 (保留原有优秀设计，升级校验规则)
    """
    if not isinstance(data, dict):
        return "输出不是有效的 JSON 字典"

    # 1. 检查是否包含必须的顶层键 (对齐新 Schema)
    required_keys = ["patient_info", "lifestyle_history", "family_history", "personal_history", "lesion_clinical",
                     "lesion_symptoms"]
    for key in required_keys:
        if key not in data:
            return f"缺少必须的顶层键: {key}"

    # 2. 语义漂移检查：严禁英文输出 (防止 LLM 将中文翻译为英文)
    json_str = json.dumps(data, ensure_ascii=False).lower()
    for word in ENGLISH_BLACKLIST:
        if f'"{word}"' in json_str or f": {word}" in json_str or f": \"{word}" in json_str:
            return f"检测到非法英文输出: '{word}'，必须严格使用中文（如 male->男, foot->足部）"

    return ""  # 验证通过


def _clean_llm_json_response(text: str) -> str:
    """清洗 LLM 返回的 Markdown 格式包裹的 JSON (保留原有设计)"""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_clinical_data(clinical_json_str: str = None, clinical_text: str = None) -> dict:
    """
    双通道病历解析 (对齐 PAD-UFES-20，含强制中文映射与 LLM 自重试机制)
    """
    # 通道 1：结构化 JSON 直接映射 (通常来自前端表单或数据集 CSV 行)
    if clinical_json_str:
        try:
            data = json.loads(clinical_json_str) if isinstance(clinical_json_str, str) else clinical_json_str
            # 极重要：必须深拷贝，防止多请求修改污染全局 Schema
            mapped_data = copy.deepcopy(EMPTY_CLINICAL_SCHEMA)

            pi = data.get("patient_info", {})
            mapped_data["patient_info"]["age"] = pi.get("age")
            mapped_data["patient_info"]["gender"] = _map_gender(pi.get("gender"))
            mapped_data["patient_info"]["fitzpatrick_skin_type"] = pi.get("fitzpatrick_skin_type")

            lh = data.get("lifestyle_history", {})
            mapped_data["lifestyle_history"]["smoke"] = _is_truthy(lh.get("smoke"))
            mapped_data["lifestyle_history"]["drink"] = _is_truthy(lh.get("drink"))
            mapped_data["lifestyle_history"]["pesticide_exposure"] = _is_truthy(lh.get("pesticide_exposure"))

            fh = data.get("family_history", {})
            mapped_data["family_history"]["background_father"] = fh.get("background_father")
            mapped_data["family_history"]["background_mother"] = fh.get("background_mother")

            ph = data.get("personal_history", {})
            mapped_data["personal_history"]["skin_cancer_history"] = _is_truthy(ph.get("skin_cancer_history"))
            mapped_data["personal_history"]["other_cancer_history"] = _is_truthy(ph.get("other_cancer_history"))

            lc = data.get("lesion_clinical", {})
            # 部位强制中文转换 + 语义清洗
            mapped_data["lesion_clinical"]["region"] = _map_region(lc.get("region"))
            mapped_data["lesion_clinical"]["diameter_1_mm"] = lc.get("diameter_1_mm") or lc.get("diameter_1")
            mapped_data["lesion_clinical"]["diameter_2_mm"] = lc.get("diameter_2_mm") or lc.get("diameter_2")
            mapped_data["lesion_clinical"]["elevation"] = _is_truthy(lc.get("elevation"))
            mapped_data["lesion_clinical"]["biopsed"] = _is_truthy(lc.get("biopsed"))

            ls = data.get("lesion_symptoms", {})
            mapped_data["lesion_symptoms"]["itch"] = _is_truthy(ls.get("itch"))
            mapped_data["lesion_symptoms"]["hurt"] = _is_truthy(ls.get("hurt"))
            mapped_data["lesion_symptoms"]["changed"] = _is_truthy(ls.get("changed"))
            mapped_data["lesion_symptoms"]["bleed"] = _is_truthy(ls.get("bleed"))
            mapped_data["lesion_symptoms"]["grew"] = _is_truthy(ls.get("grew"))

            logger.info("Successfully parsed and mapped structured clinical_json.")
            return mapped_data
        except Exception as e:
            logger.error(f"Failed to parse clinical_json: {e}. Falling back to empty schema.")
            return copy.deepcopy(EMPTY_CLINICAL_SCHEMA)

    # 通道 2：自由文本 LLM 提取 (保留带反馈的自重试机制)
    if clinical_text:
        client = OpenAI(
            api_key=settings.INTEGRATION_API_KEY,
            base_url=settings.INTEGRATION_BASE_URL
        )

        base_prompt = f"""
你是一个严谨的皮肤病专科病历结构化提取助手。请从医生输入的自由文本中提取关键临床特征，并严格按照提供的 JSON Schema 输出。
如果文本中未提及某字段，请将该字段设为 null。严禁输出任何诊断结论，只提取客观描述。

严格遵循以下规则：
1. 必须以纯JSON格式输出，不要有任何其他文字说明。
2. JSON必须包含以下顶层键：patient_info, lifestyle_history, family_history, personal_history, lesion_clinical, lesion_symptoms。
3. 绝对禁止输出任何诊断性结论（如：提示黑色素瘤、疑似恶性等），只描述你看到的客观形态和病史。
4. 【极其重要】所有提取的值必须严格使用纯中文！
   - 性别必须输出“男”或“女”，严禁输出 male/female/M/F。
   - 解剖部位必须输出中文，如“足底”、“头皮”、“腹部”，严禁输出 foot/scalp/abdomen。
   - 布尔值请严格使用 JSON 原生格式 true 或 false (小写且无引号)，严禁输出 "是"/"否"/"yes"/"no" 等字符串。
违反上述任一规则将导致系统崩溃，请务必遵守！

输出 Schema 格式如下：
{json.dumps(EMPTY_CLINICAL_SCHEMA, ensure_ascii=False)}

待提取的自由文本：
{clinical_text}
"""

        feedback_msg = ""  # 初始化反馈信息

        for attempt in range(MAX_LLM_RETRIES):
            try:
                # 拼接反馈信息到 Prompt (原有优秀设计)
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

                # ===== 核心校验与清洗逻辑 =====
                validation_error = _validate_clinical_data(parsed_data)
                if not validation_error:
                    # 🚨 校验通过后，必须对 LLM 输出的部位进行一次后置清洗，确保触发词对齐
                    if parsed_data.get("lesion_clinical", {}).get("region"):
                        raw_region = parsed_data["lesion_clinical"]["region"]
                        parsed_data["lesion_clinical"]["region"] = _normalize_region_for_triggers(raw_region)

                    logger.info(f"Successfully extracted clinical_text using LLM (Attempt {attempt + 1}).")
                    return parsed_data
                else:
                    # 校验失败，准备重试
                    feedback_msg = validation_error
                    logger.warning(f"Validation failed (Attempt {attempt + 1}): {validation_error}. Retrying...")

            except Exception as e:
                logger.error(f"LLM clinical extraction API error (Attempt {attempt + 1}): {e}")
                feedback_msg = f"API调用或解析异常: {str(e)}"

        # 如果达到最大重试次数仍然失败，降级兜底 (原有优秀设计)
        logger.error(f"Max retries ({MAX_LLM_RETRIES}) reached. Falling back to EMPTY schema.")
        return copy.deepcopy(EMPTY_CLINICAL_SCHEMA)

    # 什么数据都没传，返回深拷贝的空 Schema
    return copy.deepcopy(EMPTY_CLINICAL_SCHEMA)