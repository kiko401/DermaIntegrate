"""
医学实体抽取模块

功能：
- 通用 NER：bert-base-chinese 识别通用命名实体（PER/LOC/ORG）
- 医学词典：规则匹配医学领域专有名词（药物/疾病/基因突变等）
- 正则抽取：基因突变、蛋白名称等结构化格式

输出：
  List[{"name": str, "type": str, "normalized": str, "start": int, "end": int}]

实体类型：
  DISEASE   疾病（黑色素瘤、非小细胞肺癌）
  DRUG      药物（帕博利珠单抗、达拉菲尼）
  GENE      基因（BRAF、PD-1、EGFR）
  MUTATION  突变类型（BRAF V600E、EGFR L858R）
  STAGING   分期（T1b、N2a、TNM分期）
  TREATMENT 治疗方式（免疫治疗、靶向治疗、化疗）
  PROCEDURE 手术/操作（淋巴结清扫、分子靶向治疗）
  BIOMARKER 生物标志物（PD-L1、MSI-H）
"""
import re
import logging
from typing import List, Dict, Tuple, Optional, Set

from shared.config import NER_MODEL

logger = logging.getLogger(__name__)

# ===== 医学词典（规则匹配）=====
# 格式：名称 -> 类型

MEDICAL_DRUGS: Set[Tuple[str, str]] = {
    # 靶向药
    ("帕博利珠单抗", "pembrolizumab", "PD-1抑制剂"),
    ("卡瑞利珠单抗", "camrelizumab", "PD-1抑制剂"),
    ("特瑞普利单抗", "toripalimab", "PD-1抑制剂"),
    ("信迪利单抗", "sintilimab", "PD-1抑制剂"),
    ("替雷利珠单抗", "tislelizumab", "PD-1抑制剂"),
    ("度伐利尤单抗", "durvalumab", "PD-L1抑制剂"),
    ("阿替利珠单抗", "atezolizumab", "PD-L1抑制剂"),
    ("纳武利尤单抗", "nivolumab", "PD-1抑制剂"),
    ("伊匹木单抗", "ipilimumab", "CTLA-4抑制剂"),
    ("达拉菲尼", "dabrafenib", "BRAF抑制剂"),
    ("曲美替尼", "trametinib", "MEK抑制剂"),
    ("维莫非尼", "vemurafenib", "BRAF抑制剂"),
    ("康奈非尼", "encorafenib", "BRAF抑制剂"),
    ("比美替尼", "binimetinib", "MEK抑制剂"),
    ("考比替尼", "cobimetinib", "MEK抑制剂"),
    ("达帕菲尼", "dabrafenib", "BRAF抑制剂"),
    ("培唑帕尼", "pazopanib", "VEGFR抑制剂"),
    ("舒尼替尼", "sunitinib", "VEGFR抑制剂"),
    ("索拉菲尼", "sorafenib", "VEGFR抑制剂"),
    ("仑伐替尼", "lenvatinib", "VEGFR抑制剂"),
    ("阿帕替尼", "apatinib", "VEGFR抑制剂"),
    ("特发性肺纤维化药", ""),
    ("紫杉醇", "paclitaxel", "化疗药"),
    ("卡铂", "carboplatin", "化疗药"),
    ("顺铂", "cisplatin", "化疗药"),
    ("培美曲塞", "pemetrexed", "化疗药"),
    ("吉非替尼", "gefitinib", "EGFR-TKI"),
    ("厄洛替尼", "erlotinib", "EGFR-TKI"),
    ("阿法替尼", "afatinib", "EGFR-TKI"),
    ("奥希替尼", "osimertinib", "EGFR-TKI"),
    ("阿美替尼", "ameizumab", "EGFR-TKI"),
    ("伏美替尼", "vomerertinib", "EGFR-TKI"),
    ("克唑替尼", "crizotinib", "ALK抑制剂"),
    ("阿来替尼", "alectinib", "ALK抑制剂"),
    ("色瑞替尼", "ceritinib", "ALK抑制剂"),
    ("劳拉替尼", "lorlatinib", "ALK抑制剂"),
    ("贝伐珠单抗", "bevacizumab", "VEGF单抗"),
    ("利妥昔单抗", "rituximab", "CD20单抗"),
    ("西妥昔单抗", "cetuximab", "EGFR单抗"),
    ("帕尼单抗", "panitumumab", "EGFR单抗"),
    ("尼妥珠单抗", "nimotuzumab", "EGFR单抗"),
    ("伊立替康", "irinotecan", "化疗药"),
    ("氟尿嘧啶", "5-FU", "化疗药"),
    ("卡培他滨", "capecitabine", "化疗药"),
    ("替莫唑胺", "temozolomide", "化疗药"),
    ("替吉奥", "S-1", "化疗药"),
    ("白蛋白紫杉醇", "nab-paclitaxel", "化疗药"),
    ("多柔比星", "doxorubicin", "化疗药"),
    ("表柔比星", "epirubicin", "化疗药"),
    ("环磷酰胺", "cyclophosphamide", "化疗药"),
    ("异环磷酰胺", "ifosfamide", "化疗药"),
    ("长春新碱", "vincristine", "化疗药"),
    ("依托泊苷", "etoposide", "化疗药"),
    ("多西他赛", "docetaxel", "化疗药"),
    ("伊沙匹隆", "ixabepilone", "化疗药"),
    # 免疫治疗
    ("干扰素", "interferon", "免疫治疗"),
    ("白介素", "IL-2", "免疫治疗"),
    ("胸腺肽", "thymosin", "免疫治疗"),
    ("gp100", "gp100", "肿瘤疫苗"),
    ("T-VEC", "talimogene laherparepvec", "肿瘤病毒疫苗"),
    ("S-1", "tegafur-gimeracil-oteracil", "口服氟尿嘧啶"),
}

# 药物词典（名称 -> 标准名/英文名）
DRUG_DICTIONARY: Dict[str, Tuple[str, str]] = {
    "帕博利珠单抗": ("帕博利珠单抗", "pembrolizumab"),
    "卡瑞利珠单抗": ("卡瑞利珠单抗", "camrelizumab"),
    "特瑞普利单抗": ("特瑞普利单抗", "toripalimab"),
    "信迪利单抗": ("信迪利单抗", "sintilimab"),
    "替雷利珠单抗": ("替雷利珠单抗", "tislelizumab"),
    "度伐利尤单抗": ("度伐利尤单抗", "durvalumab"),
    "阿替利珠单抗": ("阿替利珠单抗", "atezolizumab"),
    "纳武利尤单抗": ("纳武利尤单抗", "nivolumab"),
    "伊匹木单抗": ("伊匹木单抗", "ipilimumab"),
    "达拉菲尼": ("达拉菲尼", "dabrafenib"),
    "曲美替尼": ("曲美替尼", "trametinib"),
    "维莫非尼": ("维莫非尼", "vemurafenib"),
    "康奈非尼": ("康奈非尼", "encorafenib"),
    "比美替尼": ("比美替尼", "binimetinib"),
    "考比替尼": ("考比替尼", "cobimetinib"),
    "培唑帕尼": ("培唑帕尼", "pazopanib"),
    "舒尼替尼": ("舒尼替尼", "sunitinib"),
    "索拉菲尼": ("索拉菲尼", "sorafenib"),
    "仑伐替尼": ("仑伐替尼", "lenvatinib"),
    "阿帕替尼": ("阿帕替尼", "apatinib"),
    "紫杉醇": ("紫杉醇", "paclitaxel"),
    "卡铂": ("卡铂", "carboplatin"),
    "顺铂": ("顺铂", "cisplatin"),
    "培美曲塞": ("培美曲塞", "pemetrexed"),
    "吉非替尼": ("吉非替尼", "gefitinib"),
    "厄洛替尼": ("厄洛替尼", "erlotinib"),
    "阿法替尼": ("阿法替尼", "afatinib"),
    "奥希替尼": ("奥希替尼", "osimertinib"),
    "阿美替尼": ("阿美替尼", "ameizumab"),
    "伏美替尼": ("伏美替尼", "vomerertinib"),
    "克唑替尼": ("克唑替尼", "crizotinib"),
    "阿来替尼": ("阿来替尼", "alectinib"),
    "色瑞替尼": ("色瑞替尼", "ceritinib"),
    "劳拉替尼": ("劳拉替尼", "lorlatinib"),
    "贝伐珠单抗": ("贝伐珠单抗", "bevacizumab"),
    "利妥昔单抗": ("利妥昔单抗", "rituximab"),
    "西妥昔单抗": ("西妥昔单抗", "cetuximab"),
    "帕尼单抗": ("帕尼单抗", "panitumumab"),
    "尼妥珠单抗": ("尼妥珠单抗", "nimotuzumab"),
    "伊立替康": ("伊立替康", "irinotecan"),
    "氟尿嘧啶": ("氟尿嘧啶", "5-FU"),
    "卡培他滨": ("卡培他滨", "capecitabine"),
    "替莫唑胺": ("替莫唑胺", "temozolomide"),
    "替吉奥": ("替吉奥", "S-1"),
    "白蛋白紫杉醇": ("白蛋白紫杉醇", "nab-paclitaxel"),
    "多柔比星": ("多柔比星", "doxorubicin"),
    "表柔比星": ("表柔比星", "epirubicin"),
    "环磷酰胺": ("环磷酰胺", "cyclophosphamide"),
    "异环磷酰胺": ("异环磷酰胺", "ifosfamide"),
    "长春新碱": ("长春新碱", "vincristine"),
    "依托泊苷": ("依托泊苷", "etoposide"),
    "多西他赛": ("多西他赛", "docetaxel"),
}

# 疾病词典
DISEASE_DICTIONARY: Dict[str, str] = {
    "黑色素瘤": "黑色素瘤",
    "皮肤黑色素瘤": "黑色素瘤",
    "肢端黑色素瘤": "肢端黑色素瘤",
    "黏膜黑色素瘤": "黏膜黑色素瘤",
    "脉络膜黑色素瘤": "脉络膜黑色素瘤",
    "非小细胞肺癌": "非小细胞肺癌",
    "小细胞肺癌": "小细胞肺癌",
    "肺腺癌": "肺腺癌",
    "肺鳞癌": "肺鳞癌",
    "乳腺癌": "乳腺癌",
    "三阴性乳腺癌": "三阴性乳腺癌",
    "HER2阳性乳腺癌": "HER2阳性乳腺癌",
    "胃癌": "胃癌",
    "胃腺癌": "胃腺癌",
    "结直肠癌": "结直肠癌",
    "结肠癌": "结肠癌",
    "直肠癌": "直肠癌",
    "肝癌": "肝癌",
    "肝细胞癌": "肝细胞癌",
    "胆管癌": "胆管癌",
    "胰腺癌": "胰腺癌",
    "食管癌": "食管癌",
    "头颈癌": "头颈癌",
    "鼻咽癌": "鼻咽癌",
    "喉癌": "喉癌",
    "卵巢癌": "卵巢癌",
    "宫颈癌": "宫颈癌",
    "子宫内膜癌": "子宫内膜癌",
    "前列腺癌": "前列腺癌",
    "肾癌": "肾癌",
    "膀胱癌": "膀胱癌",
    "尿路上皮癌": "尿路上皮癌",
    "淋巴瘤": "淋巴瘤",
    "霍奇金淋巴瘤": "霍奇金淋巴瘤",
    "非霍奇金淋巴瘤": "非霍奇金淋巴瘤",
    "多发性骨髓瘤": "多发性骨髓瘤",
    "急性髓性白血病": "急性髓性白血病",
    "急性淋巴细胞白血病": "急性淋巴细胞白血病",
    "慢性髓性白血病": "慢性髓性白血病",
    "慢性淋巴细胞白血病": "慢性淋巴细胞白血病",
    "骨髓增生异常综合征": "骨髓增生异常综合征",
    "胸腺瘤": "胸腺瘤",
    "胸腺癌": "胸腺癌",
    "胃肠道间质瘤": "胃肠道间质瘤",
    "神经内分泌肿瘤": "神经内分泌肿瘤",
    "黑色素瘤脑转移": "黑色素瘤脑转移",
}

# 基因词典
GENE_DICTIONARY: Dict[str, str] = {
    "BRAF": "BRAF",
    "BRAF V600E": "BRAF V600E",
    "BRAF V600K": "BRAF V600K",
    "BRAF V600": "BRAF V600",
    "EGFR": "EGFR",
    "EGFR L858R": "EGFR L858R",
    "EGFR 19del": "EGFR 19del",
    "EGFR T790M": "EGFR T790M",
    "EGFR C797S": "EGFR C797S",
    "ALK": "ALK",
    "ALK 融合": "ALK 融合",
    "EML4-ALK": "EML4-ALK",
    "ROS1": "ROS1",
    "ROS1 融合": "ROS1 融合",
    "MET": "MET",
    "MET 扩增": "MET 扩增",
    "MET exon 14": "MET exon 14",
    "RET": "RET",
    "RET 融合": "RET 融合",
    "NTRK": "NTRK",
    "NTRK 融合": "NTRK 融合",
    "NTRK1": "NTRK1",
    "NTRK2": "NTRK2",
    "NTRK3": "NTRK3",
    "KRAS": "KRAS",
    "KRAS G12C": "KRAS G12C",
    "KRAS G12D": "KRAS G12D",
    "NRAS": "NRAS",
    "HRAS": "HRAS",
    "PIK3CA": "PIK3CA",
    "AKT1": "AKT1",
    "AKT2": "AKT2",
    "PTEN": "PTEN",
    "TP53": "TP53",
    "RB1": "RB1",
    "MYC": "MYC",
    "BCL2": "BCL2",
    "CDK4": "CDK4",
    "CDK6": "CDK6",
    "MDM2": "MDM2",
    "CDKN2A": "CDKN2A",
    "NF1": "NF1",
    "NF2": "NF2",
    "SMAD4": "SMAD4",
    "APC": "APC",
    "CTNNB1": "CTNNB1",
    "ATM": "ATM",
    "BRCA1": "BRCA1",
    "BRCA2": "BRCA2",
    "PALB2": "PALB2",
    "CHEK2": "CHEK2",
    "NTRK": "NTRK",
    "TMB": "TMB",
    "MSI": "MSI",
    "MSI-H": "MSI-H",
    "PD-1": "PD-1",
    "PD-L1": "PD-L1",
    "PD-L2": "PD-L2",
    "CTLA-4": "CTLA-4",
    "LAG-3": "LAG-3",
    "TIM-3": "TIM-3",
    "TIGIT": "TIGIT",
    "VEGF": "VEGF",
    "VEGFR": "VEGFR",
    "HER2": "HER2",
    "HER3": "HER3",
    "ERBB2": "ERBB2",
    "ERBB3": "ERBB3",
    "c-KIT": "c-KIT",
    "KIT": "KIT",
    " PDGFR": "PDGFR",
    "CSF1R": "CSF1R",
    "FLT3": "FLT3",
    "IDH1": "IDH1",
    "IDH2": "IDH2",
    "FLT3 ITD": "FLT3 ITD",
    "DNMT3A": "DNMT3A",
    "TET2": "TET2",
    "ASXL1": "ASXL1",
    "EZH2": "EZH2",
    "SF3B1": "SF3B1",
    "SRSF2": "SRSF2",
    "U2AF1": "U2AF1",
    "ZRSR2": "ZRSR2",
    "RUNX1": "RUNX1",
    "CEBPA": "CEBPA",
    "NPM1": "NPM1",
    "WT1": "WT1",
    "GATA2": "GATA2",
    "ANKRD26": "ANKRD26",
    "DDX41": "DDX41",
    "ETV6": "ETV6",
    "RAD21": "RAD21",
    "SMC3": "SMC3",
    "STAG2": "STAG2",
}

# 分期词典
STAGING_PATTERNS = [
    r"T0", r"T1a", r"T1b", r"T1c", r"T2a", r"T2b", r"T3a", r"T3", r"T4a", r"T4b", r"T4",
    r"N0", r"N1a", r"N1b", r"N1c", r"N2a", r"N2b", r"N2c", r"N3a", r"N3b", r"N3c",
    r"M0", r"M1a", r"M1b", r"M1c", r"M1",
    r"TNM\s*[一二三四I-II-III-IV]期",
    r"(早期|中期|晚期|局部晚期|转移性|不可切除|可切除)",
    r"(新辅助|辅助|根治性|姑息性)",
]


# ===== NER 模型（延迟加载）=====

_ner_model = None
_ner_load_error: Optional[str] = None


def _get_ner_model():
    """获取 NER 模型实例（bert-base-chinese，延迟加载）"""
    global _ner_model, _ner_load_error
    if _ner_model is not None or _ner_load_error:
        return _ner_model

    try:
        from transformers import pipeline, AutoModelForTokenClassification, AutoTokenizer
        logger.info(f"Loading NER model: {NER_MODEL}")
        _ner_model = pipeline(
            "ner",
            model=AutoModelForTokenClassification.from_pretrained(NER_MODEL),
            tokenizer=AutoTokenizer.from_pretrained(NER_MODEL),
            aggregation_strategy="simple",
        )
        logger.info(f"NER model loaded successfully.")
        return _ner_model
    except Exception as e:
        _ner_load_error = str(e)
        logger.warning(f"NER model loading failed: {_ner_load_error}. Using rule-based NER only.")
        return None


# ===== 规则抽取 =====

def _rule_extract(text: str) -> List[Dict]:
    """
    规则抽取医学实体：
    1. 药物词典匹配
    2. 疾病词典匹配
    3. 基因词典匹配
    4. 基因突变正则匹配（BRAF V600E、EGFR L858R 等）
    5. 分期pattern匹配
    """
    entities = []
    seen: Set[Tuple[str, str]] = set()

    # 1. 药物
    for drug_name, (std_name, en_name) in DRUG_DICTIONARY.items():
        for m in re.finditer(re.escape(drug_name), text):
            key = (drug_name, "DRUG")
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": drug_name,
                    "type": "DRUG",
                    "normalized": std_name,
                    "start": m.start(),
                    "end": m.end(),
                })

    # 2. 疾病
    for disease_name, std_name in DISEASE_DICTIONARY.items():
        for m in re.finditer(re.escape(disease_name), text):
            key = (disease_name, "DISEASE")
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": disease_name,
                    "type": "DISEASE",
                    "normalized": std_name,
                    "start": m.start(),
                    "end": m.end(),
                })

    # 3. 基因
    for gene_name, std_name in GENE_DICTIONARY.items():
        for m in re.finditer(re.escape(gene_name), text):
            key = (gene_name, "GENE")
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": gene_name,
                    "type": "GENE",
                    "normalized": std_name,
                    "start": m.start(),
                    "end": m.end(),
                })

    # 4. 基因突变正则（BRAF V600E、EGFR 19del 等）
    mutation_patterns = [
        (r"BRAF\s*V600[EK]?", "BRAF突变", "MUTATION"),
        (r"EGFR\s*(L858R|19del|T790M|C797S|Exon\d+)", "EGFR突变", "MUTATION"),
        (r"KRAS\s*G12[ABCD][DSC]?", "KRAS突变", "MUTATION"),
        (r"NRAS\s*G12[ABCD][DSC]?", "NRAS突变", "MUTATION"),
        (r"ALK\s*融合", "ALK融合", "MUTATION"),
        (r"ROS1\s*融合", "ROS1融合", "MUTATION"),
        (r"MET\s*(exon\s*14|扩增)", "MET变异", "MUTATION"),
        (r"NTRK\s*(融合|1|2|3)", "NTRK变异", "MUTATION"),
        (r"MSI(-H|高)?", "MSI-H", "BIOMARKER"),
        (r"TMB\s*高", "TMB高", "BIOMARKER"),
        (r"PD-L1\s*(表达|阳性|≥\d+%)", "PD-L1表达", "BIOMARKER"),
        (r"HER2\s*(阳性|过表达|突变)", "HER2变异", "BIOMARKER"),
        (r"BRCA[12]?\s*(突变|缺失)", "BRCA变异", "BIOMARKER"),
    ]
    for pattern, norm_name, entity_type in mutation_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            key = (m.group(), entity_type)
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": m.group(),
                    "type": entity_type,
                    "normalized": norm_name,
                    "start": m.start(),
                    "end": m.end(),
                })

    # 5. TNM 分期
    for stage_pattern in STAGING_PATTERNS:
        for m in re.finditer(stage_pattern, text):
            key = (m.group(), "STAGING")
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": m.group(),
                    "type": "STAGING",
                    "normalized": m.group(),
                    "start": m.start(),
                    "end": m.end(),
                })

    return entities


def _model_ner(text: str, model) -> List[Dict]:
    """使用bert-base-chinese NER模型抽取实体"""
    try:
        results = model(text)
        entities = []
        seen: Set[Tuple[str, str]] = set()

        # bert-base-chinese 通用实体标签映射
        label_map = {
            "PER": ("PER", "人物"),
            "LOC": ("LOC", "地点"),
            "ORG": ("ORG", "机构"),
            # 部分模型会用这些
            "PERSON": ("PER", "人物"),
            "LOCATION": ("LOC", "地点"),
            "ORGANIZATION": ("ORG", "机构"),
        }

        for ent in results:
            label = ent.get("entity_group", ent.get("entity", ""))
            word = ent.get("word", "")
            if not word or len(word) < 2:
                continue

            # 映射到标准标签
            if label in label_map:
                mapped_label, _ = label_map[label]
            else:
                mapped_label = label

            key = (word, mapped_label)
            if key not in seen:
                seen.add(key)
                entities.append({
                    "name": word,
                    "type": mapped_label,
                    "normalized": word,
                    "start": ent.get("start", 0),
                    "end": ent.get("end", 0),
                })

        return entities
    except Exception as e:
        logger.warning(f"Model NER failed: {e}")
        return []


def extract_medical_entities(text: str) -> List[Dict]:
    """
    医学实体抽取主入口。

    策略：
    1. 规则抽取（词典 + 正则）：高精准，覆盖医学专有名词
    2. 模型抽取（bert-base-chinese NER）：补充通用命名实体
    3. 合并去重

    Args:
        text: 文本内容

    Returns:
        List[Dict]，每项含 name, type, normalized, start, end
    """
    if not text or len(text.strip()) < 3:
        return []

    entities = []

    # 1. 规则抽取（优先，精准）
    rule_entities = _rule_extract(text)
    entities.extend(rule_entities)

    # 2. 模型抽取（补充通用实体）
    model = _get_ner_model()
    if model is not None:
        model_entities = _model_ner(text, model)
        # 过滤掉已被规则覆盖的
        rule_keys = {(e["name"], e["type"]) for e in rule_entities}
        for me in model_entities:
            if (me["name"], me["type"]) not in rule_keys:
                entities.append(me)

    # 3. 按 start 排序
    entities.sort(key=lambda x: x["start"])

    return entities


def get_entity_signature(text: str) -> Dict[str, List[str]]:
    """
    返回实体的分类签名，供检索时 entity boost 使用。

    Returns:
        {
            "all": ["药物A", "基因B", "疾病C"],
            "drugs": [...],
            "genes": [...],
            "diseases": [...],
            "mutations": [...],
            "staging": [...]
        }
    """
    entities = extract_medical_entities(text)
    sig: Dict[str, List[str]] = {
        "all": [],
        "drugs": [],
        "genes": [],
        "diseases": [],
        "mutations": [],
        "staging": [],
        "biomarkers": [],
        "treatments": [],
    }
    seen: Set[str] = set()
    for e in entities:
        name = e["name"]
        if name in seen:
            continue
        seen.add(name)
        sig["all"].append(name)
        etype = e["type"]
        if etype == "DRUG":
            sig["drugs"].append(name)
        elif etype == "GENE":
            sig["genes"].append(name)
        elif etype == "DISEASE":
            sig["diseases"].append(name)
        elif etype == "MUTATION":
            sig["mutations"].append(name)
        elif etype == "STAGING":
            sig["staging"].append(name)
        elif etype == "BIOMARKER":
            sig["biomarkers"].append(name)
        elif etype == "TREATMENT":
            sig["treatments"].append(name)
    return sig
