"""
共享常量定义

所有业务域共享的常量数据存放于此，避免循环依赖。
包含：疾病注册表、源码标识常量、算法参数等。
"""

# ============================================================
# 源码标识常量
# ============================================================
# AI 推理结果中 source_id 的取值定义
# 用于标识推理结果的来源：
# - R00: 系统内部生成/降级回复
# - R01-R99: 保留扩展
# - KB001-KB999: 知识库检索来源
# - EXT001-EXT999: 外部工具/数据源
INTERNAL_SOURCE_ID = "R00"

# ============================================================
# BM25 算法参数（两处定义统一来源）
# ============================================================
# BM25_K1: 词频饱和参数，控制词频增长对得分的影响程度
# BM25_B: 文档长度归一化参数，控制文档长度对得分的影响程度
# AVG_DOC_LEN: 平均文档长度（字符数），用于长度归一化
BM25_K1 = 1.5
BM25_B = 0.75
AVG_DOC_LEN = 200

# ============================================================
# 疾病注册表
# ============================================================
# 疾病注册表：key=代码, value={name, keywords, is_malignant, needs_staging, rag_template}
# 新增病种只需在此处配置，无需修改核心路由逻辑
DISEASE_REGISTRY = {
    "MEL": {
        "name": "黑色素瘤",
        "keywords": ["黑色素瘤", "恶黑", "恶性黑色素瘤"],
        "is_malignant": True,
        "needs_staging": True,
        "rag_template": "{subtype}黑色素瘤，病灶位于{region}，病理分期为{stage}的诊疗指南"
    },
    "BCC": {
        "name": "基底细胞癌",
        "keywords": ["基底细胞癌", "基底细胞瘤", "bcc"],
        "is_malignant": True,
        "needs_staging": False,
        "rag_template": "基底细胞癌，病灶位于{region}的诊疗指南"
    },
    "SCC": {
        "name": "鳞状细胞癌",
        "keywords": ["鳞状细胞癌", "鳞癌", "scc"],
        "is_malignant": True,
        "needs_staging": False,
        "rag_template": "鳞状细胞癌，病灶位于{region}的诊疗指南"
    },
    "NEV": {
        "name": "色素痣",
        "keywords": ["痣", "色素痣", "皮内痣", "交界痣", "混合痣", "蓝痣", "梭形细胞痣"],
        "is_malignant": False,
        "needs_staging": False,
        "rag_template": "色素痣，病灶位于{region}的诊疗指南"
    },
    "ACK": {
        "name": "日光性角化病",
        "keywords": ["日光性角化", "日光性角化病"],
        "is_malignant": False,
        "needs_staging": False,
        "rag_template": "日光性角化病，病灶位于{region}的诊疗指南"
    },
    "SEK": {
        "name": "脂溢性角化病",
        "keywords": ["脂溢性角化", "老年斑", "脂溢性角化病"],
        "is_malignant": False,
        "needs_staging": False,
        "rag_template": "脂溢性角化病，病灶位于{region}的诊疗指南"
    }
}
