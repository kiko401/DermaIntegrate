-- DermaIntegrate 知识库权限测试数据回滚
-- 采用软删除，避免破坏测试期间可能产生的审计、会话和引用记录。

USE derma_app;

START TRANSACTION;

SELECT id INTO @admin_id
FROM doctors
WHERE username = 'admin' AND deleted_at IS NULL
LIMIT 1;

SELECT id INTO @demo_doctor_id
FROM doctors
WHERE username = 'doctor' AND deleted_at IS NULL
LIMIT 1;

-- 隐藏本批次创建的个人库及其文档。
UPDATE rag_documents d
JOIN rag_knowledge_bases kb ON kb.id = d.kb_id
SET d.status = 'deleted',
    d.deleted_at = COALESCE(d.deleted_at, NOW())
WHERE LEFT(kb.kb_code, 17) = 'kb_test_personal_'
  AND d.deleted_at IS NULL;

DELETE m
FROM rag_knowledge_base_members m
JOIN doctors d ON d.id = m.doctor_id
JOIN rag_knowledge_bases kb ON kb.id = m.kb_id
WHERE d.username IN (
  'derma_director',
  'derma_attending',
  'derma_resident',
  'path_director',
  'path_doctor',
  'mdt_doctor'
)
AND kb.name IN (
  'TEST-皮肤科门诊问答库',
  'TEST-病理协作报告库',
  'TEST-MDT会诊摘要库'
);

UPDATE rag_knowledge_bases
SET status = 'archived',
    deleted_at = COALESCE(deleted_at, NOW())
WHERE LEFT(kb_code, 17) = 'kb_test_personal_';

-- 恢复执行初始化 SQL 前的 3 个科室库负责人。
UPDATE rag_knowledge_bases
SET scope_owner_id = @admin_id,
    manager_doctor_id = @admin_id
WHERE name IN (
  'TEST-皮肤科门诊问答库',
  'TEST-病理协作报告库'
)
AND deleted_at IS NULL;

UPDATE rag_knowledge_bases
SET scope_owner_id = @demo_doctor_id,
    manager_doctor_id = @demo_doctor_id
WHERE name = 'TEST-MDT会诊摘要库'
  AND deleted_at IS NULL;

UPDATE doctors
SET is_active = 0,
    deleted_at = COALESCE(deleted_at, NOW())
WHERE username IN (
  'derma_director',
  'derma_attending',
  'derma_resident',
  'path_director',
  'path_doctor',
  'mdt_doctor'
);

COMMIT;

SELECT id, name, username, is_active, deleted_at
FROM doctors
WHERE username IN (
  'derma_director',
  'derma_attending',
  'derma_resident',
  'path_director',
  'path_doctor',
  'mdt_doctor'
)
ORDER BY id;
