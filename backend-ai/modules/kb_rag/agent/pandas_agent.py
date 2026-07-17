import io
import json
import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)


def analyze(dataset_ref: str, query: str) -> Dict[str, Any]:
    """
    Pandas Agent 受控执行逻辑。

    接收应用域传来的数据集引用或内容，在内存中构建 DataFrame 并执行分析。
    L-05: 支持 CSV 字符串、JSON 字符串（或列表）两种格式。
    L-06: 改为同步函数（原为 async 但无任何 await 点）。

    Args:
        dataset_ref: 数据集内容（CSV 字符串或 JSON 字符串/列表）
        query: 自然语言分析请求

    Returns:
        分析结果字典
    """
    logger.info(f"Pandas Agent received query: {query}")

    if not dataset_ref:
        return {"error": "传入的数据集为空"}

    try:
        # L-05: 支持 CSV 和 JSON 两种格式
        dataset_ref_stripped = dataset_ref.strip()
        if dataset_ref_stripped.startswith("["):
            # JSON 数组格式（List[dict]）
            try:
                records = json.loads(dataset_ref_stripped)
                df = pd.DataFrame(records)
            except json.JSONDecodeError as e:
                return {"error": f"JSON 解析失败: {str(e)}"}
        elif dataset_ref_stripped.startswith("{"):
            # JSON 对象格式（单个 dict）
            try:
                obj = json.loads(dataset_ref_stripped)
                df = pd.DataFrame([obj])
            except json.JSONDecodeError as e:
                return {"error": f"JSON 解析失败: {str(e)}"}
        else:
            # 默认为 CSV 格式
            df = pd.read_csv(io.StringIO(dataset_ref))

        if df.empty:
            return {"error": "数据集为空或解析失败"}

        query_lower = query.lower()

        # 意图识别：统计指定列的分布
        if "统计" in query:
            # 尝试匹配列名（简单的模糊匹配）
            target_col = None
            for col in df.columns:
                if col in query_lower or col in query:
                    target_col = col
                    break

            # 如果没找到指定列，智能找一个非数值的分类列
            if not target_col:
                for col in df.columns:
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
        return {
            "summary": f"数据集包含 {len(df)} 条记录，列名: {list(df.columns)}。",
            "data": {"row_count": len(df), "columns": list(df.columns)},
            "chart_type": "info"
        }

    except Exception as e:
        logger.error(f"Pandas analysis failed: {e}", exc_info=True)
        return {"error": f"分析执行失败: {str(e)}"}
