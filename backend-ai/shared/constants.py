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

# ============================================================
# 文档标签白名单
# ============================================================
# 来源：疾病代码 + 分期标签 + 临床特征标签 + 通用标签
# 与 DISEASE_REGISTRY.keys() 保持一致，新增病种时同步扩展
VALID_TAGS = set(DISEASE_REGISTRY.keys()) | {"T1", "T2", "T3", "T4", "高危", "肢端", "黏膜", "通用"}
