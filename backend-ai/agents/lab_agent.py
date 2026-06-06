import logging
import re

logger = logging.getLogger(__name__)


def _is_truthy(value) -> bool:
    """
    防御性布尔值判定。
    兼容 LLM 提取或前端传入的各种 True 变体：True, "true", "True", 1, "1", "有", "是"
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "有", "是", "yes", "阳性"]
    return False


def _extract_float(value) -> float:
    """
    防御性浮点数提取。
    兼容 LLM 提取带单位或不规范的数据：2.5, "2.5", "2.5mm", "2.5 mm"
    如果无法提取则抛出 ValueError
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # 使用正则提取第一个出现的数字（含小数点）
        match = re.search(r'\d+\.?\d*', value)
        if match:
            return float(match.group())
    raise ValueError(f"Cannot extract float from: {value}")


def evaluate_lab_data(lab_json: dict = None, location_from_clinical: str = None) -> dict:
    """
    基于指南的化验数据规则引擎
    :param lab_json: 化验数据字典
    :param location_from_clinical: 从病历 Agent 获取的病灶位置 (跨模态依赖)
    :return: 结构化风险分层与建议
    """
    default_result = {
        "stage": "未知",
        "risk": "无法评估",
        "actions": ["缺乏化验数据，建议完善病理及血液学检查"]
    }

    if not lab_json:
        return default_result

    result = {
        "stage": "未知",
        "risk": "无法评估",
        "actions": []
    }

    breslow = lab_json.get("breslow_thickness")
    ulceration = lab_json.get("ulceration")
    ldh = lab_json.get("ldh_elevated")

    # 核心分期逻辑 (极重要排障：必须判空且防类型错误)
    if breslow is not None:
        try:
            breslow_val = _extract_float(breslow)  # 使用健壮的提取函数
            if breslow_val <= 1.0:
                result["stage"] = "T1"
                result["risk"] = "低危"
            elif breslow_val <= 2.0:
                result["stage"] = "T2"
                result["risk"] = "中危"
            elif breslow_val <= 4.0:
                result["stage"] = "T3"
                result["risk"] = "高危"
            else:
                result["stage"] = "T4"
                result["risk"] = "极高危"
        except (ValueError, TypeError):
            result["actions"].append(f"Breslow厚度格式错误({breslow})，无法分期")
    else:
        # 缺失 Breslow 的核心兜底逻辑
        result["actions"].append("缺乏病理浸润深度，建议优先行皮肤活检明确Breslow厚度")

    # 溃疡状态逻辑 (使用健壮的布尔判定)
    if _is_truthy(ulceration):
        result["actions"].append("存在溃疡，T分期需升级，建议完善前哨淋巴结活检(SLNB)评估")
        # 如果有分期，将风险提升一级 (简单示例)
        if result["risk"] == "低危":
            result["risk"] = "中危"
        elif result["risk"] == "中危":
            result["risk"] = "高危"
        elif result["risk"] == "无法评估":
            result["risk"] = "中高危"

    # LDH 逻辑 (使用健壮的布尔判定)
    if _is_truthy(ldh):
        result["stage"] = "M1"  # 只要 LDH 高，直接归入晚期考虑
        result["risk"] = "极高危"
        result["actions"].append("LDH升高提示可能存在远处转移，建议行PET-CT或CT全身评估")

    # 跨模态依赖逻辑：肢端型附加建议 (改为模糊匹配)
    # 防止 LLM 提取 "左足底"、"足跖部"、"左手食指" 等变体导致漏判
    if location_from_clinical and isinstance(location_from_clinical, str):
        acral_keywords = ["足底", "手掌", "甲下", "足", "手", "趾", "指"]
        # 只要位置字符串中包含任意一个肢端关键词，即触发规则
        if any(keyword in location_from_clinical for keyword in acral_keywords):
            result["actions"].append("肢端型黑色素瘤侵袭性可能更强，建议密切随访及考虑基因检测(如KIT突变)")
            # 确保至少有风险评定
            if result["risk"] == "无法评估" or result["risk"] == "低危":
                result["risk"] = "中高危"

    # 如果没有触发任何 action，给个默认提示
    if not result["actions"] and result["stage"] != "未知":
        result["actions"].append("目前病理指标相对局限，建议定期随访观察")

    return result