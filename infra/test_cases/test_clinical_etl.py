"""
业务流4: 临床病例ETL流程 - 完整测试套件

测试范围（覆盖临床病例ETL完整链路）:
- TC-CLIN-01: _build_clinical_text - 自然语言文本构建
- TC-CLIN-02: clinical_etl_and_ingest - 临床病例ETL完整流程
- TC-CLIN-03: clinical_etl_and_ingest - doctor_id RBAC权限隔离
- TC-CLIN-04: clinical_etl_and_ingest - department_id 过滤
- TC-CLIN-05: clinical_etl_and_ingest - 缺少patient_context的降级
- TC-CLIN-06: clinical_etl_and_ingest - 不同case_type生成不同doc_title
- TC-CLIN-07: 实体签名一致性 - chunk entities与entity_sig一致性
- TC-CLIN-08: 切片边界 - 临床长文本正确切分

执行方式:
    python test_clinical_etl.py
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend-ai"))

os.environ["QDRANT_HOST"] = "localhost"
os.environ["DOCKER_ENV"] = "false"

# ===== 测试数据 =====

CASE_MEL = {
    "patient_context": {
        "summary_text": "患者男性，68岁，左足底有一约1.2cm色素性皮损，近期明显增大。",
        "structured": {"age": 68, "gender": "男", "region": "左足底"}
    },
    "case_text": "左足底可见一约1.2cm×0.8cm不规则黑斑，边缘呈锯齿状，颜色深浅不均。病理活检回报：恶性黑色素瘤，Breslow厚度2.5mm，伴溃疡形成。基因检测：BRAF V600E突变阳性。",
    "case_type": "pathology"
}

CASE_HIS = {
    "patient_context": {
        "summary_text": "患者女性，45岁，右上臂出现一色素性皮损，半年内明显增大。",
        "structured": {"age": 45, "gender": "女", "region": "右上臂"}
    },
    "case_text": "右上臂可见一约0.8cm色素性皮损，边缘不规则，颜色不均。皮肤镜检查提示非典型色素网络。",
    "case_type": "his"
}

CASE_LIS = {
    "patient_context": {
        "summary_text": "患者男性，55岁，左手掌发现一色素性皮损。",
        "structured": {"age": 55, "gender": "男", "region": "左手掌"}
    },
    "case_text": "实验室检查：血常规正常，肝肾功能正常，LDH正常。",
    "case_type": "lis"
}

CASE_PACS = {
    "patient_context": {
        "summary_text": "患者男性，70岁，胸部CT发现一皮肤占位。",
        "structured": {"age": 70, "gender": "男", "region": "胸部"}
    },
    "case_text": "PET-CT：右胸部皮肤可见一高代谢结节，SUVmax=4.5，考虑恶性黑色素瘤。",
    "case_type": "pacs"
}


# ============================================================================
# TC-CLIN-01: _build_clinical_text 自然语言文本构建
# ============================================================================
def test_clin_01_build_clinical_text():
    """TC-CLIN-01: _build_clinical_text 自然语言文本构建"""
    print("\n" + "=" * 60)
    print("TC-CLIN-01: _build_clinical_text 自然语言文本构建")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import _build_clinical_text

    # 测试黑色素瘤病理病例
    result = _build_clinical_text(
        CASE_MEL["patient_context"],
        CASE_MEL["case_text"],
        CASE_MEL["case_type"]
    )
    print(f"[病理病例文本] {result}")
    assert "PATHOLOGY病例" in result, "应包含病例类型标签"
    assert "患者概况" in result, "应包含患者概况"
    assert "病例详情" in result, "应包含病例详情"
    assert "68" in result, "应包含年龄"
    assert "黑色素瘤" in result, "应包含病理诊断"
    assert "BRAF" in result, "应包含基因检测信息"

    # 测试HIS病例
    result2 = _build_clinical_text(
        CASE_HIS["patient_context"],
        CASE_HIS["case_text"],
        CASE_HIS["case_type"]
    )
    print(f"[HIS病例文本] {result2}")
    assert "HIS病例" in result2, "应包含HIS病例标签"
    assert "女" in result2, "应包含性别"

    # 测试空patient_context
    result3 = _build_clinical_text(
        {"summary_text": "", "structured": {}},
        "仅病例文本无摘要",
        "pathology"
    )
    print(f"[空摘要] {result3}")
    assert "PATHOLOGY病例" in result3, "空摘要时仍应有病例标签"
    assert "仅病例文本无摘要" in result3, "病例文本应被包含"

    # 测试 structured 字段拼接
    result4 = _build_clinical_text(
        {"summary_text": "患者概况", "structured": {"age": 60, "gender": "男", "region": "足底"}},
        "病例详情内容",
        "pathology"
    )
    print(f"[structured拼接] {result4}")
    assert "age为60" in result4 or "60" in result4, "structured字段应被拼接"

    print("✅ TC-CLIN-01 通过")


# ============================================================================
# TC-CLIN-02: clinical_etl_and_ingest 完整流程
# ============================================================================
def test_clin_02_full_clinical_etl():
    """TC-CLIN-02: clinical_etl_and_ingest 完整流程"""
    print("\n" + "=" * 60)
    print("TC-CLIN-02: clinical_etl_and_ingest 完整流程")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    kb_id = 991

    chunk_count, status = asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id,
        case_type=CASE_MEL["case_type"],
        patient_context=CASE_MEL["patient_context"],
        case_text=CASE_MEL["case_text"],
        doc_version_id=1,
        doctor_id=None,
        chunk_size=300,
        chunk_overlap=50,
        access_level="internal",
        department_id=None,
    ))

    print(f"[结果] chunk_count={chunk_count}, status={status}")
    assert chunk_count > 0, "应产生chunks"
    assert status == "succeeded", f"status应为succeeded，实际={status}"

    # 验证Qdrant数据
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()
    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
        ),
        limit=50,
        with_payload=True,
    )
    print(f"[Qdrant验证] kb_id={kb_id} 有 {len(results[0])} 个chunks")

    assert len(results[0]) == chunk_count, f"Qdrant chunks数量应等于返回的chunk_count"

    # 验证payload字段完整性
    pt = results[0][0]
    p = pt.payload
    print(f"[payload字段] doc_title={p.get('doc_title')}, access_level={p.get('access_level')}")
    assert p.get("doc_title") == "PATHOLOGY病例", f"doc_title应为PATHOLOGY病例，实际={p.get('doc_title')}"
    assert p.get("access_level") == "internal", f"access_level应为internal，实际={p.get('access_level')}"
    assert p.get("kb_id") == kb_id, "kb_id应一致"
    assert "chunk_id" in p, "应有chunk_id"
    assert "entities" in p, "应有entities字段"

    # 验证NER实体被抽取（黑色素瘤、BRAF等）
    entities = p.get("entities", [])
    entity_names = [e.get("name", "") for e in entities]
    print(f"[实体] {entity_names[:5]}")
    assert len(entities) > 0, "临床病例应抽取到实体"

    print("✅ TC-CLIN-02 通过")


# ============================================================================
# TC-CLIN-03: doctor_id RBAC权限隔离
# ============================================================================
def test_clin_03_doctor_id_rbac():
    """TC-CLIN-03: doctor_id RBAC权限隔离"""
    print("\n" + "=" * 60)
    print("TC-CLIN-03: doctor_id RBAC权限隔离")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    kb_id_doctor = 992
    doctor_id = 888

    chunk_count, status = asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_doctor,
        case_type=CASE_MEL["case_type"],
        patient_context=CASE_MEL["patient_context"],
        case_text=CASE_MEL["case_text"],
        doc_version_id=1,
        doctor_id=doctor_id,
        chunk_size=300,
        chunk_overlap=50,
        access_level="internal",
        department_id=10,
    ))

    print(f"[结果] chunk_count={chunk_count}, status={status}")
    assert status == "succeeded", f"status应为succeeded，实际={status}"

    # 验证Qdrant中doctor_id被正确写入
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()
    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id_doctor)),
                models.FieldCondition(key="doctor_id", match=models.MatchValue(value=doctor_id))
            ]
        ),
        limit=50,
        with_payload=True,
    )
    print(f"[Qdrant验证] kb_id={kb_id_doctor}&doctor_id={doctor_id} 有 {len(results[0])} 个chunks")
    assert len(results[0]) > 0, f"应有doctor_id={doctor_id}的chunks"

    # 验证department_id也被写入
    pt = results[0][0]
    assert pt.payload.get("department_id") == 10, f"department_id应为10，实际={pt.payload.get('department_id')}"
    assert pt.payload.get("doctor_id") == doctor_id, f"doctor_id应为{doctor_id}"

    print("✅ TC-CLIN-03 通过")


# ============================================================================
# TC-CLIN-04: department_id 过滤
# ============================================================================
def test_clin_04_department_id_filter():
    """TC-CLIN-04: department_id 过滤"""
    print("\n" + "=" * 60)
    print("TC-CLIN-04: department_id 过滤")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    # 写入两个不同科室的病例（使用不同doc_version_id避免chunk_id冲突）
    kb_id_dept = 993

    asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_dept,
        case_type="pathology",
        patient_context={"summary_text": "科室1患者", "structured": {"department_id": 1}},
        case_text="这是科室1的病例数据，具有独特的标识文本。",
        doc_version_id=1,
        doctor_id=801,
        access_level="internal",
        department_id=1,
    ))

    asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_dept,
        case_type="pathology",
        patient_context={"summary_text": "科室2患者", "structured": {"department_id": 2}},
        case_text="这是科室2的病例数据，具有独特的标识文本。",
        doc_version_id=2,  # 不同doc_version_id，chunk_id不同
        doctor_id=802,
        access_level="internal",
        department_id=2,
    ))

    # 验证两个科室的数据都写入
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()

    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id_dept))]
        ),
        limit=50,
        with_payload=True,
    )
    print(f"[Qdrant验证] kb_id={kb_id_dept} 共有 {len(results[0])} 个chunks")

    dept_1 = [pt for pt in results[0] if pt.payload.get("department_id") == 1]
    dept_2 = [pt for pt in results[0] if pt.payload.get("department_id") == 2]
    print(f"[科室分布] 科室1: {len(dept_1)} chunks, 科室2: {len(dept_2)} chunks")

    assert len(dept_1) > 0, "科室1应有数据"
    assert len(dept_2) > 0, "科室2应有数据"

    print("✅ TC-CLIN-04 通过")


# ============================================================================
# TC-CLIN-05: 缺少patient_context的降级
# ============================================================================
def test_clin_05_empty_patient_context():
    """TC-CLIN-05: 缺少patient_context的降级"""
    print("\n" + "=" * 60)
    print("TC-CLIN-05: 缺少patient_context的降级")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    kb_id_empty = 994

    # 空patient_context
    chunk_count, status = asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_empty,
        case_type="pathology",
        patient_context={},
        case_text="这是纯粹的病例文本，无患者上下文信息。黑色素瘤治疗方案包括手术和靶向治疗。",
        doc_version_id=1,
        doctor_id=None,
        chunk_size=200,
        chunk_overlap=30,
        access_level="internal",
        department_id=None,
    ))

    print(f"[空patient_context] chunk_count={chunk_count}, status={status}")
    assert chunk_count > 0, "空patient_context仍应产生chunks"
    assert status == "succeeded", f"status应为succeeded，实际={status}"

    # 验证Qdrant
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()
    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id_empty))]
        ),
        limit=10,
        with_payload=True,
    )
    assert len(results[0]) > 0, "Qdrant应有数据"

    print("✅ TC-CLIN-05 通过")


# ============================================================================
# TC-CLIN-06: 不同case_type生成不同doc_title
# ============================================================================
def test_clin_06_case_type_doc_title():
    """TC-CLIN-06: 不同case_type生成不同doc_title"""
    print("\n" + "=" * 60)
    print("TC-CLIN-06: 不同case_type生成不同doc_title")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    test_cases = [
        ("pathology", "PATHOLOGY病例"),
        ("his", "HIS病例"),
        ("lis", "LIS病例"),
        ("pacs", "PACS病例"),
    ]

    for case_index, (case_type, expected_title) in enumerate(test_cases):
        # 每个case用不同kb_id避免碰撞；同类测多次时用不同doc_version_id
        kb_id = 890 + case_index  # 890, 891, 892, 893

        chunk_count, status = asyncio.run(clinical_etl_and_ingest(
            kb_id=kb_id,
            case_type=case_type,
            patient_context={"summary_text": f"{case_type}患者", "structured": {}},
            case_text=f"这是{case_type}类型的病例数据 UniqueId={kb_id}。",
            doc_version_id=1,
            doctor_id=None,
            access_level="internal",
            department_id=None,
        ))

        print(f"[{case_type}] chunk_count={chunk_count}, status={status}")
        assert status == "succeeded", f"{case_type} ETL应成功"

        # 验证doc_title
        from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
        from qdrant_client.http import models
        client = get_qdrant_client()
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
            ),
            limit=10,
            with_payload=True,
        )
        if results[0]:
            doc_title = results[0][0].payload.get("doc_title", "")
            print(f"  [{case_type}] kb_id={kb_id} doc_title={doc_title} (expected={expected_title})")
            assert doc_title == expected_title, f"{case_type}的doc_title应为{expected_title}，实际={doc_title}"
        else:
            print(f"  [{case_type}] kb_id={kb_id} 无数据（可能被之前的同名chunk_id覆盖了）")
            assert False, f"{case_type} kb_id={kb_id}应有数据"

    print("✅ TC-CLIN-06 通过")


# ============================================================================
# TC-CLIN-07: 实体签名一致性
# ============================================================================
def test_clin_07_entity_signature_consistency():
    """TC-CLIN-07: 实体签名一致性 - chunk entities与entity_sig一致性"""
    print("\n" + "=" * 60)
    print("TC-CLIN-07: 实体签名一致性")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    kb_id_sig = 995
    case_text = (
        "恶性黑色素瘤患者，BRAF V600E突变阳性。 "
        "使用帕博利珠单抗和达拉非尼进行治疗。 "
        "基因检测显示NRAS突变阴性。"
    )

    chunk_count, status = asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_sig,
        case_type="pathology",
        patient_context={"summary_text": "患者信息", "structured": {}},
        case_text=case_text,
        doc_version_id=1,
        doctor_id=None,
        chunk_size=500,
        chunk_overlap=50,
        access_level="internal",
        department_id=None,
    ))

    print(f"[结果] chunk_count={chunk_count}, status={status}")
    assert status == "succeeded"

    # 验证entities和entity_sig一致性
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()
    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id_sig))]
        ),
        limit=50,
        with_payload=True,
    )

    for pt in results[0]:
        p = pt.payload
        entities = p.get("entities", [])
        entity_sig = p.get("entity_sig", {})
        sig_all = set(entity_sig.get("all", []))
        sig_diseases = set(entity_sig.get("diseases", []))
        sig_drugs = set(entity_sig.get("drugs", []))
        sig_genes = set(entity_sig.get("genes", []))

        entity_names = {e.get("name", "") for e in entities}

        print(f"[chunk_id={p.get('chunk_id')}]")
        print(f"  entities: {entity_names}")
        print(f"  entity_sig.all: {sig_all}")

        # entity_sig["all"] 应包含所有实体名称
        for en in entity_names:
            assert en in sig_all, f"实体名'{en}'应在entity_sig.all中，实际sig_all={sig_all}"

        # sig中标注的类别应与entities一致
        for e in entities:
            name = e.get("name", "")
            etype = e.get("type", "")
            if etype == "DISEASE":
                assert name in sig_diseases, f"疾病'{name}'应在entity_sig.diseases中"
            elif etype == "DRUG":
                assert name in sig_drugs, f"药物'{name}'应在entity_sig.drugs中"
            elif etype == "GENE":
                assert name in sig_genes, f"基因'{name}'应在entity_sig.genes中"

    print("✅ TC-CLIN-07 通过")


# ============================================================================
# TC-CLIN-08: 切片边界 - 临床长文本正确切分
# ============================================================================
def test_clin_08_long_text_chunking():
    """TC-CLIN-08: 切片边界 - 临床长文本正确切分"""
    print("\n" + "=" * 60)
    print("TC-CLIN-08: 切片边界 - 临床长文本正确切分")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    kb_id_long = 996

    # 构造一个超长病例文本，确保触发多chunk
    long_case_text = (
        "患者信息：男性，68岁，左足底皮损。".ljust(100, "　")
        + "病史：3年前发现左足底一米粒大小色素斑，近期明显增大，伴边缘不规则。".ljust(200, "　")
        + "查体：左足底可见一约1.2cm×0.8cm不规则黑斑，边缘呈锯齿状，颜色深浅不均，隆起约2mm。".ljust(300, "　")
        + "皮肤镜：非典型色素网络，蓝色漫反射，血管模式紊乱。".ljust(200, "　")
        + "病理：恶性黑色素瘤，Breslow厚度2.5mm，溃疡(+)，核分裂像5个/mm²。".ljust(200, "　")
        + "免疫组化：S-100(+)，HMB45(+)，MelanA(+)。".ljust(150, "　")
        + "基因检测：BRAF V600E突变(+)，NRAS突变(-)。".ljust(150, "　")
        + "治疗：行扩大切除术，前哨淋巴结活检阴性。".ljust(150, "　")
        + "随访：术后2年，无复发转移证据。".ljust(100, "　")
    )

    chunk_count, status = asyncio.run(clinical_etl_and_ingest(
        kb_id=kb_id_long,
        case_type="pathology",
        patient_context={
            "summary_text": "患者男性，68岁，左足底黑色素瘤",
            "structured": {"age": 68, "gender": "男", "region": "左足底"}
        },
        case_text=long_case_text,
        doc_version_id=1,
        doctor_id=None,
        chunk_size=200,
        chunk_overlap=30,
        access_level="internal",
        department_id=None,
    ))

    print(f"[长文本切片] chunk_count={chunk_count}, status={status}")
    assert chunk_count > 1, f"长文本应产生多个chunks，实际={chunk_count}"
    assert status == "succeeded"

    # 验证Qdrant中的chunk完整性
    from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.http import models
    client = get_qdrant_client()
    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id_long))]
        ),
        limit=100,
        with_payload=True,
    )
    assert len(results[0]) == chunk_count, "Qdrant chunks数量应一致"

    # 验证chunk_id唯一性
    chunk_ids = [pt.payload.get("chunk_id") for pt in results[0]]
    assert len(set(chunk_ids)) == len(chunk_ids), "chunk_id应唯一"

    # 验证is_first和is_last
    first_chunks = [pt for pt in results[0] if pt.payload.get("is_first_chunk")]
    last_chunks = [pt for pt in results[0] if pt.payload.get("is_last_chunk")]
    assert len(first_chunks) == 1, "应恰好有1个is_first_chunk=True的chunk"
    assert len(last_chunks) == 1, "应恰好有1个is_last_chunk=True的chunk"

    print(f"[切片验证] chunk_count={chunk_count}, first={first_chunks[0].payload.get('chunk_id')}, last={last_chunks[0].payload.get('chunk_id')}")

    print("✅ TC-CLIN-08 通过")


# ============================================================================
# TC-CLIN-09: clinical ETL job状态跟踪
# ============================================================================
def test_clin_09_job_status_tracking():
    """TC-CLIN-09: clinical ETL job状态跟踪"""
    print("\n" + "=" * 60)
    print("TC-CLIN-09: clinical ETL job状态跟踪")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import get_etl_jobs_list

    jobs = get_etl_jobs_list(limit=20)
    print(f"[ETL任务列表] 共{len(jobs)}个任务")

    if len(jobs) > 0:
        job = jobs[0]
        print(f"[最新任务] job_id={job['job_id']}, status={job['status']}, progress={job['progress']}")
        required_fields = ["job_id", "status", "progress", "stage", "created_at"]
        for field in required_fields:
            assert field in job, f"任务应有{field}字段"
        assert job["status"] in ("running", "succeeded", "failed", "pending"), f"非法status: {job['status']}"

    print("✅ TC-CLIN-09 通过")


# ============================================================================
# TC-CLIN-10: 重名患者病例隔离（doc_id = kb_id）
# ============================================================================
def test_clin_10_doc_id_uses_kb_id():
    """TC-CLIN-10: 重名患者病例隔离（doc_id = kb_id）"""
    print("\n" + "=" * 60)
    print("TC-CLIN-10: 重名患者病例隔离（doc_id = kb_id）")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import clinical_etl_and_ingest

    # 同一文本写入不同kb_id
    case_text = "相同内容的病例文本，但属于不同知识库。"

    for kb_id in [901, 902]:
        chunk_count, status = asyncio.run(clinical_etl_and_ingest(
            kb_id=kb_id,
            case_type="pathology",
            patient_context={"summary_text": f"kb_id={kb_id}患者", "structured": {}},
            case_text=case_text,
            doc_version_id=1,
            doctor_id=None,
            access_level="internal",
            department_id=None,
        ))

        assert status == "succeeded", f"kb_id={kb_id} ETL应成功"

        # 验证doc_id = kb_id（确保不同kb的chunk_id不互相覆盖）
        from modules.kb_rag.ingest.vector_store import get_qdrant_client, COLLECTION_NAME
        from qdrant_client.http import models
        client = get_qdrant_client()
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
            ),
            limit=10,
            with_payload=True,
        )
        assert len(results[0]) > 0, f"kb_id={kb_id}应有数据"

        pt = results[0][0]
        assert pt.payload.get("doc_id") == kb_id, f"doc_id应等于kb_id({kb_id})，实际={pt.payload.get('doc_id')}"

        # 验证不同kb_id的chunk_id不冲突（格式：{kb_id}_{doc_version_id}_{chunk_index:03d}）
        chunk_id = pt.payload.get("chunk_id", "")
        assert chunk_id.startswith(f"{kb_id}_"), f"chunk_id应以其kb_id({kb_id})开头，实际={chunk_id}"
        print(f"[kb_id={kb_id}] chunk_id={chunk_id}, doc_id={pt.payload.get('doc_id')}")

    print("✅ TC-CLIN-10 通过")


# ============================================================================
# 主函数
# ============================================================================
def run_all_tests():
    print("\n" + "=" * 70)
    print("  业务流4: 临床病例ETL流程 - 完整测试套件")
    print("=" * 70)

    tests = [
        ("TC-CLIN-01", test_clin_01_build_clinical_text),
        ("TC-CLIN-02", test_clin_02_full_clinical_etl),
        ("TC-CLIN-03", test_clin_03_doctor_id_rbac),
        ("TC-CLIN-04", test_clin_04_department_id_filter),
        ("TC-CLIN-05", test_clin_05_empty_patient_context),
        ("TC-CLIN-06", test_clin_06_case_type_doc_title),
        ("TC-CLIN-07", test_clin_07_entity_signature_consistency),
        ("TC-CLIN-08", test_clin_08_long_text_chunking),
        ("TC-CLIN-09", test_clin_09_job_status_tracking),
        ("TC-CLIN-10", test_clin_10_doc_id_uses_kb_id),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for test_id, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ {test_id} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ {test_id} 异常: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"测试结果: {passed} 通过, {failed} 失败, {skipped} 跳过")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
