import logging
from rag.knowledge_base import RAGKnowledgeBase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Starting RAG Knowledge Base initialization from script...")
    try:
        kb = RAGKnowledgeBase(docs_dir="./rag/docs")
        kb.init_from_documents()
        logger.info("RAG Knowledge Base initialization completed successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize RAG Knowledge Base: {e}")