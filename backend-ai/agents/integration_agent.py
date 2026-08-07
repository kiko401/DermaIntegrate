import json
import logging
from pathlib import Path
from openai import OpenAI
import json_repair
from config import settings
from shared.constants import INTERNAL_SOURCE_ID
from shared.config import LLM_READ_TIMEOUT

logger = logging.getLogger(__name__)

_INTEGRATION_TEMPLATE = (
    Path(__file__).parent.parent / "prompts" / "integration_report.txt"
).read_text(encoding="utf-8")


def _build_dynamic_prompt(image_result: dict, clinical_result: dict, pathology_result: dict, rag_passages: list) -> str:
    """
    根据输入数据动态拼接 LLM 推理 Prompt。

    核心原则：
    1. 视觉/临床数据缺失时，明确提示LLM建议补充检查。
    2. 若已提供病理分期，不得因模态缺失否定该结论（综合研判锚定原则）。
    3. 强制全中文输出。
    """
    evidence_parts = []

    if image_result and image_result.get("morphology"):
        morph = image_result["morphology"]
        location = image_result.get("location", "未知")
        coverage = image_result.get("coverage", 0)
        evidence_parts.append(
            f"【视觉证据】：皮肤镜形态学特征提取如下：{json.dumps(morph, ensure_ascii=False)}。"
            f"病灶位于图像{location}，占比约{coverage * 100:.1f}%。"
        )
    else:
        evidence_parts.append("【视觉证据】：未提供影像信息，请在建议中优先考虑完善皮肤镜或皮损局部拍照检查。")

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
            "【病理与分子规则】：未提供病理活检信息，缺乏金标准，必须在建议中强烈建议行皮肤活检明确病理诊断。"
        )

    rag_text = "\n".join(rag_passages) if rag_passages else "（无可用权威指南参考）"
    rag_section = f"\n\n【权威指南参考】（必须基于以下参考作答并照抄编号）：\n{rag_text}"

    # 使用 str.replace 替代 .format()，避免 JSON 示例中的 {/} 被误解析为占位符
    return (
        _INTEGRATION_TEMPLATE
        .replace("__EVIDENCE__", "\n".join(evidence_parts))
        .replace("__RAG_PASSAGES__", rag_section)
    )


def run_integration_agent(
        task_id: str,
        image_result: dict,
        clinical_result: dict,
        pathology_result: dict,
        rag_passages: list
) -> dict:
    """
    整合 Agent：融合多模态特征与 RAG 知识，生成结构化辅助诊断报告。

    Args:
        task_id: 任务ID，用于日志追踪。
        image_result: 视觉 Agent 输出（含 morphology, location, coverage）。
        clinical_result: 临床 Agent 输出（结构化病历）。
        pathology_result: 病理 Agent 输出（含 T 分期、治疗建议）。
        rag_passages: RAG 检索到的权威指南片段列表。

    Returns:
        dict: 包含 risk_level, key_concerns, recommendations 等字段的标准化报告。
    """

    def get_fallback_report(risk_msg="AI 推理异常", concern_msg="整合推理失败，请结合临床经验判断"):
        """生成降级兜底报告，确保前端不崩溃。"""
        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_msg, "source_id": INTERNAL_SOURCE_ID}],
            "recommendations": [{"item": "建议优先完善相关检查或寻求第二意见", "source_id": INTERNAL_SOURCE_ID}],
            "differential": ["推理服务暂不可用"],
            "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",
            "status": "complete"
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
                pathology_result is not None and
                pathology_result.get("t_stage") not in ["未提供", "无法分期"]
        )

        return {
            "task_id": task_id,
            "risk_level": risk_msg,
            "key_concerns": [{"item": concern_text, "source_id": INTERNAL_SOURCE_ID}],
            "recommendations": [{"item": "请完善相关检查 (Mock建议)", "source_id": INTERNAL_SOURCE_ID}],
            "differential": ["Mock黑色素瘤", "Mock色素痣"],
            "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",
            "status": "complete"
        }

    logger.info(f"Running REAL Integration Agent for task: {task_id}")
    try:
        client = OpenAI(
            api_key=settings.INTEGRATION_API_KEY,
            base_url=settings.INTEGRATION_BASE_URL
        )

        prompt = _build_dynamic_prompt(image_result, clinical_result, pathology_result, rag_passages)

        response = client.chat.completions.create(
            model=settings.INTEGRATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=LLM_READ_TIMEOUT
        )

        result_str = response.choices[0].message.content

        try:
            parsed_data = json.loads(result_str)
        except json.JSONDecodeError:
            logger.warning(f"LLM output JSON decode failed, attempting json-repair. Raw: {result_str[:100]}...")
            parsed_data = json_repair.loads(result_str)


        final_data = {
            "task_id": task_id,
            "risk_level": parsed_data.get("risk_level", "数据不足无法评估"),
            "key_concerns": parsed_data.get("key_concerns", [{"item": "未提取到关注要点", "source_id": INTERNAL_SOURCE_ID}]),
            "recommendations": parsed_data.get("recommendations", [{"item": "请结合临床判断", "source_id": INTERNAL_SOURCE_ID}]),
            "differential": parsed_data.get("differential", ["未知"]),
            "disclaimer": parsed_data.get("disclaimer",
                                          "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断"),
            "status": "complete"
        }

        # 确保 source_id 不缺失
        for item in final_data["key_concerns"]:
            if isinstance(item, dict):
                item.setdefault("source_id", "R00")
        for item in final_data["recommendations"]:
            if isinstance(item, dict):
                item.setdefault("source_id", "R00")

        logger.info(f"Integration Agent successful for task: {task_id}, status: complete")
        return final_data

    except Exception as e:
        logger.error(f"Integration Agent API call failed for task {task_id}: {e}", exc_info=True)
        return get_fallback_report()
