"""
多模态推理管线执行器，运行在独立子线程中。
"""

import os
import json
import logging
import threading
import asyncio

from config import settings
from agents.vlm_agent import VLMAgent
from agents.clinical_agent import parse_clinical_data
from agents.pathology_agent import evaluate_pathology_data
from agents.integration_agent import run_integration_agent
from rag.knowledge_base import RAGKnowledgeBase
from exceptions import ModelInferenceException, DiagnosisUncertainException
from cnn.lesion_extractor import LesionExtractor

logger = logging.getLogger(__name__)

lesion_extractor = LesionExtractor()
vlm_agent = VLMAgent()


def run_pipeline_with_cancel(
        task_id: str,
        image_uid: str | None,
        original_image_path: str | None,
        clinical_text: str | None,
        clinical_json: str | None,
        lab_json: str | None,
        cancel_event: threading.Event,
        queue: asyncio.Queue,
        rag_kb: RAGKnowledgeBase | None,
) -> None:
    """
    多模态推理管线，在独立子线程中执行，通过 Queue 向主线程推送进度事件。
    协调各 Agent 调用，支持客户端断连取消。
    """
    image_result: dict | None = None
    clinical_result: dict | None = None
    pathology_result: dict | None = None

    try:
        if image_uid and original_image_path:
            if cancel_event.is_set():
                raise InterruptedError()

            evidence_filename = f"{image_uid}_evidence.png"
            evidence_path = os.path.join(settings.STATIC_DIR, "heatmaps", evidence_filename)

            visual_features = lesion_extractor.generate(
                original_image_path, evidence_path, cancel_event=cancel_event
            )
            evidence_url = f"/ai-static/heatmaps/{evidence_filename}"

            if cancel_event.is_set():
                raise InterruptedError()
            morphology_dict = vlm_agent.analyze(
                original_image_path, evidence_path, cancel_event=cancel_event
            )

            image_result = {
                "image_url": evidence_url,
                "morphology": morphology_dict,
                "coverage": visual_features.get("coverage", 0) if visual_features else 0,
                "location": visual_features.get("location", "未知") if visual_features else "未知"
            }

            queue.put_nowait(("step", {
                "step": "image_done",
                "message": "视觉定位与形态学完成",
                "data": image_result
            }))

        if clinical_json or clinical_text:
            if cancel_event.is_set():
                raise InterruptedError()
            logger.info(f"Task {task_id}: Running Clinical Agent...")

            c_json_str: str | None = None
            if clinical_json:
                c_json_str = clinical_json if isinstance(clinical_json, str) else json.dumps(clinical_json)

            clinical_result = parse_clinical_data(
                clinical_json_str=c_json_str,
                clinical_text=clinical_text
            )
            queue.put_nowait(("step", {
                "step": "clinical_done",
                "message": "病历结构化解析完成",
                "data": clinical_result
            }))

        if lab_json:
            if cancel_event.is_set():
                raise InterruptedError()
            logger.info(f"Task {task_id}: Running Pathology Agent...")

            path_dict: dict = lab_json if isinstance(lab_json, dict) else json.loads(lab_json)
            lesion_location: str | None = None
            if clinical_result and clinical_result.get("lesion_clinical"):
                lesion_location = clinical_result.get("lesion_clinical", {}).get("region")

            pathology_result = evaluate_pathology_data(
                pathology_json=path_dict,
                location_from_clinical=lesion_location
            )
            queue.put_nowait(("step", {
                "step": "pathology_done",
                "message": "病理与分子规则引擎完成",
                "data": pathology_result
            }))

        rag_passages: list[str] = []
        if rag_kb:
            if cancel_event.is_set():
                raise InterruptedError()
            try:
                rag_passages = rag_kb.retrieve(image_result, clinical_result, pathology_result, top_k=3)
                logger.info(f"Task {task_id}: Retrieved {len(rag_passages)} RAG passages.")
            except Exception as e:
                logger.error(f"Task {task_id}: RAG retrieval failed: {e}. Proceeding without RAG.")

        if cancel_event.is_set():
            raise InterruptedError()
        final_report_dict = run_integration_agent(
            task_id, image_result, clinical_result, pathology_result, rag_passages
        )

        # 先发送 final step 事件，触发 90% progress；再发送 final_data
        queue.put_nowait(("step", {
            "step": "final",
            "message": "综合报告生成完成",
        }))
        queue.put_nowait(("final_data", final_report_dict))

    except InterruptedError:
        logger.info(f"Pipeline execution cancelled for task: {task_id}")
        queue.put_nowait(("error", {"error_code": "CANCELLED", "message": "推理任务被中断取消"}))
    except ModelInferenceException as e:
        logger.error(f"Model inference failed for task {task_id}: {e}")
        queue.put_nowait(("error", {"error_code": "INFERENCE_FAILED", "message": str(e)}))
    except DiagnosisUncertainException as e:
        logger.warning(f"Evidence chain broken for task {task_id}: {e}")
        queue.put_nowait(("error", {"error_code": "EVIDENCE_CHAIN_BROKEN", "message": str(e)}))
    except Exception as e:
        logger.error(f"Pipeline unknown error for task {task_id}: {e}", exc_info=True)
        queue.put_nowait(("error", {"error_code": "INTERNAL_ERROR", "message": f"未知异常: {str(e)}"}))
