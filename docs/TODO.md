# TODO.md

> 当前状态快照。每轮结束时更新。只保留当前有用信息，不保留长历史。
> 最后更新：2026-06-17（主线收敛分析完成，按 M1-M4 里程碑重组剩余任务）

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
| `routes/stream.js` | `GET /api/tasks/:id/stream`（SSE 代理）/ `GET /api/tasks/:id/result`（历史快照）/ `GET /api/tasks/:id`（详情，含 pacs_image_url） | ✅ |
| `routes/static.js` | `/ai-static/*` 代理到 AI 推理域 | ✅ |
| `routes/empi.js` | EMPI 匹配 + 外部数据源列表（当前仍偏 mock） | ✅ |
| `routes/pacs_task.js` | `POST /api/tasks/from-pacs`（基于 PACS 记录发起 AI 分析） | ✅ |

### 数据库（MySQL / `derma_integrate` schema）

| 表 | 说明 |
|----|------|
| `doctors` | seed 预置：username=doctor / password=demo123 |
| `patients` | 患者主表 |
| `visits` | 就诊记录，FK → patients / doctors |
| `ai_tasks` | 含 `result_snapshot JSON` + `pacs_record_id VARCHAR(64)` 列（启动时自动迁移） |
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
| `/integration` | `Integration.vue` | ✅ 双栏工作台布局，消费 clinical-view 接口，含患者摘要卡 + HIS/LIS/PACS/AI任务 Tabs；PACS Tab 支持"发起 AI 分析"→ 跳转 TaskDetail |
| `/tasks` | `Tasks.vue` | ✅ 真实接口，支持 pending 任务静默轮询刷新 |
| `/tasks/:taskId` | `TaskDetail.vue` | ✅ 左右布局，支持 live SSE + 历史快照；"重新分析"跳转已修复；左图接入 pacs_image_url（旧任务兼容占位） |

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

## 主线收敛：README 落地最短路径

**核心闭环：** 医生在统一临床视图中选择 PACS 影像，系统自动聚合该患者的 HIS 病历与 LIS 化验数据，作为多模态输入一并发往 AI 推理域，AI 返回可解释结构化报告并实时流式展示。

**当前断点：** HIS/LIS 数据在 clinical-view 可见，但从未进入 AI 任务。这是”数据集成”与”AI 诊断”两条主线之间唯一的断裂口。

---

### M1 — 多模态上下文写入 AI 任务 ✅

**为什么：** README 明确描述 AI 接收「图像 + 病历文本 + 化验数据」三路输入。当前 `POST /api/tasks/from-pacs` 只送图像 URL，clinical-view 已有的 HIS/LIS 数据从未流向推理域。

**完成标志：**
- 从 Integration.vue 发起分析时，HIS 病历摘要 + LIS 化验结构化数据与 pacs_record_id 一并发往 AI ✅
- AI 侧病历 Agent / 化验 Agent 能触发（而非始终 fallback）✅

**依赖前置：** 读取 `docs/api-contract.yaml` 确认上传接口支持的多模态字段；与 backend-ai 协作者对齐接收格式。

**进度：**
- [x] 确认 api-contract.yaml 多模态字段（`clinical_text` / `lab_json`，multipart/form-data）
- [x] 新增 `lis_pathology_reports` 表（对齐 TCGA-SKCM/AJCC 8th 字段：breslow/ulceration/braf/kit 等）
- [x] seed 张伟病理报告（PATH-2021-0318-001，breslow=5.20，braf=V600E突变）
- [x] app.js 启动迁移加入 `lis_pathology_reports` 建表
- [x] `getClinicalView` 返回 `lis_pathology` 字段
- [x] `POST /api/tasks/from-pacs`：HIS → `clinical_text`，lis_pathology → `lab_json`，全链路验证通过
- [x] Integration.vue 无需改动（数据由服务端聚合）

---

### M2 — Docker Compose + Nginx 完整编排

**为什么：** README section 5 将容器化部署列为正式部署方式，`infra/` 目录已在 README 目录结构中标注，section 5.3 仍有 `<!-- TODO: Application Domain: -->` 占位。

**完成标志：**
- `docker-compose up` 能完整拉起 frontend + backend-app + MySQL + backend-ai + Nginx
- SSE 在 Nginx 下无超时断连
- README 5.3 占位符替换为真实命令

**依赖前置：** M1 完成后功能稳定再固化部署配置。

**进度：**
- [ ] 编写 `infra/docker-compose.yml`（含 Nginx SSE 配置）
- [ ] 填写 README section 5.3 应用域部署说明

---

### M3 — README 应用域 TODO 占位符全部填写

**为什么：** README section 3.2 和 5.3 仍有两处 `<!-- TODO: Application Domain: -->` 标记，是未完成的文档承诺。

**完成标志：** README 中无 TODO 占位符；section 3.2 应用域描述与实际实现一致。

**依赖前置：** M1 + M2 完成。

**进度：**
- [ ] 填写 README section 3.2 应用域功能描述
- [ ] 填写 README section 5.3 部署命令

---

### M4 — FHIR R4 归一化层（延后评估）

**为什么：** README 将 FHIR R4 列为数据集成核心机制。当前 clinical-view 输出自定义格式，未符合 FHIR R4 规范。

**完成标志：** `clinical-view` 接口输出符合 FHIR R4 规范的资源结构（Patient / Observation / ImagingStudy）。

**依赖前置：** M1-M3 完成后单独评估工作量。

**进度：**
- [ ] 评估工作量后拆分子任务

---

## 现在不要做

| 事项 | 原因 |
|------|------|
| PatientList.vue 加 PACS 引导 banner | 原型尾巴，不影响主线 |
| ImageCompare 旧任务左图占位处理 | from-pacs 任务已正常，旧任务占位不阻塞 |
| 患者详情页补充 clinical-view 入口 | 原型尾巴，Integration.vue 是主入口 |
| Redis 引入 | 无真实使用场景 |
| test/index.html 修复 | 已废弃 |
| KI-007 SSE 枚举约束 | backend-ai 协作者职责 |

---

## 已完成里程碑（可回退参考）

- [x] 单 schema + 分型表原型验证（ext_his / ext_lis / ext_pacs）
- [x] 多库底座重构（app / his / lis / pacs 四库，pool + schema + seed + 启动迁移）
- [x] clinical-view 从单 schema 切换为真实多库聚合查询
- [x] listExternalSources 从 mock 切换为三库聚合
- [x] PACS 静态访问链路（/pacs-static 路由 + queryPacs 返回可访问 URL）
- [x] ai_tasks 加 pacs_record_id，POST /api/tasks/from-pacs，TaskDetail 左图接入 PACS 原图
- [x] Integration.vue 统一临床视图工作台（双栏 + HIS/LIS/PACS/AI 任务 Tabs）
- [x] PatientList.vue 定位为 fallback/补录入口

---

## 已知问题 / 风险

| ID | 问题 | 状态 |
|----|------|------|
| KI-001 | `EventSource` 无法发送自定义请求头，SSE 鉴权依赖 cookie / 代理行为 | 🟡 活跃风险 |
| KI-002 | `test/index.html` 无 cookie 机制，接口全 401 | 🟡 非阻塞，已知 |
| KI-003 | `ImageCompare` 左侧原图 | ✅ TaskDetail 已接 pacs_image_url；from-pacs 任务可显示原图；旧任务兼容占位 |
| KI-004 | 当前 EMPI 和外部来源接入已完成原型验证，但整体仍依赖单 schema / mock 过渡结构，尚未进入正式多库架构 | 🟡 当前主线正在重构 |
| KI-007 | `SSEResultEvent.status` 无枚举约束，AI 侧返回非预期值会导致前端判断失效 | 🟡 非阻塞，建议协作者加 `Literal` 约束 |