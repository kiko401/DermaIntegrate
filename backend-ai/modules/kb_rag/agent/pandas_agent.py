import io
import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def analyze(dataset_csv: str, query: str) -> Dict[str, Any]:
    """
    Pandas Agent 受控执行逻辑。
    接收应用域传来的 CSV 字符串，在内存中构建 DataFrame 并执行分析。
    """
    logger.info(f"Pandas Agent received query: {query}")

    if not dataset_csv:
        return {"error": "传入的数据集为空"}

    try:
        # 将应用域传来的 CSV 字符串读入内存为 DataFrame
        df = pd.read_csv(io.StringIO(dataset_csv))

        if df.empty:
            return {"error": "数据集为空或解析失败"}

        query_lower = query.lower()

        # 意图识别：统计指定列的分布
        if "统计" in query:
            # 尝试匹配列名 (简单的模糊匹配)
            target_col = None
            for col in df.columns:
                if col in query_lower or col in query:
                    target_col = col
                    break

            # 如果没找到指定列，智能找一个非数值的分类列
            if not target_col:
                for col in df.columns:
                    # 使用 is_numeric_dtype 健壮地判断非数值列
                    if not pd.api.types.is_numeric_dtype(df[col]):
                        target_col = col
                        break

            if target_col:
                counts = df[target_col].value_counts().to_dict()
                return {
                    "summary": f"已完成统计，按 【{target_col}】 共返回 {len(counts)} 类分布。",
                    "data": counts,
                    "chart_type": "bar"
                }
            else:
                return {"error": "未找到可统计的分类列", "available_columns": list(df.columns)}

        # 意图识别：查看数据预览
        elif "预览" in query or "前" in query or "列表" in query:
            preview_data = df.head(5).to_dict(orient="records")
            return {
                "summary": f"返回数据集前 {len(preview_data)} 行预览。",
                "data": preview_data,
                "chart_type": "table"
            }

        # 默认：返回数据集基本信息
        else:
            return {
                "summary": f"数据集包含 {len(df)} 条记录，列名: {list(df.columns)}。",
                "data": {"row_count": len(df), "columns": list(df.columns)},
                "chart_type": "info"
            }

    except Exception as e:
        logger.error(f"Pandas analysis failed: {e}", exc_info=True)
        return {"error": f"分析执行失败: {str(e)}"}