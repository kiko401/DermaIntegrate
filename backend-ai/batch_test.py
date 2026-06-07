# backend-ai/batch_test.py
import json
import uuid
import time
import logging
from agents.clinical_agent import parse_clinical_data
from agents.pathology_agent import evaluate_pathology_data
from agents.integration_agent import run_integration_agent
from rag.knowledge_base import RAGKnowledgeBase

# 配置日志，只显示 INFO 级别，避免底层 DEBUG 刷屏
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化 RAG (耗时操作，只做一次)
print("⏳ 正在初始化 RAG 知识库...")
kb = RAGKnowledgeBase(docs_dir="./rag/docs")
print("✅ RAG 知识库初始化完成！\n")

# ==========================================
# 定义批量测试用例 (自然语言病历 + 病理 JSON)
# ==========================================
test_cases = [
    {
        "case_id": "Case-01-高危肢端型",
        "clinical_text": "患者男性，62岁。左足底发现一黑色斑块，直径约15mm，近期明显增大隆起，伴有瘙痒和偶尔出血。既往体健。",
        "pathology_json": {"breslow_thickness_mm": 5.2, "ulceration": True, "braf_mutation": "突变型",
                           "lymph_node_status": None}
    },
    {
        "case_id": "Case-02-黏膜型晚期",
        "clinical_text": "女性，55岁。口腔上颚黏膜出现黑斑，破溃疼痛一月余。既往有系统性红斑狼疮病史。",
        "pathology_json": {"breslow_thickness_mm": 3.5, "ulceration": True, "braf_mutation": "野生型",
                           "nras_mutation": "突变型", "ldh_level": True}
    },
    {
        "Case-03-早期皮肤型": {
            "clinical_text": "男性，45岁。背部发现一颗黑痣，近期颜色变深，边界稍显不规则，无破溃。无家族史。",
            "pathology_json": {"breslow_thickness_mm": 0.6, "ulceration": False, "lymph_node_status": "阴性"}
        }
    },
    {
        "case_id": "Case-04-数据缺失型",
        "clinical_text": "右手拇指甲床变黑两月，范围扩大，有压痛。患者拒绝活检，目前无病理报告。",
        "pathology_json": None  # 无病理数据
    },
    {
        "case_id": "Case-05-良性怀疑型",
        "clinical_text": "躯干多发褐色丘疹，其中一个边缘规则，颜色均匀，直径4mm，表面有油腻性鳞屑，似乎贴在皮肤上。",
        "pathology_json": None
    },
    {
        "case_id": "Case-06-高危体征无病理",
        "clinical_text": "左侧足跟一黑色结节，近期快速增大，表面溃疡渗血，边缘极不规则，颜色深浅不一。",
        "pathology_json": None
    }
]

# 修正 Case-03 的字典嵌套错误
test_cases[2] = {
    "case_id": "Case-03-早期皮肤型",
    "clinical_text": "男性，45岁。背部发现一颗黑痣，近期颜色变深，边界稍显不规则，无破溃。无家族史。",
    "pathology_json": {"breslow_thickness_mm": 0.6, "ulceration": False, "lymph_node_status": "阴性"}
}


def run_batch_tests():
    results_summary = []

    for case in test_cases:
        case_id = case["case_id"]
        print("\n" + "=" * 80)
        print(f"🚀 开始测试: {case_id}")
        print("=" * 80)

        task_id = str(uuid.uuid4())

        # -----------------------------------
        # Step 1: 病历 Agent 解析
        # -----------------------------------
        print("\n[Step 1] 病历 Agent 解析中...")
        clinical_result = parse_clinical_data(clinical_text=case["clinical_text"])
        print(
            f"  ➡️ 解析结果 (部分): region={clinical_result.get('lesion_clinical', {}).get('region')}, symptoms={clinical_result.get('lesion_symptoms')}")

        # 提取部位供跨模态依赖使用
        lesion_location = clinical_result.get("lesion_clinical", {}).get("region")

        # -----------------------------------
        # Step 2: 病理与分子 Agent 评估
        # -----------------------------------
        print("\n[Step 2] 病理与分子 Agent 评估中...")
        pathology_result = evaluate_pathology_data(
            pathology_json=case["pathology_json"],
            location_from_clinical=lesion_location
        )
        print(f"  ➡️ T分期: {pathology_result.get('t_stage')}")
        print(f"  ➡️ 治疗建议: {pathology_result.get('treatment_recommendations')}")
        print(f"  ➡️ 缺失警告: {pathology_result.get('missing_data_warnings')}")

        # -----------------------------------
        # Step 3: RAG 两阶段检索
        # -----------------------------------
        print("\n[Step 3] RAG 专科知识检索中...")
        rag_passages = kb.retrieve(
            image_result=None,
            clinical_result=clinical_result,
            pathology_result=pathology_result,
            top_k=3
        )
        print(f"  ➡️ 召回法条数: {len(rag_passages)}")
        for i, p in enumerate(rag_passages):
            # 只打印前 80 字符，避免刷屏
            print(f"     [{i + 1}] {p[:80]}...")

        # -----------------------------------
        # Step 4: 整合 Agent 生成报告
        # -----------------------------------
        print("\n[Step 4] 整合 Agent 生成报告中 (可能需要几秒)...")
        final_report = run_integration_agent(
            task_id=task_id,
            image_result=None,
            clinical_result=clinical_result,
            pathology_result=pathology_result,
            rag_passages=rag_passages
        )

        print("\n✅ 最终报告:")
        print(f"  ➡️ 风险等级: {final_report.get('risk_level')}")
        print(f"  ➡️ 报告状态: {final_report.get('status')}")
        print(f"  ➡️ 关注要点:")
        for concern in final_report.get("key_concerns", []):
            print(f"     - {concern.get('item')} (来源: {concern.get('source_id')})")
        print(f"  ➡️ 建议:")
        for rec in final_report.get("recommendations", []):
            print(f"     - {rec.get('item')} (来源: {rec.get('source_id')})")

        results_summary.append({
            "case_id": case_id,
            "risk_level": final_report.get("risk_level"),
            "status": final_report.get("status"),
            "sources": [c.get("source_id") for c in final_report.get("key_concerns", [])]
        })

        # 防止 API 限流
        time.sleep(2)

    # ==========================================
    # 汇总展示
    # ==========================================
    print("\n\n" + "#" * 80)
    print("📊 批量测试汇总报告")
    print("#" * 80)
    for res in results_summary:
        print(f"[{res['case_id']}] 风险: {res['risk_level']} | 状态: {res['status']} | 引用: {res['sources']}")


if __name__ == "__main__":
    run_batch_tests()