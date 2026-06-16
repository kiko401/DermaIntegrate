# TODO.md

> 当前状态快照。每轮结束时更新。只保留当前有用信息，不保留长历史。
> 最后更新：2026-06-16（vite.config.js 补 /pacs-static 代理，缩略图加载修复）

---

## 当前状态

- 分支：`feat/multidb-empi-rebuild`
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

## 当前主线：README 对齐正式版重构（多库 / 多源 / 真原图）
当前阶段目标已经从“继续完善单 schema 原型”切换为：
**按 README 的正式目标重构系统底座，逐步推进到真实多源数据库 + 统一患者视图 + 基于已有影像发起 AI 分析的架构。**

## 原型阶段已完成成果（可回退参考）
以下内容已完成，用于验证多源聚合方向，但不是最终正式架构：
- [x] 单 schema + 分型表原型（`ext_his_records` / `ext_lis_results` / `ext_pacs_records`）
- [x] `clinical-view` 聚合接口原型
- [x] Integration 页面统一临床视图工作台
- [x] TaskDetail “重新分析”跳转到对应患者
- [x] 单 schema 下的多源患者聚合、前端展示、基础导航链路已打通

说明：
当前 GitHub 上这版代码保留为**原型阶段成果**，可作为回退和参考，不再继续作为长期正式架构深挖。

## README 对齐正式重构：第一阶段（数据底座）
目标：
从当前单 schema 原型过渡到正式多库 / 多 schema 架构，为真实多源接入与基于已有影像发起 AI 分析做准备。

第一阶段范围：
- [x] 新建 `app_db`（pool + schema + seed 完成，验证通过）
- [x] 新建 `his_db`（pool + schema + seed 完成，验证通过）
- [x] 新建 `lis_db`（pool + schema + seed 完成，验证通过）
- [x] 新建 `pacs_db`（pool + schema + seed 完成，验证通过）
- [x] 新增多 pool 连接配置（app / his / lis / pacs 全部完成）
- [x] db/index.js 导出多 pool，向下兼容旧代码
- [x] 新增 schema/app.sql / his.sql / lis.sql / pacs.sql
- [x] 拆分 seed：seed/app.js / his.js / lis.js / pacs.js / index.js（含建表前置）
- [x] app.js 启动时多库建表检查（MultiDB Migration OK 已验证）
- [x] 更新 .env.example 补充多库变量

## README 对齐正式重构：后续阶段
- [x] 将 `clinical-view` 从单 schema 原型查询切换为真实多库聚合查询（含清理收口：重复 require 合并、旧注释清理、`getSourcesByPatientId` 修复）
- [x] `listExternalSources` 已从 `mock_external_patients` 切换为从 `his_db` / `lis_db` / `pacs_db` 三库聚合，返回结构不变
- [x] 准备真实 PACS 图片资源路径与静态访问方式（`/pacs-static` 路由已挂载，`queryPacs` 已返回可访问 URL）
- [ ] 改造 AI 分析入口：从“手工创建数据 + 手工上传图”逐步过渡到“基于已有患者 / 就诊 / 原图发起分析”
- [ ] 将手工录入路径从主入口降级为补录 / fallback 入口
- [ ] 后续再评估 FHIR R4 风格归一化层

---

## 原型阶段剩余优化（延后）

以下事项仍然有效，但已不再是当前正式重构主线：

- [x] 原图资源准备完成后，再接入 `ImageCompare` 左侧原图（Integration.vue PACS Tab 缩略图已接入真实路径）
- [ ] 患者详情页展示 `clinical-view`：目前只在 Integration 页可查，可考虑在 PatientList 患者卡片展开区补充“外部数据”入口
- [ ] 其他原型阶段 UI 小优化按需处理

## 次级任务（延后）

- [ ] **ImageCompare 原图方案**：Integration.vue PACS Tab 已接缩略图；TaskDetail ImageCompare 左侧原图（`image_url`）尚未接入
- [x] **TaskDetail「重新分析」**：改为跳转到对应患者（`task.patient_id` 接口已返回）

---

## 后续技术扩展

- [ ] FHIR R4 风格归一化层
- [ ] 构建 FHIR 风格资源 + EMPI + AI 结果的统一临床聚合接口
- [ ] Docker Compose 部署：Nginx SSE 配置 + 多 schema / 多库编排
- [ ] Redis：出现真实使用场景时再引入

---

## 已知问题 / 风险

| ID | 问题 | 状态 |
|----|------|------|
| KI-001 | `EventSource` 无法发送自定义请求头，SSE 鉴权依赖 cookie / 代理行为 | 🟡 活跃风险 |
| KI-002 | `test/index.html` 无 cookie 机制，接口全 401 | 🟡 非阻塞，已知 |
| KI-003 | `ImageCompare` 左侧原图仍为占位，真实原图资源和访问路径尚未正式落地 | ✅ Integration PACS Tab 缩略图已接真实路径；TaskDetail ImageCompare 左侧原图待接入 |
| KI-004 | 当前 EMPI 和外部来源接入已完成原型验证，但整体仍依赖单 schema / mock 过渡结构，尚未进入正式多库架构 | 🟡 当前主线正在重构 |
| KI-007 | `SSEResultEvent.status` 无枚举约束，AI 侧返回非预期值会导致前端判断失效 | 🟡 非阻塞，建议协作者加 `Literal` 约束 |