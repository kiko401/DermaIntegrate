"""
知识库离线初始化脚本

用法：
    python init_rag.py                    # 初始化默认文档目录
    python init_rag.py --recreate         # 重建（清空现有数据）
    python init_rag.py --docs-dir ./docs  # 指定文档目录

推荐方式：
    通过 API 初始化（更智能，支持热更新）：
        POST /rag/init/from-docs
        GET  /rag/init/status
"""

import os
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='初始化 RAG 知识库')
    parser.add_argument('--docs-dir', type=str, default=None, help='文档目录路径')
    parser.add_argument('--recreate', action='store_true', help='是否重建（清空现有数据）')
    args = parser.parse_args()

    # 切换到脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    logger.info("=" * 50)
    logger.info("RAG 知识库初始化脚本")
    logger.info("=" * 50)

    try:
        from rag.knowledge_base import init_knowledge_base, check_knowledge_base_status

        # 检查当前状态
        status = check_knowledge_base_status()
        logger.info(f"当前状态: {status}")

        # 执行初始化
        result = init_knowledge_base(docs_dir=args.docs_dir, recreate=args.recreate)

        logger.info("=" * 50)
        logger.info("初始化结果:")
        for key, value in result.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 50)

        if result["status"] == "succeeded":
            logger.info("✅ 知识库初始化成功！")
            return 0
        else:
            logger.warning(f"⚠️ 知识库初始化跳过: {result.get('message')}")
            return 1

    except ImportError as e:
        logger.error(f"❌ 导入模块失败: {e}")
        logger.error("请确保已安装所有依赖：pip install -r requirements.txt")
        return 1
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
