from rag.knowledge_base import RAGKnowledgeBase
import os

DOCS_DIR = "./rag/docs"

if __name__ == "__main__":
    if not os.path.exists(DOCS_DIR):
        print(f"❌ 找不到文档目录: {DOCS_DIR}")
    else:
        # 1. 初始化并构建知识库
        kb = RAGKnowledgeBase()
        kb.init_from_documents(DOCS_DIR)

        # 2. 测试检索
        query = "边缘不规则色素网络"
        print(f"\n🔍 正在检索: '{query}'")
        results = kb.retrieve(query, top_k=2)

        print("\n✅ 检索结果：")
        for i, text in enumerate(results):
            print(f"[片段 {i + 1}]: {text}")