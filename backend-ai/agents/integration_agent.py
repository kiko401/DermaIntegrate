import json
import logging
from openai import OpenAI
import json_repair
from config import settings  # 引入配置中心

logger = logging.getLogger(__name__)


def _build_dynamic_prompt(image_result: dict, clinical_result: dict, lab_result: dict) -> str:
    """
    根据输入数据的存在与否动态拼接 Prompt。
    若某模态缺失，明确指示 LLM 在建议中优先考虑完善相关检查。
    """
    evidence_parts = []

    # 1. 视觉证据
    if image_result and image_result.get("morphology"):
        morph = image_result["morphology"]
        evidence_parts.append(f"【视觉证据】：皮肤镜形态学特征提取如下：{json.dumps(morph, ensure_ascii=False)}")
    else:
        evidence_parts.append("【视觉证据】：未提供影像信息，请在建议中优先考虑完善皮肤镜检查。")

    # 2. 病历特征
    if clinical_result and any(v is not None for v in clinical_result.values()):
        # 过滤掉全为 None 的二级字典，让 LLM 聚焦有效信息
        filtered_clinical = {k: v for k, v in clinical_result.items() if
                             v is not None and isinstance(v, dict) and any(sv is not None for sv in v.values())}
        if filtered_clinical:
            evidence_parts.append(f"【病历特征】：结构化病历解析如下：{json.dumps(filtered_clinical, ensure_ascii=False)}")
        else:
            evidence_parts.append("【病历特征】：未提供有效病历信息，请在建议中优先考虑详细询问病史。")
    else:
        evidence_parts.append("【病历特征】：未提供病历信息，请在建议中优先考虑详细询问病史。")

    # 3. 化验规则
    if lab_result and lab_result.get("actions"):
        evidence_parts.append(
            f"【化验规则】：基于指南的规则引擎判定如下：风险为'{lab_result.get('risk', '未知')}'，分期为'{lab_result.get('stage', '未知')}'，触发的规则建议为：{json.dumps(lab_result.get('actions', []), ensure_ascii=False)}")
    else:
        evidence_parts.append("【化验规则】：未提供化验信息，请在建议中优先考虑完善病理活检及相关血液检查。")

    prompt = (
            "你是一个严谨的皮肤病专科辅助诊断AI助手。你的任务是根据提供的多模态证据，综合分析并输出结构化的辅助诊断报告。\n\n"
            "【核心约束】：\n"
            "1. 严禁输出终局诊断结论（如“确诊为黑色素瘤”），你只能提供风险分层和鉴别诊断建议。\n"
            "2. 如果某项证据缺失，你必须在建议中明确指出“缺乏XXX信息，建议优先完善相关检查”，切勿编造缺失信息。\n"
            "3. 必须以严格的 JSON 格式输出，包含以下键：risk_level, key_concerns, recommendations, differential, disclaimer。\n"
            "4. 所有的输出内容必须使用中文。\n\n"
            "【输入证据】：\n" + "\n".join(evidence_parts) + "\n\n"
                                                          "【输出格式要求】：\n"
                                                          "{\n"
                                                          '  "risk_level": "极高危/高危/中高危/中危/低危/数据不足无法评估",\n'
                                                          '  "key_concerns": [{"item": "关注要点1", "source_id": "R00"}, {"item": "关注要点2", "source_id": "R00"}],\n'
                                                          '  "recommendations": [{"item": "建议检查1", "source_id": "R00"}, {"item": "建议检查2", "source_id": "R00"}],\n'
                                                          '  "differential": ["鉴别诊断1", "鉴别诊断2"],\n'
                                                          '  "disclaimer": "本建议仅供辅助参考，最终诊断由执业医师结合临床判断"\n'
                                                          "}"
    )
    return prompt


def run_integration_agent(task_id: str, image_result: dict, clinical_result: dict, lab_result: dict,
                          rag_passages: list) -> dict:
    """
    整合 Agent：融合多源特征，生成结构化报告。
    如果 USE_MOCK_INTEGRATION=true 则走 Mock，否则调用真实 LLM。
    返回符合 SSEResultEvent 契约的字典。
    """

    # 兜底降级报告
    def get_fallback_report(risk_msg="AI 推理异常", concern_msg="整合推理失败，请结合临床经验判断"):
        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_msg, "source_id": "R00"}],
            "recommendations": [{"item": "建议优先完善相关检查或寻求第二意见", "source_id": "R00"}],
            "differential": ["推理服务暂不可用"],
            "disclaimer": "本建议仅供辅助参考，最终诊断由执业医师结合临床判断",
            "status": "completed"
        }

    # 1. 判断是否走 Mock (使用 settings 规范读取)
    if settings.USE_MOCK_INTEGRATION:
        logger.info(f"Running MOCK Integration Agent for task: {task_id}")
        missing_modalities = []
        if not image_result: missing_modalities.append("图像")
        if not clinical_result: missing_modalities.append("病历")
        if not lab_result: missing_modalities.append("化验")

        risk_msg = "数据不足无法评估" if missing_modalities else "中危 (Mock)"
        concern_text = f"缺乏{'、'.join(missing_modalities)}信息，建议完善相关检查" if missing_modalities else "Mock关注要点"

        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_text, "source_id": "R00"}],
            "recommendations": [{"item": "请完善相关检查 (Mock建议)", "source_id": "R00"}],
            "differential": ["Mock黑色素瘤", "Mock色素痣"],
            "disclaimer": "本建议仅供辅助参考，最终诊断由执业医师结合临床判断",
            "status": "completed"
        }

    # 2. 真实 LLM 调用逻辑
    logger.info(f"Running REAL Integration Agent for task: {task_id}")
    try:
        client = OpenAI(
            api_key=settings.INTEGRATION_API_KEY,
            base_url=settings.INTEGRATION_BASE_URL
        )

        prompt = _build_dynamic_prompt(image_result, clinical_result, lab_result)

        response = client.chat.completions.create(
            model=settings.INTEGRATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=15.0
        )

        result_str = response.choices[0].message.content

        # 3. 解析与容错 (引入 json-repair 兜底)
        try:
            parsed_data = json.loads(result_str)
        except json.JSONDecodeError:
            logger.warning(f"LLM output JSON decode failed, attempting json-repair. Raw: {result_str[:100]}...")
            parsed_data = json_repair.loads(result_str)

        # 4. 数据契约对齐
        final_data = {
            "task_id": task_id,
            "risk_level": parsed_data.get("risk_level", "数据不足无法评估"),
            "key_concerns": parsed_data.get("key_concerns", [{"item": "未提取到关注要点", "source_id": "R00"}]),
            "recommendations": parsed_data.get("recommendations", [{"item": "请结合临床判断", "source_id": "R00"}]),
            "differential": parsed_data.get("differential", ["未知"]),
            "disclaimer": parsed_data.get("disclaimer", "本建议仅供辅助参考，最终诊断由执业医师结合临床判断"),
            "status": "completed"
        }

        # 确保列表内的字典包含必须的键
        for item in final_data["key_concerns"]:
            if isinstance(item, dict): item.setdefault("source_id", "R00")
        for item in final_data["recommendations"]:
            if isinstance(item, dict): item.setdefault("source_id", "R00")

        logger.info(f"Integration Agent successful for task: {task_id}")
        return final_data

    except Exception as e:
        logger.error(f"Integration Agent API call failed for task {task_id}: {e}", exc_info=True)
        return get_fallback_report()