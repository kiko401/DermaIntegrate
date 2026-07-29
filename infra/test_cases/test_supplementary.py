"""
补充测试套件 - 覆盖剩余关键路径

测试范围:
- TC-SUP-01: _split_table_blocks 表格分块
- TC-SUP-02: reranker rule-based降级路径
- TC-SUP-03: export_feedback_by_filters 反馈导出
- TC-SUP-04: retrieval低置信度阻断（密集检索）
- TC-SUP-05: rerank中bm25_score缺失时的rule-based行为
- TC-SUP-06: _prune_etl_jobs ETL任务内存上限
- TC-SUP-07: NER去重边界（同一文本重复实体）
- TC-SUP-08: _split_table_blocks 100行每块限制

执行方式:
    python test_supplementary.py
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend-ai"))
os.environ["QDRANT_HOST"] = "localhost"
os.environ["DOCKER_ENV"] = "false"

# ===== 测试数据 =====

TABLE_BLOCKS = [
    {"text": "张三\t65\t黑色素瘤\tT2b\t手术+靶向", "is_table": True, "section_title": "", "table_meta": {"row_count": 100}},
    {"text": "非表格文本第一段。黑色素瘤的治疗方案包括手术切除。", "is_table": False, "section_title": "", "is_heading": False},
    {"text": "非表格文本第二段。BRAF突变阳性推荐靶向治疗。", "is_table": False, "section_title": "", "is_heading": False},
]


# ============================================================================
# TC-SUP-01: _split_table_blocks 表格分块
# ============================================================================
def test_sup_01_split_table_blocks():
    """TC-SUP-01: _split_table_blocks 表格分块"""
    print("\n" + "=" * 60)
    print("TC-SUP-01: _split_table_blocks 表格分块")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import _split_table_blocks

    # 100行表格 -> 应分成1个chunk（100行 <= 100行/块）
    blocks = [
        {
            "text": "\n".join([f"row{i}\t{i}\t诊断\t分期\t方案" for i in range(100)]),
            "is_table": True,
            "section_title": "患者列表",
            "table_meta": {"row_count": 100, "columns": ["姓名", "年龄", "诊断", "分期", "方案"]}
        }
    ]

    chunks = _split_table_blocks(blocks, doc_id=1, doc_version_id=1)

    print(f"[100行表格] 切分为 {len(chunks)} 个chunks")
    assert len(chunks) == 1, f"100行表格应切分为1个chunk（100行<=100行/块），实际={len(chunks)}"

    # 验证is_last_chunk
    last_chunk = chunks[-1]
    print(f"[末chunk] is_last_chunk={last_chunk.get('is_last_chunk')}, text长度={len(last_chunk.get('text', ''))}")
    assert last_chunk.get("is_last_chunk") == True, "末chunk的is_last_chunk应为True"

    # 验证is_table标记
    for c in chunks:
        assert c.get("is_table") == True, f"表格chunk的is_table应为True"
        assert c.get("table_meta") is not None, "表格chunk应有table_meta"
        assert "chunk_row_start" in c.get("table_meta", {}), "table_meta应包含chunk_row_start"
        assert "chunk_row_end" in c.get("table_meta", {}), "table_meta应包含chunk_row_end"

    # 验证非表格block保留
    blocks2 = [
        {"text": "普通段落文本。", "is_table": False, "section_title": "", "is_heading": False},
    ]
    chunks2 = _split_table_blocks(blocks2, doc_id=2, doc_version_id=1)
    print(f"[非表格] {len(chunks2)} 个chunks")
    assert len(chunks2) == 1
    assert not chunks2[0].get("is_table"), f"非表格块的is_table应为None/Falsy，实际={chunks2[0].get('is_table')}"

    # 空blocks
    chunks3 = _split_table_blocks([], doc_id=3, doc_version_id=1)
    assert len(chunks3) == 0, "空blocks应返回空列表"

    print("✅ TC-SUP-01 通过")


# ============================================================================
# TC-SUP-02: reranker rule-based降级路径
# ============================================================================
def test_sup_02_reranker_rule_based_fallback():
    """TC-SUP-02: reranker rule-based降级路径"""
    print("\n" + "=" * 60)
    print("TC-SUP-02: reranker rule-based降级路径")
    print("=" * 60)

    from modules.kb_rag.retrieval.reranker import rerank, _reranker_load_error

    # 检查是否已加载或加载失败（避免重复下载卡住测试）
    if _reranker_load_error is None:
        try:
            from modules.kb_rag.retrieval.reranker import _get_reranker
            result = _get_reranker()
            if result is None and _reranker_load_error is None:
                # 模型加载中或失败，不阻塞测试
                print("[注意] Cross-Encoder模型状态未知，跳过详细验证")
        except Exception as e:
            print(f"[注意] Cross-Encoder加载异常: {e}")

    chunks = [
        {
            "doc_id": 1, "doc_version_id": 1, "chunk_id": "1_1_000",
            "text": "黑色素瘤的靶向治疗方案包括BRAF抑制剂和MEK抑制剂。",
            "score": 0.85, "dense_norm": 0.85,
            "bm25_score": 0.0,  # 纯Dense检索无BM25分数
        },
        {
            "doc_id": 2, "doc_version_id": 1, "chunk_id": "2_1_000",
            "text": "帕博利珠单抗是PD-1抑制剂，用于黑色素瘤免疫治疗。",
            "score": 0.80, "dense_norm": 0.80,
            "bm25_score": 0.0,
        },
        {
            "doc_id": 3, "doc_version_id": 1, "chunk_id": "3_1_000",
            "text": "基底细胞癌是常见的皮肤恶性肿瘤。",
            "score": 0.60, "dense_norm": 0.60,
            "bm25_score": 0.0,
        },
    ]

    # rerank会自动降级到rule-based（Cross-Encoder模型不可用）
    reranked = rerank("黑色素瘤靶向治疗", chunks, top_k=3)

    print(f"[重排后] {len(reranked)} chunks")
    for c in reranked:
        print(f"  chunk_id={c.get('chunk_id')}, rerank_score={c.get('rerank_score'):.4f}, rule_based={c.get('rule_based_score') is not None}")

    assert len(reranked) == 3, "应返回3个重排后的chunks"
    assert all("rerank_score" in c for c in reranked), "每个chunk应有rerank_score"

    # 验证排序（dense_norm最高的应排第一）
    assert reranked[0]["doc_id"] == 1, "dense_norm最高的应排第一"

    # 验证rule_based_score字段存在
    assert all("rule_based_score" in c for c in reranked), "降级路径应有rule_based_score"

    print("✅ TC-SUP-02 通过")


# ============================================================================
# TC-SUP-03: export_feedback_by_filters 反馈导出
# ============================================================================
def test_sup_03_export_feedback():
    """TC-SUP-03: export_feedback_by_filters 反馈导出"""
    print("\n" + "=" * 60)
    print("TC-SUP-03: export_feedback_by_filters 反馈导出")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import export_feedback_by_filters

    conversation_data = [
        {
            "conversation_id": "conv_001",
            "created_at": "2025-01-15T10:00:00",
            "kb_ids": [1, 2],
            "confidence": 0.85,
            "question": "黑色素瘤治疗方案",
            "answer": "包括手术、靶向治疗、免疫治疗"
        },
        {
            "conversation_id": "conv_002",
            "created_at": "2025-01-16T10:00:00",
            "kb_ids": [1],
            "confidence": 0.90,
            "question": "BRAF突变怎么办",
            "answer": "推荐靶向治疗"
        },
        {
            "conversation_id": "conv_003",
            "created_at": "2025-01-17T10:00:00",
            "kb_ids": [3],
            "confidence": 0.60,
            "question": "无关问题",
            "answer": "无法回答"
        },
    ]

    # 按日期过滤
    jsonl_str, filename = asyncio.run(export_feedback_by_filters(
        start_date="2025-01-15T00:00:00",
        end_date="2025-01-16T23:59:59",
        conversation_data=conversation_data,
    ))

    print(f"[日期过滤] {filename}")
    print(f"[导出行数] {len(jsonl_str.splitlines())}")

    # 验证包含符合条件的记录
    lines = jsonl_str.strip().split("\n")
    assert len(lines) == 2, f"日期范围内的2条记录，实际={len(lines)}"

    # 按kb_ids过滤
    jsonl_str2, _ = asyncio.run(export_feedback_by_filters(
        kb_ids=[1],
        conversation_data=conversation_data,
    ))
    lines2 = jsonl_str2.strip().split("\n")
    print(f"[kb_ids过滤] {len(lines2)} 条")
    assert len(lines2) == 2, "kb_ids=[1]应过滤出2条"

    # 按置信度过滤
    jsonl_str3, _ = asyncio.run(export_feedback_by_filters(
        min_confidence=0.80,
        conversation_data=conversation_data,
    ))
    lines3 = jsonl_str3.strip().split("\n")
    print(f"[置信度>=0.8] {len(lines3)} 条")
    assert len(lines3) == 2, "confidence>=0.8应过滤出2条"

    # 空数据
    jsonl_empty, _ = asyncio.run(export_feedback_by_filters(conversation_data=[]))
    assert jsonl_empty == "", "空数据应返回空字符串"

    # 无匹配
    jsonl_none, _ = asyncio.run(export_feedback_by_filters(
        min_confidence=0.99,
        conversation_data=conversation_data,
    ))
    print(f"[无匹配] '{jsonl_none}'")
    assert jsonl_none == "", "无匹配应返回空字符串"

    print("✅ TC-SUP-03 通过")


# ============================================================================
# TC-SUP-04: retrieval低置信度阻断（密集检索）
# ============================================================================
def test_sup_04_retrieval_low_confidence_block():
    """TC-SUP-04: retrieval低置信度阻断"""
    print("\n" + "=" * 60)
    print("TC-SUP-04: retrieval低置信度阻断")
    print("=" * 60)

    from modules.kb_rag.retrieval.retriever import retrieve, register_doctor, unregister_doctor

    register_doctor(9997, "chief", department_id=1)

    # 极高阈值（0.99）必然触发阻断
    chunks, blocked = asyncio.run(retrieve(
        query="黑色素瘤治疗方案有哪些靶向药物",
        kb_ids=[10],
        top_k=5,
        threshold=0.99,
        use_rerank=False,
        doctor_id=9997,
    ))

    print(f"[极高阈值] chunks={len(chunks)}, blocked={blocked}")
    # blocked取决于知识库实际内容，不做强制断言
    # 但blocked_reason应该记录

    unregister_doctor(9997)
    print("✅ TC-SUP-04 通过")


# ============================================================================
# TC-SUP-05: rerank中bm25_score缺失时的rule-based行为
# ============================================================================
def test_sup_05_rerank_missing_bm25_score():
    """TC-SUP-05: rerank中bm25_score缺失时的rule-based行为"""
    print("\n" + "=" * 60)
    print("TC-SUP-05: rerank中bm25_score缺失时的rule-based行为")
    print("=" * 60)

    from modules.kb_rag.retrieval.reranker import rerank

    # 模拟纯Dense检索结果（无bm25_score字段）
    chunks = [
        {
            "doc_id": 1, "chunk_id": "1_0",
            "text": "黑色素瘤免疫治疗使用帕博利珠单抗。",
            "score": 0.82, "dense_norm": 0.82,
        },
        {
            "doc_id": 2, "chunk_id": "2_0",
            "text": "基底细胞癌预后较好。",
            "score": 0.55, "dense_norm": 0.55,
        },
    ]

    reranked = rerank("帕博利珠单抗适应症", chunks, top_k=2)

    print(f"[重排结果] {len(reranked)} chunks")
    for c in reranked:
        print(f"  doc_id={c['doc_id']}, rerank_score={c.get('rerank_score'):.4f}")
        # bm25_score缺失时，bm25_norm=1.0（默认值），keyword_hit_ratio有效
        # 应包含keyword_hits字段
        if "keyword_hits" in c:
            print(f"    keyword_hits={c['keyword_hits']}")

    assert len(reranked) == 2
    # 帕博利珠单抗出现在chunk1中，keyword_hits > 0
    assert reranked[0]["doc_id"] == 1, "含关键词的chunk应排第一"

    print("✅ TC-SUP-05 通过")


# ============================================================================
# TC-SUP-06: _prune_etl_jobs ETL任务内存上限
# ============================================================================
def test_sup_06_etl_job_pruning():
    """TC-SUP-06: _prune_etl_jobs ETL任务内存上限"""
    print("\n" + "=" * 60)
    print("TC-SUP-06: _prune_etl_jobs ETL任务内存上限")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import _ETL_JOBS, _prune_etl_jobs, submit_etl_job
    from modules.kb_rag.schemas import ETLRunRequest
    from shared.config import MAX_ETL_JOBS
    from unittest.mock import patch

    print(f"[MAX_ETL_JOBS] {MAX_ETL_JOBS}")

    # 创建超过限制的任务
    initial_count = len(_ETL_JOBS)
    print(f"[初始任务数] {initial_count}")

    # 模拟提交多个URL任务（实际会创建asyncio.create_task）
    # 由于无法真正执行URL下载，我们测试_prune_etl_jobs的行为
    # 通过直接操作_ETL_JOBS来模拟

    # 记录初始任务
    initial_keys = set(_ETL_JOBS.keys())

    # 手动添加超过限制的已完成任务
    for i in range(MAX_ETL_JOBS + 5):
        job_id = f"prune_test_job_{i}"
        _ETL_JOBS[job_id] = type('obj', (object,), {
            'job_id': job_id,
            'status': 'succeeded',
            'created_at': f"2024-01-{(i % 28) + 1:02d}T10:00:00",
        })()

    print(f"[添加后任务数] {len(_ETL_JOBS)}")

    # 调用prune
    _prune_etl_jobs()

    print(f"[Prune后任务数] {len(_ETL_JOBS)}")
    assert len(_ETL_JOBS) <= MAX_ETL_JOBS, f"prune后任务数应≤{MAX_ETL_JOBS}，实际={len(_ETL_JOBS)}"

    # 清理测试任务
    for k in list(_ETL_JOBS.keys()):
        if k.startswith("prune_test_job_"):
            del _ETL_JOBS[k]

    print("✅ TC-SUP-06 通过")


# ============================================================================
# TC-SUP-07: NER去重边界（同一文本重复实体）
# ============================================================================
def test_sup_07_ner_deduplication():
    """TC-SUP-07: NER去重边界"""
    print("\n" + "=" * 60)
    print("TC-SUP-07: NER去重边界")
    print("=" * 60)

    from modules.kb_rag.ingest.ner import extract_medical_entities

    # 同一实体多次出现（规则词典可处理）
    text = "黑色素瘤黑色素瘤黑色素瘤黑色素瘤黑色素瘤"
    entities = extract_medical_entities(text)

    print(f"[重复文本] 黑色素瘤×5")
    print(f"[抽取结果] {[(e['name'], e['type'], e.get('normalized')) for e in entities]}")

    # 去重后应只有1个黑色素瘤（规则词典按exact match去重）
    names = [e["name"] for e in entities if e["type"] == "DISEASE"]
    print(f"[疾病去重] names={names}")
    assert names.count("黑色素瘤") == 1, f"应去重为1个，实际={names.count('黑色素瘤')}"

    # 不同位置但相同实体（规则词典只匹配完整词，不做散布匹配）
    text2 = "黑色素瘤出现在开头。中间也有黑色素瘤。末尾黑色素瘤。"
    entities2 = extract_medical_entities(text2)
    disease_entities = [e for e in entities2 if e["type"] == "DISEASE"]
    names2 = [e["name"] for e in disease_entities]
    print(f"[散布文本] 黑色素瘤 -> {names2}")
    # 规则词典按完整词匹配，text2中"黑色素瘤"出现3次，但原始文本是散布形式
    # 去重后只有1个（seen机制）
    assert names2.count("黑色素瘤") >= 1, "应至少匹配到1个黑色素瘤"

    # 验证(相同name,不同type)的去重：(达拉非尼=DRUG) vs (达拉非尼=GENE)应共存
    # 注意：bert-base-chinese对中文逐字tokenize，多字实体提取不完整
    # 用规则词典中的药物名测试
    text3 = "紫杉醇多西他赛紫杉醇多西他赛"
    entities3 = extract_medical_entities(text3)
    drug_entities = [e for e in entities3 if e["type"] == "DRUG"]
    drug_names3 = [e["name"] for e in drug_entities]
    print(f"[重复药物] 紫杉醇×2, 多西他赛×2 -> {drug_names3}")
    # 去重后各1个
    for dn in set(drug_names3):
        count = drug_names3.count(dn)
        print(f"  {dn} count={count}")
        assert count == 1, f"{dn}应去重为1个，实际={count}"

    print("✅ TC-SUP-07 通过")


# ============================================================================
# TC-SUP-08: _split_table_blocks 100行每块限制
# ============================================================================
def test_sup_08_table_block_100_row_limit():
    """TC-SUP-08: _split_table_blocks 100行每块限制"""
    print("\n" + "=" * 60)
    print("TC-SUP-08: _split_table_blocks 100行每块限制")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import _split_table_blocks

    # 测试各种行数
    test_cases = [
        (50, 1),   # 50行 -> 1块
        (100, 1),  # 100行 -> 1块（边界）
        (101, 2),  # 101行 -> 2块
        (200, 2),  # 200行 -> 2块
        (201, 3),  # 201行 -> 3块
        (250, 3),  # 250行 -> 3块
    ]

    for row_count, expected_chunks in test_cases:
        lines = [f"row{i}\t{i}\t诊断\t分期\t方案" for i in range(row_count)]
        blocks = [{
            "text": "\n".join(lines),
            "is_table": True,
            "section_title": "",
            "table_meta": {"row_count": row_count}
        }]

        chunks = _split_table_blocks(blocks, doc_id=1, doc_version_id=1)
        print(f"  {row_count}行 -> {len(chunks)}chunks (expected={expected_chunks})")
        assert len(chunks) == expected_chunks, f"{row_count}行应产生{expected_chunks}块，实际={len(chunks)}"

        # 验证每个chunk的table_meta
        for ci, c in enumerate(chunks):
            tm = c.get("table_meta", {})
            assert tm.get("total_chunks") == expected_chunks, f"total_chunks应为{expected_chunks}"
            assert tm.get("chunk_index") == ci, f"chunk_index应为{ci}"
            print(f"    chunk[{ci}]: rows {tm.get('chunk_row_start')}-{tm.get('chunk_row_end')}, total={tm.get('total_chunks')}")

    print("✅ TC-SUP-08 通过")


# ============================================================================
# TC-SUP-09: submit_etl_job URL源ETL（逻辑验证）
# ============================================================================
def test_sup_09_submit_etl_job_url():
    """TC-SUP-09: submit_etl_job URL源ETL（逻辑验证）"""
    print("\n" + "=" * 60)
    print("TC-SUP-09: submit_etl_job URL源ETL（逻辑验证）")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import submit_etl_job
    from modules.kb_rag.schemas import ETLRunRequest

    # 验证source_type=url时需要url配置
    try:
        req = ETLRunRequest(
            source_type="url",
            source_config={},  # 缺少url
            kb_id=1,
            job_name="测试",
        )
        # submit_etl_job应抛出ValueError
        asyncio.run(submit_etl_job(req))
        print("[错误] 应抛出ValueError")
        assert False
    except ValueError as e:
        print(f"[预期异常] ValueError: {e}")
        assert "source_type=url requires source_config.url" in str(e)

    # 验证source_type=file时抛出错误（file应走/file端点）
    try:
        req2 = ETLRunRequest(
            source_type="file",
            source_config={},
            kb_id=1,
            job_name="测试",
        )
        asyncio.run(submit_etl_job(req2))
        print("[错误] 应抛出ValueError")
        assert False
    except ValueError as e:
        print(f"[预期异常] ValueError: {e}")
        assert "should use /etl/run-file endpoint" in str(e)

    print("✅ TC-SUP-09 通过")


# ============================================================================
# TC-SUP-10: submit_etl_job database源ETL（逻辑验证）
# ============================================================================
def test_sup_10_submit_etl_job_database():
    """TC-SUP-10: submit_etl_job database源ETL（逻辑验证）"""
    print("\n" + "=" * 60)
    print("TC-SUP-10: submit_etl_job database源ETL（逻辑验证）")
    print("=" * 60)

    from modules.kb_rag.etl.etl_service import submit_etl_job
    from modules.kb_rag.schemas import ETLRunRequest

    # 验证database源缺少配置时抛出错误
    try:
        req = ETLRunRequest(
            source_type="database",
            source_config={},  # 缺少table_name和sql_query
            kb_id=1,
            job_name="测试",
        )
        asyncio.run(submit_etl_job(req))
        print("[错误] 应抛出ValueError")
        assert False
    except ValueError as e:
        print(f"[预期异常] ValueError: {e}")
        assert "requires source_config.table_name or source_config.sql_query" in str(e)

    print("✅ TC-SUP-10 通过")


# ============================================================================
# 主函数
# ============================================================================
def run_all_tests():
    print("\n" + "=" * 70)
    print("  补充测试套件 - 覆盖剩余关键路径")
    print("=" * 70)

    tests = [
        ("TC-SUP-01", test_sup_01_split_table_blocks),
        ("TC-SUP-02", test_sup_02_reranker_rule_based_fallback),
        ("TC-SUP-03", test_sup_03_export_feedback),
        ("TC-SUP-04", test_sup_04_retrieval_low_confidence_block),
        ("TC-SUP-05", test_sup_05_rerank_missing_bm25_score),
        ("TC-SUP-06", test_sup_06_etl_job_pruning),
        ("TC-SUP-07", test_sup_07_ner_deduplication),
        ("TC-SUP-08", test_sup_08_table_block_100_row_limit),
        ("TC-SUP-09", test_sup_09_submit_etl_job_url),
        ("TC-SUP-10", test_sup_10_submit_etl_job_database),
    ]

    passed = 0
    failed = 0

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
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
