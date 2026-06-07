import json
import logging
from openai import OpenAI
import json_repair
from config import settings

logger = logging.getLogger(__name__)

def _build_dynamic_prompt(image_result: dict, clinical_result: dict, pathology_result: dict) -> str:
    """
    根据输入数据的存在与否动态拼接 Prompt。
    严格对齐 v3.2 综合研判锚定契约。
    """
    evidence_parts = []

    # 1. 视觉证据
    if image_result and image_result.get("morphology"):
        morph = image_result["morphology"]
        location = image_result.get("location", "未知")
        coverage = image_result.get("coverage", 0)
        evidence_parts.append(
            f"【视觉证据】：皮肤镜形态学特征提取如下：{json.dumps(morph, ensure_ascii=False)}。病灶位于图像{location}，占比约{coverage * 100:.1f}%。")
    else:
        evidence_parts.append("【视觉证据】：未提供影像信息，请在建议中优先考虑完善皮肤镜或皮损局部拍照检查。")

    # 2. 病历特征
    if clinical_result:
        filtered_clinical = {}
        for k, v in clinical_result.items():
            if isinstance(v, dict) and any(sv is not None for sv in v.values()):
                filtered_clinical[k] = v

        if filtered_clinical:
            evidence_parts.append(f"【临床特征】：结构化病历解析如下：{json.dumps(filtered_clinical, ensure_ascii=False)}")
        else:
            evidence_parts.append("【临床特征】：未提供有效临床体征与病史，请在建议中优先考虑详细询问病史及查体。")
    else:
        evidence_parts.append("【临床特征】：未提供临床信息，请在建议中优先考虑详细询问病史及查体。")

    # 3. 病理与分子规则
    if pathology_result:
        t_stage = pathology_result.get("t_stage", "未提供")
        treatments = pathology_result.get("treatment_recommendations", [])
        warnings = pathology_result.get("missing_data_warnings", [])

        path_str = f"基于AJCC指南的病理分期判定为：'{t_stage}'。"
        if treatments:
            path_str += f"触发的指南建议为：{json.dumps(treatments, ensure_ascii=False)}。"
        if warnings:
            path_str += f"病理数据缺失警告：{json.dumps(warnings, ensure_ascii=False)}。"

        evidence_parts.append(f"【病理与分子规则】：{path_str}")
    else:
        evidence_parts.append(
            "【病理与分子规则】：未提供病理活检信息，缺乏金标准，必须在建议中强烈建议行皮肤活检明确病理诊断。")

    prompt = (
            "你是一个严谨的皮肤病专科辅助诊断AI助手。你的任务是根据提供的多模态证据，综合分析并输出结构化的辅助诊断报告。\n\n"
            "【核心约束】：\n"
            "1. 严禁输出终局诊断结论（如“确诊为黑色素瘤”），你只能提供风险分层和鉴别诊断建议。\n"
            "2. 综合研判原则：如果【病理与分子规则】中已给出明确的T分期或病理诊断结论，必须以此作为风险分层和建议的核心依据。对于视觉或临床特征的缺失，请客观提示“建议完善相关检查”，但不应因此否定或降级已有的病理分期结论，避免过度保守导致延误病情。\n"
            "3. 必须以严格的 JSON 格式输出，包含以下键：risk_level, key_concerns, recommendations, differential, disclaimer, status。\n"
            "4. 【终极全中文约束】你的输出必须 100% 使用专业且规范的中文！严禁在任何字段中夹杂英文（如不得输出 melanoma、BRAF、SLNB，必须替换为 黑色素瘤、BRAF基因、前哨淋巴结活检）。所有的建议必须以中文医学规范表述。\n\n"
            "【输入证据】：\n" + "\n".join(evidence_parts) + "\n\n"
            "【输出格式要求】：\n"
            "{\n"
            '  "risk_level": "极高危/高危/中高危/中危/低危/数据不足无法评估",\n'
            '  "key_concerns": [{"item": "关注要点1", "source_id": "[参考编号1]"}, {"item": "关注要点2", "source_id": "[参考编号2]"}],\n'
            '  "recommendations": [{"item": "建议检查1", "source_id": "[参考编号3]"}, {"item": "建议检查2", "source_id": "R00"}],\n'
            '  "differential": ["鉴别诊断1", "鉴别诊断2"],\n'
            '  "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",\n'
            '  "status": "complete 或 incomplete"\n'
            "}\n\n"
            "【严格引用约束（极重要）】：\n"
            "1. 你的输出中 key_concerns 和 recommendations 的每一项，必须包含 source_id 字段。\n"
            "2. source_id 的值必须严格照抄上述【权威指南参考】中每条文本开头的编号！必须包含方括号！例如参考中第一条是\"[NCCN-13] ...\"，则填\"[NCCN-13]\"。\n"
            "3. 绝对禁止凭空捏造参考中不存在的编号！如果该建议无法对应到参考中的具体编号，source_id 必须填写 \"R00\"。"
    )
    return prompt


def run_integration_agent(task_id: str, image_result: dict, clinical_result: dict, pathology_result: dict,
                          rag_passages: list) -> dict:
    """
    整合 Agent：融合多源特征，生成结构化报告。
    """
    def get_fallback_report(risk_msg="AI 推理异常", concern_msg="整合推理失败，请结合临床经验判断"):
        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_msg, "source_id": "R00"}],
            "recommendations": [{"item": "建议优先完善相关检查或寻求第二意见", "source_id": "R00"}],
            "differential": ["推理服务暂不可用"],
            "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",
            "status": "incomplete"
        }

    if settings.USE_MOCK_INTEGRATION:
        logger.info(f"Running MOCK Integration Agent for task: {task_id}")
        missing_modalities = []
        if not image_result: missing_modalities.append("图像")
        if not clinical_result: missing_modalities.append("临床")
        if not pathology_result: missing_modalities.append("病理")

        risk_msg = "数据不足无法评估" if missing_modalities else "中危 (Mock)"
        concern_text = f"缺乏{'、'.join(missing_modalities)}信息，建议完善相关检查" if missing_modalities else "Mock关注要点"

        is_complete = not missing_modalities and (
                    pathology_result is not None and pathology_result.get("t_stage") not in ["未提供", "无法分期"])

        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_text, "source_id": "R00"}],
            "recommendations": [{"item": "请完善相关检查 (Mock建议)", "source_id": "R00"}],
            "differential": ["Mock黑色素瘤", "Mock色素痣"],
            "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",
            "status": "complete" if is_complete else "incomplete"
        }

    logger.info(f"Running REAL Integration Agent for task: {task_id}")
    try:
        client = OpenAI(
            api_key=settings.INTEGRATION_API_KEY,
            base_url=settings.INTEGRATION_BASE_URL
        )

        prompt = _build_dynamic_prompt(image_result, clinical_result, pathology_result)

        if rag_passages:
            rag_text = "\n".join(rag_passages)
            prompt += f"\n\n【权威指南参考】（必须基于以下参考作答并照抄编号）：\n{rag_text}"

        response = client.chat.completions.create(
            model=settings.INTEGRATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=15.0
        )

        result_str = response.choices[0].message.content

        try:
            parsed_data = json.loads(result_str)
        except json.JSONDecodeError:
            logger.warning(f"LLM output JSON decode failed, attempting json-repair. Raw: {result_str[:100]}...")
            parsed_data = json_repair.loads(result_str)

        is_incomplete_by_data = (pathology_result is None or pathology_result.get("t_stage") in ["未提供", "无法分期", "非黑色素瘤病变"])
        llm_status = parsed_data.get("status", "incomplete").lower()

        final_status = "incomplete" if is_incomplete_by_data or llm_status == "incomplete" else "complete"

        final_data = {
            "task_id": task_id,
            "risk_level": parsed_data.get("risk_level", "数据不足无法评估"),
            "key_concerns": parsed_data.get("key_concerns", [{"item": "未提取到关注要点", "source_id": "R00"}]),
            "recommendations": parsed_data.get("recommendations", [{"item": "请结合临床判断", "source_id": "R00"}]),
            "differential": parsed_data.get("differential", ["未知"]),
            "disclaimer": parsed_data.get("disclaimer",
                                          "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断"),
            "status": final_status
        }

        for item in final_data["key_concerns"]:
            if isinstance(item, dict): item.setdefault("source_id", "R00")
        for item in final_data["recommendations"]:
            if isinstance(item, dict): item.setdefault("source_id", "R00")

        logger.info(f"Integration Agent successful for task: {task_id}, status: {final_status}")
        return final_data

    except Exception as e:
        logger.error(f"Integration Agent API call failed for task {task_id}: {e}", exc_info=True)
        return get_fallback_report()