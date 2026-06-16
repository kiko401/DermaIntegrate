# TODO.md

> 当前状态快照。每轮结束时更新。只保留当前有用信息，不保留长历史。
> 最后更新：2026-06-16（TaskDetail 跳转优化完成）

---

## 当前状态

- 分支：`feat/app/sse-integration`
- 默认工作范围：`frontend/` + `backend-app/`
- AI 推理域 `backend-ai/`：同属本仓库，协作者负责，默认不修改、不扫描

---

## 当前产品状态

当前系统已完成 AI 辅助诊断的原型主流程：

1. 医生手动创建患者
2. 医生手动填写就诊 / 临床信息
3. 医生手动上传原图
4. 医生发起 AI 分析
5. AI 返回热力图和结构化诊断结果
6. 系统展示实时 / 历史诊断结果

这条链路作为原型阶段成立，但**不是最终目标形态**。

最终目标：

1. 患者 / 就诊 / 检验 / 影像数据主要来自外部系统
2. 通过 `empi_index` 做跨系统患者身份映射
3. 聚合 HIS / LIS / PACS 风格数据，形成统一患者视图
4. 医生基于已有数据发起分析，而非从零手工造数据
5. 原图主要来自外部影像记录
6. 热力图和结构化诊断结果由 AI 推理生成，再回挂到整合后的患者上下文

---

## 已完成模块

### 后端（`backend-app/src/`）

| 路由文件 | 接口 | 状态 |
|---------|------|------|
| `routes/health.js` | `GET /api/health/ai` | ✅ |
| `routes/auth.js` | `POST /api/auth/login`（httpOnly cookie）/ `POST /logout` / `GET /me` | ✅ |
| `routes/patients.js` | 患者 CRUD + `GET /api/patients/:id/clinical-view` | ✅ |
| `routes/visits.js` | 就诊记录 CRUD（mergeParams: true） | ✅ |
| `routes/upload.js` | `POST /api/tasks/upload` / `GET /api/tasks`（列表） | ✅ |
| `routes/stream.js` | `GET /api/tasks/:id/stream`（SSE 代理）/ `GET /api/tasks/:id/result`（历史快照）/ `GET /api/tasks/:id`（详情） | ✅ |
| `routes/static.js` | `/ai-static/*` 代理到 AI 推理域 | ✅ |
| `routes/empi.js` | EMPI 匹配 + 外部数据源列表（当前仍偏 mock） | ✅ |

### 数据库（MySQL / `derma_integrate` schema）

| 表 | 说明 |
|----|------|
| `doctors` | seed 预置：username=doctor / password=demo123 |
| `patients` | 患者主表 |
| `visits` | 就诊记录，FK → patients / doctors |
| `ai_tasks` | 含 `result_snapshot JSON` 列（启动时自动迁移） |
| `empi_index` | 外部系统 ID → 内部患者 ID 映射 |
| `mock_external_patients` | HIS/LIS/PACS mock 身份数据，seed 预置 6 条（EMPI 匹配入口） |
| `ext_his_records` | HIS 风格就诊记录（分型表，seed 3条） |
| `ext_lis_results` | LIS 风格检验结果（分型表，seed 4条） |
| `ext_pacs_records` | PACS 风格影像记录，含 image_url / thumbnail_url（分型表，seed 2条） |

> 新来源表（`ext_*`）：`app.js` 启动时自动 `CREATE TABLE IF NOT EXISTS`，无需手动建表。`result_snapshot` 同理。

### 前端（`frontend/src/`）

| 路由 | 组件 | 状态 |
|------|------|------|
| `/login` | `LoginView.vue` | ✅ |
| `/dashboard` | `Dashboard.vue` | ✅ 已接真实数据（患者数 / 任务统计 / 最近动态） |
| `/patients` | `PatientList.vue` | ✅ 完整（患者卡片 + 就诊工作台 + 发起分析）；支持 `?patient_id=` query 自动展开患者 |
| `/integration` | `Integration.vue` | ✅ 双栏工作台布局，消费 clinical-view 接口，含患者摘要卡 + HIS/LIS/PACS/AI任务 Tabs |
| `/tasks` | `Tasks.vue` | ✅ 真实接口，支持 pending 任务静默轮询刷新 |
| `/tasks/:taskId` | `TaskDetail.vue` | ✅ 左右布局，支持 live SSE + 历史快照；"重新分析"跳转已修复 |

| 组件 | 状态 |
|------|------|
| `DiagnosisDialog.vue` | ✅ live / history 双模式 |
| `ImageCompare.vue` | ✅ clip-path 滑动对比，左侧原图目前为占位 |
| `useSSE.js` | ✅ |

### 已废弃 / 已变更

- `VisitDetail.vue`：已删除，逻辑并入 `PatientList.vue`
- JWT localStorage → httpOnly cookie（已完成）
- `test/index.html`：已失效（无 cookie 机制，接口全 401），非阻塞

---

## 当前主线：EMPI + 多源异构接入基础（MVP 后端已完成）

后端 MVP 已落地，外部分型表已建，统一临床视图接口已上线并验证。

### 已完成（2026-06-16）

- [x] 设计：单 schema + 分型表，保留升级到多 schema 的路径
- [x] 新增 `ext_his_records` / `ext_lis_results` / `ext_pacs_records` 三张分型表（schema + 启动迁移）
- [x] seed：his 3条 / lis 4条 / pacs 2条，覆盖患者 901/902/903
- [x] `empiService.getClinicalView(patientId)`：聚合 patient + empi_sources + his + lis + pacs + ai_tasks
- [x] `GET /api/patients/:patientId/clinical-view`：curl 验证通过

### 已完成（2026-06-16）

- [x] 前端：`Integration.vue` 重构为双栏工作台布局
- [x] 左栏：汇总行 + 外部来源表格，点击"查看"切换右侧
- [x] 右栏：患者摘要卡 + Tabs（概览 / HIS / LIS / PACS / AI任务）
- [x] PACS Tab：缩略图预览 + image_url 文本展示
- [x] 左右栏独立滚动，右侧无选中时显示占位提示
- [x] KI-004 已解决

### 前端待做（本阶段剩余）

- [ ] **ImageCompare 原图接入**：`ext_pacs_records.image_url` 已有真实数据，待将 PACS 影像 URL 接入 `ImageCompare.vue` 左侧原图（当前为占位）
- [x] **TaskDetail「重新分析」跳转**：跳转到 `task.patient_id` 对应的具体患者页并自动展开该患者
- [ ] **患者详情页展示 clinical-view**：目前只在 Integration 页可查，可考虑在 PatientList 患者卡片展开区补充一个"外部数据"入口（延后，视需求而定）

---

## 次级任务（延后）

- [ ] **ImageCompare 原图方案**：原图来源已有 `ext_pacs_records.image_url`，待前端接入后处理
- [x] **TaskDetail「重新分析」**：改为跳转到对应患者（`task.patient_id` 接口已返回）

---

## 后续技术扩展

- [ ] FHIR R4 风格归一化层
- [ ] 构建 FHIR 风格资源 + EMPI + AI 结果的统一临床聚合接口
- [ ] Docker Compose 部署：Nginx SSE 配置 + 多 schema 数据库编排
- [ ] Redis：出现真实使用场景时再引入

---

## 已知问题 / 风险

| ID | 问题 | 状态 |
|----|------|------|
| KI-001 | `EventSource` 无法发送自定义请求头，SSE 鉴权依赖 cookie / 代理行为 | 🟡 活跃风险 |
| KI-002 | `test/index.html` 无 cookie 机制，接口全 401 | 🟡 非阻塞，已知 |
| KI-003 | `ImageCompare` 左侧原图为占位，原图来源策略尚未落地 | 🟡 已知，延后处理 |
| KI-004 | 当前 EMPI 和外部来源接入仍偏原型级，整体结构依赖 mock | 🟢 后端 MVP 完成，前端展示待做 |
| KI-007 | `SSEResultEvent.status` 无枚举约束，AI 侧返回非预期值会导致前端判断失效 | 🟡 非阻塞，建议协作者加 `Literal` 约束 |
