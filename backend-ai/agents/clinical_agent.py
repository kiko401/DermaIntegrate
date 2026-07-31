import json
import logging
import re
import copy
from pathlib import Path
from openai import OpenAI
from config import settings
from shared.config import LLM_READ_TIMEOUT

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 2

# 对齐 PAD-UFES-20 数据集的临床数据结构
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

# 性别标准化映射
GENDER_MAP = {"male": "男", "female": "女", "m": "男", "f": "女"}

# 部位英文->中文映射
REGION_MAP = {
    "ABDOMEN": "腹部", "BACK": "背部", "CHEST": "胸部", "FACE": "面部",
    "FOOT": "足部", "FOREARM": "前臂", "HAND": "手部", "LATERAL CHEST": "侧胸",
    "LOWER LIMB": "下肢", "NECK": "颈部", "NOSE": "鼻部", "SCALP": "头皮",
    "THIGH": "大腿", "UPPER LIMB": "上肢", "EAR": "耳部", "LIP": "唇部",
    "ORAL": "口腔", "NASAL": "鼻腔", "GENITAL": "生殖器",
    "SOLE": "足底", "PALM": "手掌", "HEEL": "足跟",
    "FINGER": "手指", "TOE": "足趾", "NAIL": "甲床", "THUMB": "拇指",
    "BIG TOE": "拇趾", "GREAT TOE": "拇趾"
}

# 英文词汇校验黑名单（测试发现LLM偶尔会输出英文，导致下游Agent匹配失败）
ENGLISH_BLACKLIST = [
    "male", "female",
    "left", "right", "sole", "palm", "scalp", "face", "abdomen", "back", "foot", "hand",
    "yes", "no", "neck", "ear", "chest", "arm", "leg"
]

# 口语化部位名称清洗表（如"左脚底" -> "左足底"，确保能命中病理Agent触发词）
REGION_NORMALIZATION_MAP = {
    "脚": "足", "脚底": "足底", "脚跟": "足跟", "脚趾": "足趾", "脚背": "足背",
    "大拇趾": "拇趾", "大脚趾": "拇趾",
    "手掌心": "手掌", "手心": "手掌", "手指头": "手指", "大拇指": "拇指",
    "鼻翼": "鼻部", "鼻侧": "鼻部", "鼻腔内": "鼻腔",
    "口腔内": "口腔", "嘴唇": "唇部", "下唇": "唇部", "上唇": "唇部",
}


def _is_truthy(value) -> bool:
    """将各种输入转换为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "有", "是", "yes"]
    return False


def _map_gender(raw_gender) -> str:
    """性别映射为中文。"""
    if not raw_gender:
        return None
    val = str(raw_gender).lower().strip()
    return GENDER_MAP.get(val, raw_gender)


def _normalize_region_for_triggers(region_str: str) -> str:
    """将口语化部位名称清洗为规范中文，命中下游病理Agent触发词。"""
    if not region_str:
        return None
    for old, new in REGION_NORMALIZATION_MAP.items():
        region_str = region_str.replace(old, new)
    return region_str


def _map_region(raw_region) -> str:
    """部位映射：先查静态表，未命中再做语义清洗。"""
    if not raw_region:
        return None
    val = str(raw_region).upper().strip()
    mapped = REGION_MAP.get(val, raw_region)
    if mapped == raw_region:
        mapped = _normalize_region_for_triggers(mapped)
    return mapped


def _validate_clinical_data(data: dict) -> str:
    """校验LLM输出的临床数据质量。"""
    if not isinstance(data, dict):
        return "输出不是有效的 JSON 字典"
    required_keys = [
        "patient_info", "lifestyle_history", "family_history",
        "personal_history", "lesion_clinical", "lesion_symptoms"
    ]
    for key in required_keys:
        if key not in data:
            return f"缺少必须的顶层键: {key}"

    # 英文词汇检查，防止中英混杂导致下游失败
    json_str = json.dumps(data, ensure_ascii=False).lower()
    for word in ENGLISH_BLACKLIST:
        if f'"{word}"' in json_str or f": {word}" in json_str or f": \"{word}" in json_str:
            return f"检测到非法英文输出: '{word}'，必须使用中文（如 male->男, foot->足部）"

    return ""


def _clean_llm_json_response(text: str) -> str:
    """剥离 Markdown 代码块标记。"""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_clinical_data(clinical_json_str: str = None, clinical_text: str = None) -> dict:
    """
    临床数据解析入口，支持两种输入方式：
    1. 结构化 JSON 解析（前端表单或数据库导入）
    2. 自由文本 LLM 提取（医生自然语言输入）

    优先级：JSON 解析结果为基础，clinical_text 补充 JSON 中为 null 的字段。
    包含校验-反馈-重试机制，防止LLM语义漂移导致输出不合规。
    """
    # 通道1：结构化JSON解析（作为基础结果）
    mapped_data = copy.deepcopy(EMPTY_CLINICAL_SCHEMA)
    if clinical_json_str:
        try:
            data = json.loads(clinical_json_str) if isinstance(clinical_json_str, str) else clinical_json_str

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
        except Exception as e:
            logger.error(f"Failed to parse clinical_json: {e}. Using empty schema as base.")

    # 通道2：自由文本LLM提取，补充 JSON 中为 null 的字段
    if not clinical_text:
        return mapped_data

    client = OpenAI(
        api_key=settings.INTEGRATION_API_KEY,
        base_url=settings.INTEGRATION_BASE_URL
    )

    _prompt_tpl = (
        Path(__file__).parent.parent / "prompts" / "clinical_parse.txt"
    ).read_text(encoding="utf-8")

    # 把已解析的 JSON 中非 null 的值注入 prompt，减少 LLM 幻觉
    known_info = _build_known_context(mapped_data)
    base_prompt = _prompt_tpl.format(
        SCHEMA=json.dumps(EMPTY_CLINICAL_SCHEMA, ensure_ascii=False),
        CLINICAL_TEXT=clinical_text
    )
    if known_info:
        base_prompt += f"\n\n【已知信息（来自结构化JSON，提取时保持这些值不变）】：\n{known_info}"

    feedback_msg = ""

    for attempt in range(MAX_LLM_RETRIES):
        try:
            current_prompt = base_prompt
            if feedback_msg:
                current_prompt += f"\n\n【重要纠正】：你上一次的输出违反了规则，错误原因为：'{feedback_msg}'。请务必修正并重新输出！"

            response = client.chat.completions.create(
                model=settings.INTEGRATION_MODEL,
                messages=[{"role": "user", "content": current_prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=LLM_READ_TIMEOUT
            )

            result_str = response.choices[0].message.content
            cleaned_str = _clean_llm_json_response(result_str)
            parsed_data = json.loads(cleaned_str)

            validation_error = _validate_clinical_data(parsed_data)
            if not validation_error:
                # 用 LLM 结果补充 mapped_data 中为 null 的字段
                _merge_clinical_data(mapped_data, parsed_data)
                if mapped_data["lesion_clinical"]["region"]:
                    raw_region = mapped_data["lesion_clinical"]["region"]
                    mapped_data["lesion_clinical"]["region"] = _normalize_region_for_triggers(raw_region)
                logger.info(f"Successfully extracted and merged clinical_text using LLM (Attempt {attempt + 1}).")
                return mapped_data
            else:
                feedback_msg = validation_error
                logger.warning(f"Validation failed (Attempt {attempt + 1}): {validation_error}. Retrying...")

        except Exception as e:
            logger.error(f"LLM clinical extraction API error (Attempt {attempt + 1}): {e}")
            feedback_msg = f"API调用或解析异常: {str(e)}"

    logger.error(f"Max retries ({MAX_LLM_RETRIES}) reached. Falling back to JSON base.")
    return mapped_data


def _build_known_context(mapped_data: dict) -> str:
    """构建已知信息描述，供 LLM 感知已解析的字段，避免重复填充或覆盖。"""
    parts = []
    pi = mapped_data.get("patient_info", {})
    if pi.get("age") is not None:
        parts.append(f"- 患者年龄：{pi['age']}岁")
    if pi.get("gender") is not None:
        parts.append(f"- 患者性别：{pi['gender']}")
    lc = mapped_data.get("lesion_clinical", {})
    if lc.get("region") is not None:
        parts.append(f"- 病灶部位：{lc['region']}")
    if lc.get("diameter_1_mm") is not None:
        parts.append(f"- 病灶直径1：{lc['diameter_1_mm']}mm")
    if lc.get("diameter_2_mm") is not None:
        parts.append(f"- 病灶直径2：{lc['diameter_2_mm']}mm")
    if lc.get("elevation") is not None:
        parts.append(f"- 病灶隆起：{'是' if lc['elevation'] else '否'}")
    ls = mapped_data.get("lesion_symptoms", {})
    for k, v in ls.items():
        if v is not None and v is not False:
            parts.append(f"- 症状{k}：{'有' if v else '否'}")
    return "\n".join(parts) if parts else ""


def _merge_clinical_data(base: dict, overlay: dict) -> None:
    """将 overlay 中非 null 的字段合并到 base（原地修改）。"""
    for top_key in base:
        if top_key not in overlay:
            continue
        for sub_key in base[top_key]:
            overlay_val = overlay[top_key].get(sub_key)
            if overlay_val is not None and overlay_val != "":
                # 性别标准化
                if top_key == "patient_info" and sub_key == "gender":
                    base[top_key][sub_key] = _map_gender(overlay_val)
                # 部位标准化
                elif top_key == "lesion_clinical" and sub_key == "region":
                    base[top_key][sub_key] = _map_region(overlay_val)
                # 布尔值标准化
                elif sub_key in ("smoke", "drink", "pesticide_exposure",
                                 "skin_cancer_history", "other_cancer_history",
                                 "elevation", "biopsied",
                                 "itch", "hurt", "changed", "bleed", "grew"):
                    base[top_key][sub_key] = _is_truthy(overlay_val)
                else:
                    base[top_key][sub_key] = overlay_val
