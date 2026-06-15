# TODO.md

> 当前状态快照。每轮结束时更新。只保留当前有用信息，不保留长历史。
> 最后更新：2026-06-15

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
| `routes/patients.js` | 患者 CRUD | ✅ |
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
| `empi_index` | 外部系统 ID → 内部患者 ID 映射（当前仍是原型级） |
| `mock_external_patients` | HIS/LIS/PACS mock 数据，seed 预置 6 条 |

> `result_snapshot` 列：`app.js` 启动时自动执行 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，无需手动迁移。

### 前端（`frontend/src/`）

| 路由 | 组件 | 状态 |
|------|------|------|
| `/login` | `LoginView.vue` | ✅ |
| `/dashboard` | `Dashboard.vue` | ✅ 已接真实数据（患者数 / 任务统计 / 最近动态） |
| `/patients` | `PatientList.vue` | ✅ 完整（患者卡片 + 就诊工作台 + 发起分析） |
| `/integration` | `Integration.vue` | ✅ EMPI 展示页（当前仍偏 mock 方案） |
| `/tasks` | `Tasks.vue` | ✅ 真实接口，支持 pending 任务静默轮询刷新 |
| `/tasks/:taskId` | `TaskDetail.vue` | ✅ 左右布局，支持 live SSE + 历史快照 |

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

## 下一阶段主线：EMPI + 多源异构接入基础

**当前主优先级不是继续做前端体验小修小补，而是：**

把项目从「手工录入驱动的 AI 原型流程」推进到「多源数据集成驱动的临床工作流基础」。
本阶段优先完成设计与最小可行实现（MVP），不追求一次性做完整 FHIR 体系。


### 阶段目标

- 跨系统患者身份映射
- 本地模拟 HIS / LIS / PACS 风格数据源
- 统一患者临床视图
- 外部原图来源设计
- 后续 FHIR 风格归一化的基础路径

### 计划任务

- [ ] 设计多 schema 数据库布局（`app_db` / `his_db` / `lis_db` / `pacs_db`）
  - 云上优先采用「一个 MySQL 实例 + 多个 schema」的轻量方案
- [ ] 将 `empi_index` 从原型映射表升级为更清晰的跨系统身份映射表
- [ ] 用分离的来源库 / 来源表替代当前单表 `mock_external_patients` 方案
- [ ] 新增后端聚合 service，生成统一患者临床视图
- [ ] 定义统一接口（如 `/api/patients/:id/clinical-view`），返回整合后的患者全景数据
- [ ] 明确原图来源策略：原图来自外部影像记录 / PACS 风格数据源，热力图仍由 AI 推理输出
- [ ] 逐步改造分析发起流程：从「手工创建数据再分析」过渡到「选择已有患者 / 就诊 / 原图后发起分析」

---

## 次级任务（延后）

- [ ] **ImageCompare 原图方案**：左侧固定占位，等原图来源策略落地后处理
- [ ] **TaskDetail「重新分析」**：改为跳转到对应患者（当前泛跳 `/patients`，`task.patient_id` 接口已返回）
- [ ] Integration 页面交互体验补充（等 EMPI 接入真实化后再做）

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
| KI-004 | 当前 EMPI 和外部来源接入仍偏原型级，整体结构依赖 mock | 🔴 下一阶段核心问题 |
| KI-007 | `SSEResultEvent.status` 无枚举约束，AI 侧返回非预期值会导致前端判断失效 | 🟡 非阻塞，建议协作者加 `Literal` 约束 |
