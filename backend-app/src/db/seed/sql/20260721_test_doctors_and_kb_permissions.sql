-- DermaIntegrate 知识库权限测试数据
-- 日期：2026-07-21
-- 作用：
--   1. 创建 6 个测试医生账号
--   2. 创建每位医生的个人知识库
--   3. 将现有 3 个 TEST 科室知识库分配给模拟负责人
--   4. 配置 viewer / uploader / manager 交叉权限
--
-- 特性：
--   - 可重复执行
--   - 不依赖固定自增 ID，全部通过 username / kb_code / name 解析
--   - 不创建 departments 表，遵循当前“负责人医生 + 成员授权”实现

USE derma_app;

START TRANSACTION;

-- 所有测试账号统一密码：Test@123456
-- bcrypt cost=12
SET @test_password_hash = '$2b$12$gY/rlYthMB72SnVkd1BJnOB2df.5nzuok6XHc2Ztkn3AD1EqC/5rK';

INSERT INTO doctors (name, username, password_hash, role, is_active, deleted_at)
VALUES
  ('张晨', 'derma_director',  @test_password_hash, 'doctor', 1, NULL),
  ('李雯', 'derma_attending', @test_password_hash, 'doctor', 1, NULL),
  ('王凯', 'derma_resident',  @test_password_hash, 'doctor', 1, NULL),
  ('陈静', 'path_director',   @test_password_hash, 'doctor', 1, NULL),
  ('赵敏', 'path_doctor',     @test_password_hash, 'doctor', 1, NULL),
  ('周航', 'mdt_doctor',      @test_password_hash, 'doctor', 1, NULL)
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  password_hash = VALUES(password_hash),
  role = 'doctor',
  is_active = 1,
  deleted_at = NULL;

SELECT id INTO @admin_id
FROM doctors
WHERE username = 'admin' AND deleted_at IS NULL
LIMIT 1;

SELECT id INTO @demo_doctor_id
FROM doctors
WHERE username = 'doctor' AND deleted_at IS NULL
LIMIT 1;

SELECT id INTO @zhang_id FROM doctors WHERE username = 'derma_director' LIMIT 1;
SELECT id INTO @li_id    FROM doctors WHERE username = 'derma_attending' LIMIT 1;
SELECT id INTO @wang_id  FROM doctors WHERE username = 'derma_resident' LIMIT 1;
SELECT id INTO @chen_id  FROM doctors WHERE username = 'path_director' LIMIT 1;
SELECT id INTO @zhao_id  FROM doctors WHERE username = 'path_doctor' LIMIT 1;
SELECT id INTO @zhou_id  FROM doctors WHERE username = 'mdt_doctor' LIMIT 1;

-- 当前模型没有 departments 表：
-- department 库的 scope_owner_id 保存该知识库的负责人 doctor_id。
UPDATE rag_knowledge_bases
SET scope_type = 'department',
    scope_owner_id = @zhang_id,
    manager_doctor_id = @zhang_id,
    status = 'active',
    deleted_at = NULL,
    description = '测试用皮肤科门诊知识库：负责人张晨；用于门诊分诊、标准问答及权限隔离测试。'
WHERE name = 'TEST-皮肤科门诊问答库';

UPDATE rag_knowledge_bases
SET scope_type = 'department',
    scope_owner_id = @chen_id,
    manager_doctor_id = @chen_id,
    status = 'active',
    deleted_at = NULL,
    description = '测试用病理协作知识库：负责人陈静；用于病理送检、报告回传及跨科室授权测试。'
WHERE name = 'TEST-病理协作报告库';

UPDATE rag_knowledge_bases
SET scope_type = 'department',
    scope_owner_id = @zhou_id,
    manager_doctor_id = @zhou_id,
    status = 'active',
    deleted_at = NULL,
    description = '测试用MDT会诊知识库：负责人周航；用于多学科会诊和多角色协作测试。'
WHERE name = 'TEST-MDT会诊摘要库';

SELECT id INTO @skin_kb_id
FROM rag_knowledge_bases
WHERE name = 'TEST-皮肤科门诊问答库' AND deleted_at IS NULL
LIMIT 1;

SELECT id INTO @path_kb_id
FROM rag_knowledge_bases
WHERE name = 'TEST-病理协作报告库' AND deleted_at IS NULL
LIMIT 1;

SELECT id INTO @mdt_kb_id
FROM rag_knowledge_bases
WHERE name = 'TEST-MDT会诊摘要库' AND deleted_at IS NULL
LIMIT 1;

-- 个人知识库使用固定 kb_code 保证重复执行时不会重复创建。
INSERT INTO rag_knowledge_bases
  (kb_code, name, description, scope_type, scope_owner_id,
   manager_doctor_id, default_model, retrieval_config, status, deleted_at)
VALUES
  ('kb_test_personal_zhang',
   'TEST-张晨个人诊疗经验库',
   '张晨个人知识库：皮肤肿瘤门诊管理、诊疗路径和科室治理经验。',
   'personal', @zhang_id, @zhang_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 6, 'threshold', 0.32, 'rerank', TRUE, 'scene', 'personal-clinical'),
   'active', NULL),
  ('kb_test_personal_li',
   'TEST-李雯门诊学习笔记库',
   '李雯个人知识库：门诊问诊、患者沟通和常见皮损随访笔记。',
   'personal', @li_id, @li_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 5, 'threshold', 0.30, 'rerank', TRUE, 'scene', 'personal-learning'),
   'active', NULL),
  ('kb_test_personal_wang',
   'TEST-王凯住院病例复盘库',
   '王凯个人知识库：住院病例复盘、风险提示和交接班记录模板。',
   'personal', @wang_id, @wang_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 5, 'threshold', 0.34, 'rerank', FALSE, 'scene', 'personal-case-review'),
   'active', NULL),
  ('kb_test_personal_chen',
   'TEST-陈静病理文献摘录库',
   '陈静个人知识库：皮肤病理术语、报告字段和文献摘录。',
   'personal', @chen_id, @chen_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 7, 'threshold', 0.28, 'rerank', TRUE, 'scene', 'personal-pathology'),
   'active', NULL),
  ('kb_test_personal_zhao',
   'TEST-赵敏病理报告模板库',
   '赵敏个人知识库：病理报告模板、质控清单和临床沟通记录。',
   'personal', @zhao_id, @zhao_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 4, 'threshold', 0.31, 'rerank', FALSE, 'scene', 'personal-reporting'),
   'active', NULL),
  ('kb_test_personal_zhou',
   'TEST-周航MDT研究资料库',
   '周航个人知识库：MDT会诊准备、治疗讨论和研究问题记录。',
   'personal', @zhou_id, @zhou_id, 'BAAI/bge-small-zh-v1.5',
   JSON_OBJECT('top_k', 6, 'threshold', 0.29, 'rerank', TRUE, 'scene', 'personal-mdt'),
   'active', NULL)
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  description = VALUES(description),
  scope_type = 'personal',
  scope_owner_id = VALUES(scope_owner_id),
  manager_doctor_id = VALUES(manager_doctor_id),
  default_model = VALUES(default_model),
  retrieval_config = VALUES(retrieval_config),
  status = 'active',
  deleted_at = NULL;

-- 只重建本批次 6 位医生在 3 个目标科室库中的授权，
-- 不影响管理员、演示医生或其他后续创建账号的授权记录。
DELETE m
FROM rag_knowledge_base_members m
JOIN doctors d ON d.id = m.doctor_id
WHERE d.username IN (
  'derma_director',
  'derma_attending',
  'derma_resident',
  'path_director',
  'path_doctor',
  'mdt_doctor'
)
AND m.kb_id IN (@skin_kb_id, @path_kb_id, @mdt_kb_id);

-- 皮肤科门诊组：
-- 张晨 manager；李雯 uploader；王凯/周航 viewer。
INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by)
VALUES
  (@skin_kb_id, @zhang_id, 'manager',  @admin_id),
  (@skin_kb_id, @li_id,    'uploader', @admin_id),
  (@skin_kb_id, @wang_id,  'viewer',   @admin_id),
  (@skin_kb_id, @zhou_id,  'viewer',   @admin_id)
ON DUPLICATE KEY UPDATE
  role = VALUES(role),
  granted_by = VALUES(granted_by);

-- 病理协作组：
-- 陈静 manager；赵敏 uploader；张晨/李雯 viewer。
INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by)
VALUES
  (@path_kb_id, @chen_id, 'manager',  @admin_id),
  (@path_kb_id, @zhao_id, 'uploader', @admin_id),
  (@path_kb_id, @zhang_id, 'viewer',  @admin_id),
  (@path_kb_id, @li_id,    'viewer',  @admin_id)
ON DUPLICATE KEY UPDATE
  role = VALUES(role),
  granted_by = VALUES(granted_by);

-- MDT 会诊组：
-- 周航/张晨 manager；陈静 uploader；李雯/王凯 viewer；赵敏不授权。
INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by)
VALUES
  (@mdt_kb_id, @zhou_id,  'manager',  @admin_id),
  (@mdt_kb_id, @zhang_id, 'manager',  @admin_id),
  (@mdt_kb_id, @chen_id,  'uploader', @admin_id),
  (@mdt_kb_id, @li_id,    'viewer',   @admin_id),
  (@mdt_kb_id, @wang_id,  'viewer',   @admin_id)
ON DUPLICATE KEY UPDATE
  role = VALUES(role),
  granted_by = VALUES(granted_by);

COMMIT;

-- 执行后快速核验
SELECT id, name, username, role, is_active
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

SELECT
  kb.id,
  kb.name,
  kb.scope_type,
  owner.name AS owner_name,
  manager.name AS manager_name,
  COUNT(m.id) AS member_count
FROM rag_knowledge_bases kb
LEFT JOIN doctors owner ON owner.id = kb.scope_owner_id
LEFT JOIN doctors manager ON manager.id = kb.manager_doctor_id
LEFT JOIN rag_knowledge_base_members m ON m.kb_id = kb.id
WHERE kb.deleted_at IS NULL
  AND (
    LEFT(kb.kb_code, 17) = 'kb_test_personal_'
    OR kb.name IN (
      'TEST-皮肤科门诊问答库',
      'TEST-病理协作报告库',
      'TEST-MDT会诊摘要库'
    )
  )
GROUP BY kb.id, kb.name, kb.scope_type, owner.name, manager.name
ORDER BY kb.id;
