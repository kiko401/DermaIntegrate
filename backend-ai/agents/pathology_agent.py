import logging
import re

logger = logging.getLogger(__name__)

# ==========================================================
# 1. 核心架构：疾病注册表 (纯中文面向LLM，英文Code仅内部使用)
# 新增病种只需在此处添加配置，无需修改任何核心逻辑！
# ==========================================================
DISEASE_REGISTRY = {
    "MEL": {
        "name": "黑色素瘤",
        "keywords": ["黑色素瘤", "恶黑", "恶性黑色素瘤"],
        "is_malignant": True,
        "needs_staging": True,
        "rag_template": "{subtype}黑色素瘤，病灶位于{region}，病理分期为{stage}的诊疗指南"
    },
    "BCC": {
        "name": "基底细胞癌",
        "keywords": ["基底细胞癌", "基底细胞瘤", "bcc"],
        "is_malignant": True,
        "needs_staging": False,
        "rag_template": "基底细胞癌，病灶位于{region}的诊疗指南"
    },
    "SCC": {
        "name": "鳞状细胞癌",
        "keywords": ["鳞状细胞癌", "鳞癌", "scc"],
        "is_malignant": True,
        "needs_staging": False,
        "rag_template": "鳞状细胞癌，病灶位于{region}的诊疗指南"
    },
    "NEV": {
        "name": "色素痣",
        "keywords": ["痣", "色素痣", "皮内痣", "交界痣", "混合痣", "蓝痣", "梭形细胞痣"],
        "is_malignant": False,
        "needs_staging": False,
        "rag_template": "色素痣，病灶位于{region}的诊疗指南"
    },
    "ACK": {
        "name": "日光性角化病",
        "keywords": ["日光性角化", "日光性角化病"],
        "is_malignant": False,  # 癌前病变
        "needs_staging": False,
        "rag_template": "日光性角化病，病灶位于{region}的诊疗指南"
    },
    "SEK": {
        "name": "脂溢性角化病",
        "keywords": ["脂溢性角化", "老年斑", "脂溢性角化病"],
        "is_malignant": False,
        "needs_staging": False,
        "rag_template": "脂溢性角化病，病灶位于{region}的诊疗指南"
    }
}


# ==========================================================
# 2. 辅助函数
# ==========================================================
def _is_truthy(value) -> bool:
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value > 0
    if isinstance(value, str): return value.strip().lower() in ["true", "1", "有", "是", "yes", "阳性"]
    return False


def _extract_float(value) -> float:
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, str):
        match = re.search(r'\d+\.?\d*', value)
        if match: return float(match.group())
    raise ValueError(f"无法从 '{value}' 中提取数值")


def _map_mutation_status(value) -> str:
    if not value: return None
    val = str(value).strip().lower()
    if val in ["mutant", "突变", "突变型", "阳性", "positive", "1"]: return "突变型"
    if val in ["wildtype", "野生", "野生型", "阴性", "negative", "0"]: return "野生型"
    return str(value)


def _map_lymph_node(value) -> str:
    if not value: return None
    val = str(value).strip().lower()
    if val in ["阳性", "positive", "有转移", "转移", "1"]: return "阳性"
    if val in ["阴性", "negative", "无转移", "未转移", "0"]: return "阴性"
    return str(value)


# ==========================================================
# 3. 规则引擎：基于注册表的动态分诊与分期
# ==========================================================
def evaluate_pathology_data(pathology_json: dict = None, location_from_clinical: str = None) -> dict:
    """
    基于 v4.0 契约：配置驱动的疾病分诊，全中文输出
    """
    default_result = {
        "disease_type": "MEL",
        "t_stage": "未提供",
        "treatment_recommendations": [],
        "missing_data_warnings": ["缺乏病理金标准，强烈建议行皮肤活检明确诊断"]
    }

    if not pathology_json:
        return default_result

    result = {
        "disease_type": "MEL",
        "t_stage": "无法分期",
        "treatment_recommendations": [],
        "missing_data_warnings": []
    }

    # ---- 第一步：基于注册表的动态分诊 ----
    pathology_diag = str(pathology_json.get("pathology_diagnosis", "") or "").lower()
    matched_disease = None

    for code, config in DISEASE_REGISTRY.items():
        if any(keyword in pathology_diag for keyword in config["keywords"]):
            matched_disease = {"code": code, **config}
            break

    # 如果匹配到非MEL病种，直接走专属分支
    if matched_disease and matched_disease["code"] != "MEL":
        result["disease_type"] = matched_disease["code"]
        result["t_stage"] = "无需分期" if not matched_disease["needs_staging"] else "非黑色素瘤分期"

        malignancy_hint = "恶性肿瘤" if matched_disease["is_malignant"] else "良性或癌前病变"
        result["treatment_recommendations"].append(
            f"病理已明确提示为【{matched_disease['name']}】({malignancy_hint})，请按照该疾病临床诊疗规范处理，无需按黑色素瘤分期"
        )
        return result

    # ---- 第二步：黑色素瘤临床路径 ----
    breslow_raw = pathology_json.get("breslow_thickness_mm")
    ulceration_raw = pathology_json.get("ulceration")
    lymph_node = _map_lymph_node(pathology_json.get("lymph_node_status"))
    braf = _map_mutation_status(pathology_json.get("braf_mutation"))
    nras = _map_mutation_status(pathology_json.get("nras_mutation"))
    ldh_elevated = _is_truthy(pathology_json.get("ldh_level"))

    if breslow_raw is not None:
        try:
            breslow_val = _extract_float(breslow_raw)
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
        result["missing_data_warnings"].append("缺乏病理浸润深度，无法进行准确分期，强烈建议优先行皮肤活检明确浸润深度")

    t_stage_str = result["t_stage"]
    if t_stage_str not in ["未提供", "无法分期"]:
        try:
            t_num = int(re.search(r'T(\d)', t_stage_str).group(1))
            t_suffix = t_stage_str[-1]
            if (t_num == 1 and t_suffix == 'b') or t_num >= 2:
                if lymph_node is None:
                    result["treatment_recommendations"].append(
                        f"目前分期为{t_stage_str}，强烈建议行前哨淋巴结活检明确淋巴结状态")
                elif lymph_node == "阳性":
                    result["t_stage"] += " N1(淋巴结阳性)"
                    result["treatment_recommendations"].append("确认淋巴结转移，建议行淋巴结清扫及后续系统治疗评估")
        except:
            pass

    if braf == "突变型":
        result["treatment_recommendations"].append("BRAF V600突变阳性，推荐靶向治疗方案（达拉非尼联合曲美替尼）")
    if nras == "突变型":
        result["treatment_recommendations"].append("NRAS突变阳性，提示可能对特定免疫治疗敏感，建议专科会诊")
    if ldh_elevated:
        result["t_stage"] = "IV期 (M1)"
        result["treatment_recommendations"].append("乳酸脱氢酶升高提示可能存在远处转移，建议行PET-CT或CT全身评估")

    if braf is None and nras is None and t_stage_str in ["T3a", "T3b", "T4a", "T4b"]:
        result["missing_data_warnings"].append("晚期患者建议完善BRAF/NRAS基因检测以指导靶向治疗")

    # 跨模态依赖逻辑
    if location_from_clinical and isinstance(location_from_clinical, str):
        acral_keywords = ["足底", "手掌", "甲下", "足", "手", "趾", "指"]
        if any(keyword in location_from_clinical for keyword in acral_keywords):
            result["treatment_recommendations"].append(
                "肢端型黑色素瘤侵袭性可能更强，建议密切随访及考虑基因检测(如KIT突变)")
            if result["t_stage"] == "无法分期": result["missing_data_warnings"].append(
                "肢端病灶缺乏病理深度，建议优先活检")

        mucosal_keywords = ["口", "鼻", "唇", "生殖", "黏膜", "粘膜", "肛"]
        if any(keyword in location_from_clinical for keyword in mucosal_keywords):
            result["treatment_recommendations"].append(
                "黏膜型黑色素瘤侵袭性强，预后较差，强烈建议完善KIT等基因检测指导靶向治疗")
            if result["t_stage"] == "无法分期": result["missing_data_warnings"].append(
                "黏膜病灶预后极差，强烈建议优先活检明确病理")

    if not result["treatment_recommendations"] and not result["missing_data_warnings"]:
        result["treatment_recommendations"].append("目前病理指标相对局限，建议定期随访观察")

    return result