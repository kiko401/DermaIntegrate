import logging
import re

logger = logging.getLogger(__name__)

# ==========================================================
# 1. 对齐 TCGA-SKCM / AJCC 8th 的标准输入 Schema (v3.1 契约)
# ==========================================================
EMPTY_PATHOLOGY_SCHEMA = {
    "breslow_thickness_mm": None,
    "ulceration": None,
    "clark_level": None,
    "margin_status_mm": None,
    "lymph_node_status": None,
    "braf_mutation": None,
    "nras_mutation": None,
    "ldh_level": None
}


# ==========================================================
# 2. 输入拦截映射与防御性提取 (保留优秀设计)
# ==========================================================
def _is_truthy(value) -> bool:
    """防御性布尔值判定"""
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value > 0
    if isinstance(value, str): return value.strip().lower() in ["true", "1", "有", "是", "yes", "阳性"]
    return False


def _extract_float(value) -> float:
    """防御性浮点数提取，兼容带单位字符串"""
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, str):
        match = re.search(r'\d+\.?\d*', value)
        if match: return float(match.group())
    raise ValueError(f"无法从 '{value}' 中提取数值")


def _map_mutation_status(value) -> str:
    """基因突变状态强制中文映射"""
    if not value: return None
    val = str(value).strip().lower()
    if val in ["mutant", "突变", "突变型", "阳性", "positive", "1"]: return "突变型"
    if val in ["wildtype", "野生", "野生型", "阴性", "negative", "0"]: return "野生型"
    return str(value)  # 兜底


def _map_lymph_node(value) -> str:
    """淋巴结状态强制中文映射"""
    if not value: return None
    val = str(value).strip().lower()
    if val in ["阳性", "positive", "有转移", "转移", "1"]: return "阳性"
    if val in ["阴性", "negative", "无转移", "未转移", "0"]: return "阴性"
    return str(value)


# ==========================================================
# 3. 规则引擎详实逻辑 (AJCC 8th T分期 + NCCN 治疗)
# ==========================================================
def evaluate_pathology_data(pathology_json: dict = None, location_from_clinical: str = None) -> dict:
    """
    基于指南的病理与分子数据规则引擎
    :param pathology_json: 病理数据字典
    :param location_from_clinical: 从病历 Agent 获取的病灶位置 (跨模态依赖)
    :return: 结构化分期与建议
    """
    # 默认兜底返回
    default_result = {
        "t_stage": "未提供",
        "treatment_recommendations": [],
        "missing_data_warnings": ["缺乏病理金标准，强烈建议行皮肤活检明确诊断"]
    }

    if not pathology_json:
        return default_result

    result = {
        "t_stage": "无法分期",
        "treatment_recommendations": [],
        "missing_data_warnings": []
    }

    # ---- 数据清洗与拦截 ----
    breslow_raw = pathology_json.get("breslow_thickness_mm")
    ulceration_raw = pathology_json.get("ulceration")
    lymph_node = _map_lymph_node(pathology_json.get("lymph_node_status"))
    braf = _map_mutation_status(pathology_json.get("braf_mutation"))
    nras = _map_mutation_status(pathology_json.get("nras_mutation"))
    ldh_elevated = _is_truthy(pathology_json.get("ldh_level"))

    # ---- 核心：AJCC 8th T 分期逻辑 ----
    # 判空原则：若 Breslow 为空，整个 T 分期逻辑阻断
    if breslow_raw is not None:
        try:
            breslow_val = _extract_float(breslow_raw)
            # 临床保守原则：ulceration 如果未提供(None)，按可能伴有溃疡的高危倾向处理(归为b期)
            has_ulceration = _is_truthy(ulceration_raw) if ulceration_raw is not None else True

            if breslow_val <= 1.0:
                result["t_stage"] = "T1a" if not has_ulceration else "T1b"
            elif breslow_val <= 2.0:
                result["t_stage"] = "T2a" if not has_ulceration else "T2b"
            elif breslow_val <= 4.0:
                result["t_stage"] = "T3a" if not has_ulceration else "T3b"
            else:
                result["t_stage"] = "T4a" if not has_ulceration else "T4b"

        except (ValueError, TypeError):
            result["missing_data_warnings"].append(f"Breslow厚度格式错误({breslow_raw})，无法进行准确分期")
    else:
        # 缺失 Breslow 的核心兜底逻辑
        result["missing_data_warnings"].append(
            "缺乏病理浸润深度(Breslow)，无法进行准确分期，强烈建议优先行皮肤活检明确浸润深度")

    # ---- NCCN 治疗建议规则 ----
    # 1. SLNB (前哨淋巴结活检) 规则
    # 提取分期数字，判断是否 T1b 及以上
    t_stage_str = result["t_stage"]
    if t_stage_str not in ["未提供", "无法分期"]:
        try:
            t_num = int(re.search(r'T(\d)', t_stage_str).group(1))
            t_suffix = t_stage_str[-1]  # a or b
            # T1b 及以上，或者 T2a 及以上，均推荐 SLNB (简化规则：只要有b或者T2以上)
            if (t_num == 1 and t_suffix == 'b') or t_num >= 2:
                if lymph_node is None:
                    result["treatment_recommendations"].append(
                        f"目前分期为{t_stage_str}，强烈建议行前哨淋巴结活检(SLNB)明确淋巴结状态")
                elif lymph_node == "阳性":
                    result["t_stage"] += " N1(淋巴结阳性)"  # 附加 N 分期提示
                    result["treatment_recommendations"].append("确认淋巴结转移，建议行淋巴结清扫及后续系统治疗评估")
        except:
            pass

    # 2. 分子靶向规则
    if braf == "突变型":
        result["treatment_recommendations"].append("BRAF V600突变阳性，推荐靶向治疗方案(达拉非尼+曲美替尼)")

    if nras == "突变型":
        result["treatment_recommendations"].append("NRAS突变阳性，提示可能对特定免疫治疗敏感，建议专科会诊")

    # 3. LDH 远处转移评估
    if ldh_elevated:
        result["t_stage"] = "IV期 (M1)"  # 只要 LDH 高，直接归入晚期考虑
        result["treatment_recommendations"].append("LDH升高提示可能存在远处转移，建议行PET-CT或CT全身评估")

    # ---- 缺失兜底与晚期提示 ----
    if braf is None and t_stage_str in ["T3a", "T3b", "T4a", "T4b"]:
        result["missing_data_warnings"].append("晚期患者建议完善BRAF/NRAS基因检测以指导靶向治疗")

    # ---- 跨模态依赖逻辑：肢端型附加建议 (保留) ----
    if location_from_clinical and isinstance(location_from_clinical, str):
        acral_keywords = ["足底", "手掌", "甲下", "足", "手", "趾", "指"]
        if any(keyword in location_from_clinical for keyword in acral_keywords):
            result["treatment_recommendations"].append(
                "肢端型黑色素瘤侵袭性可能更强，建议密切随访及考虑基因检测(如KIT突变)")
            # 如果没有分期，给一个基本的风险提示
            if result["t_stage"] == "无法分期":
                result["missing_data_warnings"].append("肢端病灶缺乏病理深度，建议优先活检")

    # 如果没有任何建议和警告，给出常规随访提示
    if not result["treatment_recommendations"] and not result["missing_data_warnings"]:
        result["treatment_recommendations"].append("目前病理指标相对局限，建议定期随访观察")

    return result