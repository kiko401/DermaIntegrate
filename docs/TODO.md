# TODO.md

> 最后更新：2026-06-19
> **当前最重要的事：N1/N2/N3/N6 全部完成。Seed 数据已重构为真实多源异构映射（EMPI reconcile 驱动），内部患者完全由外部三库归集生成。AI 自动触发链路已打通：`GET /api/tasks` 支持 patient_id 过滤，临床视图无任务时自动发起首次分析并接入 SSE。**

---

## 基本信息

- 分支：`feat/multidb-empi-rebuild`
- 默认工作范围：`frontend/` + `backend-app/`
- AI 推理域 `backend-ai/`：协作者负责，默认不修改、不扫描

---

## 当前代码状态（已核实）

### 后端 `backend-app/src/`

| 文件 | 内容 |
|------|------|
| `routes/auth.js` | JWT + httpOnly cookie，登录/登出/me |
| `routes/patients.js` | 患者 CRUD + `GET /api/patients/:id/clinical-view` |
| `routes/visits.js` | 就诊记录 CRUD |
| `routes/upload.js` | `POST /api/tasks/upload`（手动上传）+ `GET /api/tasks`（任务列表） |
| `routes/stream.js` | SSE 代理 + 历史快照 + 任务详情（含 pacs_image_url） |
| `routes/pacs_task.js` | `POST /api/tasks/from-pacs`（已聚合 HIS clinical_text + LIS lab_json） |
| `routes/empi.js` | EMPI 匹配 + 外部数据源列表统计 + stats |
| `routes/health.js` | AI 健康检查 + HIS 连接检查 |
| `routes/static.js` | AI 静态资源代理 `/ai-static/*` |
| `services/empiService.js` | getClinicalView（四库并发聚合）、matchAndLink、listExternalSources |
| `services/taskService.js` | create/createFromPacs/getByTaskId/saveSnapshot/getSnapshot/listAll/getDetail |
| `db/schema/` | app/his/lis/pacs 四库 schema（含 lis_pathology_reports 表） |
| `db/seed/` | 四库 seed（8位患者，HIS 16条就诊/LIS 26条结果+2份病理/PACS 10条影像/EMPI 19条映射；5条孤立外部记录待审核；内部患者由 HIS reconcile 驱动生成，非硬编码插入） |
| `app.js` | 启动时自动迁移 result_snapshot 和 pacs_record_id 列，四库建表检查 |

### 前端 `frontend/src/`

| 路由 | 组件 | 说明 |
|------|------|------|
| `/login` | `LoginView.vue` | 登录页 |
| `/` → `/patients` | 重定向 | 默认入口 |
| `/patients` | `PatientList.vue` | 患者检索表格，点"查看档案"跳 `/clinical/:id` |
| `/clinical/:patientId` | `ClinicalView.vue` | 左70% 多Tab病历 + 右30% AI侧栏，SSE live/快照双模式 |
| `/tasks/:taskId` | `TaskDetail.vue` | 独立任务详情，Snapshot/Live 模式自动切换，三路卡片 |
| `/admin/tasks` | `Tasks.vue` | 管理员任务监控，requireAdmin |
| `/admin/integration` | `Integration.vue` | Tab1 EMPI映射治理 + Tab2 SSE会话治理，requireAdmin |
| `/admin/users` | `admin/Users.vue` | 账号管理 stub，requireAdmin |

其他：`hooks/useSSE.js`（EventSource 封装）、`components/ImageCompare.vue`、`App.vue`（顶部导航，role 控制导航项）

### 基础设施

- `infra/docker-compose.app.yml`：frontend + backend-app + mysql + nginx
- `infra/nginx.conf`：SSE 专用 location，proxy_buffering off，3600s 超时
- `infra/init-app.sql`：仅初始化 derma_app 库

---

## 目标形态

系统的核心场景是：外部系统（HIS/LIS/PACS）通过 Webhook 推送数据，系统自动触发 AI 分析，医生打开患者后直接看到整合好的真实病历数据和 AI 建议，不需要手动录入或主动点击触发。当前原型已完成数据聚合和 AI 推理链路的核心部分，剩余差距集中在：自动触发机制未实现、患者列表字段聚合有 bug、前端导航结构对医生不友好。

---

## 里程碑任务

### N1 — 修复患者列表聚合字段缺失

**为什么：** `PatientList.vue` 依赖 `has_pacs`、`has_lis`、`empi_id` 字段做过滤和标签展示，但 `patientService.list()` 只做 `SELECT * FROM patients`，这些字段从未返回。前端的"有影像"/"有病理"过滤器和 HIS/LIS/PACS 标签全部无效，是已知的功能性 bug。

**完成标志：**
- `GET /api/patients` 返回字段包含 `has_his`、`has_lis`、`has_pacs`（boolean）和 `empi_id`（string | null）
- 前端患者列表过滤器（有影像/有病理）按预期工作
- 患者卡片的 HIS/LIS/PACS 标签正确显示

**进度：**
- [x] `patientService.list()` 扩充：并发查三库统计，返回 has_his/has_lis/has_pacs/empi_id 字段（跨库 JOIN 查询，已验证张伟/李敏/王强返回正确）
- [x] 前端验证：过滤器有效，标签显示正确（已验证通过）

---

### N2 — Webhook 自动触发机制

**为什么：** 当前只能医生手动点"重新生成AI分析"，不符合目标形态"数据推送后自动触发"的设计。这是数据集成与 AI 诊断两条主线之间的断裂口。

**完成标志：**
- `POST /api/mock/his_push`：入库 his_records，不触发分析
- `POST /api/mock/lis_push`：入库 lis_results；若 `is_pathology=true` 则同时入库 lis_pathology_reports，并触发分析
- `POST /api/mock/pacs_push`：入库 pacs_records，触发分析
- DebounceManager：内存 Map，同一 patient_id 30s 窗口合并，到期执行 `triggerAnalysis(patient_id)`
- TaskConflictResolver：`triggerAnalysis` 时检查同 patient_id 是否有 pending/running 任务；若有则先将旧任务标记 `interrupted`，再发起新任务
- `triggerAnalysis(patient_id)` 复用 pacs_task.js 的聚合逻辑，取该患者最新 pacs_record 发起分析
- 三个推送接口的入参使用**模拟异构格式**（字段名、结构故意与内部不同，体现真实外部系统的异构性），经 FHIRAdapter 归一化后再存库（见下方说明）

**FHIRAdapter 归一化（随 N2 一起实现）：**
- 新建 `services/fhirAdapter.js`，提供三个纯函数：`normalizeHis(raw)`、`normalizeLis(raw)`、`normalizePacs(raw)`
- 每个函数接收模拟的"外部异构 JSON"，输出内部统一结构，再走 EMPI 匹配和存库
- 模拟异构格式示例：
  - HIS：`{ pat_no, id_no, visit_info: { dept_name, cc, diag } }`（字段缩写+嵌套）
  - LIS：`{ specimen_id, patient_id_card, test_results: [{ item, val, unit_str }] }`（数组嵌套）
  - PACS：`{ ris_uid, card_no, img_path, thumb_path, modality_code }`（字段名完全不同）
- 体现思路：外部异构格式进来 → FHIRAdapter 归一化 → EMPI 匹配 → 存对应库；存库后数据格式不变，下游全部不受影响

**进度：**
- [x] 新建 `routes/mock_push.js`，三个接口使用模拟异构入参格式
- [x] 新建 `services/fhirAdapter.js`（三个归一化纯函数）
- [x] 新建 `services/debounceManager.js`（内存 Map，30s 防抖）
- [x] 新建 `services/conflictResolver.js`（检查 running 任务 → 标记 interrupted → 触发新任务）
- [x] `triggerAnalysis` 抽离为独立函数，供 debounceManager 调用
- [x] app.js 注册新路由

---

### N3 — 前端视图重定位

**为什么：** `PatientList.vue` 的主按钮"查看历史AI报告"跳转到 `Tasks.vue` 是错误的导航方向。`Tasks.vue` 是运维监控页，不应该是医生的主路径。AI 建议应内嵌在患者视图中，医生不需要离开当前页就能看到结果。

**完成标志：**
- `PatientList.vue`：去掉"查看历史AI报告"跳转按钮；AI 最新建议（result_snapshot）直接内嵌展示在患者工作区（区块5位置）
- `Tasks.vue`：从主导航降级，移入 `Integration.vue` 的第三个 Tab（"任务监控"），定位为运维功能
- `App.vue`：侧边栏去掉"AI 分析记录"独立入口，集成到 Integration.vue

**进度：**
- [x] `PatientList.vue`：改造区块5，直接加载并展示该患者最新任务的 result_snapshot
- [x] `Integration.vue`：新增"任务监控"Tab，嵌入 Tasks.vue 的内容
- [x] `App.vue`：更新侧边栏导航

---

### N4 — Docker 三库初始化修复

**为什么：** `infra/init-app.sql` 只初始化 `derma_app`，`docker-compose.app.yml` 的 mysql 容器 `MYSQL_DATABASE` 也只设了 `derma_app`。其他三库（derma_his/derma_lis/derma_pacs）靠 app.js 启动时建表，但如果库本身不存在，`CREATE TABLE IF NOT EXISTS` 会报错，导致启动失败。

**完成标志：**
- `infra/init-app.sql` 加入 `CREATE DATABASE IF NOT EXISTS derma_his/derma_lis/derma_pacs`
- `docker-compose -f infra/docker-compose.app.yml up` 能正常启动并通过 seed
- 端到端验证：三库表结构完整，seed 数据可查

**进度：**
- [x] `infra/init-app.sql` 补全四库 CREATE DATABASE 语句（已含四库，docker-compose.app.yml 已正确挂载）
- [ ] 本地或 CI 验证 docker-compose up 全流程

---

### N5 — FHIR R4 归一化层（延后）

**为什么：** README 提到 FHIR R4，当前 clinical-view 输出自定义格式，未符合规范。这是学术规范项，不影响当前功能主线。

**完成标志：** `GET /api/patients/:id/clinical-view` 输出符合 FHIR R4 规范的资源结构（Patient / Observation / ImagingStudy）

**依赖：** N1-N4 完成后单独评估工作量。

**进度：**
- [ ] 评估工作量后拆分子任务

---

### N6 — 前端全面重构（按定稿方案 v1.0，医生端 + 管理员端）

**为什么：** 当前前端页面结构与《前端页面与布局排版最终定稿方案 v1.0》不符。核心问题：无独立临床视图页、患者列表承担过多职责、无医生/管理员端分离、SSE 渲染违反动态原则。

**完成标志：**
- 医生端（`/patients`、`/clinical/:patient_id`）可正常使用 `doctor` 账号登录访问
- 管理员端（`/admin/*`）可正常使用 `admin` 账号登录访问
- 两端路由守卫隔离，越权跳 403
- SSE 渲染使用动态追加（无 if/else 硬编码顺序）
- 所有组件 `onUnmounted` 中执行 `eventSource.close()`

**测试账号（seed 写入）：**
| 账号 | 密码 | 角色 | 可访问路由 |
|------|------|------|-----------|
| `doctor` | `demo123` | 医生 | `/patients`、`/clinical/*`、`/tasks/*` |
| `admin` | `admin123` | 管理员 | `/admin/*` 及上述全部 |

**测试数据：** 见下方 Seed 数据说明。

---

#### N6-S1 — 后端：doctors 表加 role 字段 + admin seed

**完成标志：**
- `doctors` 表新增 `role` 列（`'doctor'`/`'admin'`，默认 `'doctor'`）
- JWT payload 含 `role` 字段
- `GET /api/auth/me` 返回 `role`
- seed 写入 `admin` 账号（role=admin）

**验证方式：**
```bash
cd backend-app && node src/app.js
# 另一终端
curl -c cookies.txt -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 返回 { doctor: { id, name, role: "admin" } }
curl -b cookies.txt http://localhost:3000/api/auth/me
# 返回 role: "admin"
```

**进度：**
- [x] `schema/app.sql`：`doctors` 表加 `role VARCHAR(10) DEFAULT 'doctor'`
- [x] `app.js` 启动迁移：`ALTER TABLE doctors ADD COLUMN IF NOT EXISTS role ...`
- [x] `routes/auth.js`：JWT payload 加 `role`，`/me` 返回 `role`
- [x] `seed/app.js`：写入 admin 账号（`role='admin'`）
- [x] `npm run seed` 验证（build 通过，seed 逻辑已包含 admin 账号）

---

#### N6-S2 — 后端：admin 路由守卫中间件

**完成标志：**
- `middleware/requireAdmin.js`：`role !== 'admin'` 返回 403
- `/admin/*` 路由全部走此中间件

**验证方式：**
```bash
# 用 doctor 账号 cookie 访问 admin 接口，应返回 403
curl -b doctor_cookies.txt http://localhost:3000/api/admin/sessions
# 用 admin 账号 cookie 访问，应返回 200
```

**进度：**
- [x] 新建 `middleware/requireAdmin.js`
- [x] `app.js` 将 admin 路由挂载到 `/api/admin/*`

---

#### N6-S3 — 前端：路由重构 + App.vue 顶部导航

**完成标志：**
- 路由表按定稿方案，新增 `/clinical/:patient_id`，管理员路由挂 `/admin/*`
- `App.vue`：侧边栏改为顶部导航条（系统名 | 当前用户 | 退出）
- 路由守卫：`/admin/*` 路由检查 `localStorage` 中 `role`，非 admin 跳转 `/patients`
- 医生端底部或顶部不显示 admin 入口

**验证方式：**
1. 用 `doctor` 登录，手动访问 `/admin/tasks`，应跳转回 `/patients`
2. 用 `admin` 登录，访问 `/admin/tasks`，正常显示

**进度：**
- [x] `router/index.js` 重写
- [x] `App.vue` 改顶部导航，根据 role 控制导航项

---

#### N6-S4 — 前端：PatientList.vue 精简

**完成标志：**
- 只有搜索栏 + 患者表格（ID、姓名、性别、年龄、EMPI映射状态、操作）
- 去掉临床视图折叠区、AI 报告区块、工作区头部
- "查看档案"跳转 `/clinical/:patient_id`

**验证方式：**
1. `doctor` 登录，访问 `/patients`，搜索"张"，找到张伟
2. 点"查看档案"，跳转到 `/clinical/901`

**进度：**
- [x] `PatientList.vue` 精简重写（去掉工作区/AI报告/折叠视图，操作列改"查看档案"跳 `/clinical/:id`）

---

#### N6-S5 — 前端：ClinicalView.vue 新建（核心）

**完成标志：**
- 左 70%：多 Tab（基本信息 / HIS就诊 / LIS化验 / LIS病理 / PACS影像），调用 `GET /api/patients/:id/clinical-view`
- 右 30%：AI 侧栏
  - 初始状态：展示最近一次任务快照（如有）
  - 若有 running 任务：建立 SSE 连接，动态追加 step 卡片（image_done / clinical_done / pathology_done），result 事件更新综合研判区
  - `onUnmounted` / `beforeRouteLeave` 执行 `eventSource.close()`
  - 有 `incomplete` 状态时顶部黄色警告
- "重新生成分析"按钮调用现有 from-pacs 接口

**验证方式：**
1. `doctor` 登录，打开张伟 `/clinical/901`
2. 左侧 HIS Tab 应有就诊记录，PACS Tab 应有影像缩略图
3. 右侧 AI 侧栏应显示最近任务快照（如有）
4. 点"重新生成分析"，右侧侧栏进入 SSE live 模式，卡片动态追加

**进度：**
- [x] 新建 `views/ClinicalView.vue`（左70%多Tab + 右30%AI侧栏，useSSE复用，onUnmounted/beforeRouteLeave均close）
- [x] `hooks/useSSE.js` 已有 connect/close 接口，无需改动

---

#### N6-S6 — 前端：TaskDetail.vue 重构

**完成标志：**
- 进入时自动判断：有 running 任务 → Live 模式（SSE）；有快照 → Snapshot 模式
- 顶部模式指示器（蓝色快照横幅 / 橙色 Live 横幅）
- 内容区：三路 agent 卡片（并行无序）+ 综合研判区
- `onUnmounted` 执行 `close()`

**验证方式：**
1. 从 `/clinical/901` 点击历史任务"查看详情"，应进入 Snapshot 模式
2. 在 `/clinical/901` 触发新分析后从侧栏点"查看详情"，应进入 Live 模式

**进度：**
- [x] `TaskDetail.vue` 重构（isSnapshot/agentEvents 动态卡片、快照横幅含生成时间、三路卡片横排 3 列、去右侧侧栏移患者信息到顶部 header、综合研判区全宽后置、onUnmounted close）

---

#### N6-S7 — 前端：管理员页面

**完成标志：**
- `/admin/tasks`（Tasks.vue 搬迁）：全屏任务监控，"查阅快照"跳 `/tasks/:id`
- `/admin/integration`（Integration.vue 重构）：Tab1 EMPI映射治理，Tab2 SSE会话治理（含强制释放）
- `/admin/users`（Users.vue 新建）：医生账号列表 + 新增（stub，无后端接口）

**验证方式：**
1. `admin` 登录，访问 `/admin/tasks`，应有任务列表
2. 访问 `/admin/integration`，Tab1 应有 EMPI 映射明细，Tab2 应有会话列表
3. 访问 `/admin/users`，应有账号列表

**进度：**
- [x] `Tasks.vue` 路由已挂载至 `/admin/tasks`（router/index.js 已配置）；`goPatient` 改跳 `/clinical/:id`；操作列改"查阅快照"
- [x] `Integration.vue` 重构（Tab1 EMPI映射治理全量表格，Tab2 SSE会话治理 stub，去掉旧任务监控 Tab）
- [x] UC-11 SSE 会话治理实装：新建 `services/sseRegistry.js`（ConnectionMonitor + SessionGovernor）；`stream.js` 建连时 register/断连时 unregister/每个 data chunk 调 touch 更新 lastHeartbeat；`GET /api/admin/sessions` 读取内存注册表；`DELETE /api/admin/sessions` 强制释放（写 force_close 事件再 res.end()）；Integration.vue Tab2 去 stub 接真实接口，支持刷新、勾选、强制释放、超时橙色高亮；`useSSE.js` 补 force_close 事件监听（close + 入 events）；ClinicalView.vue/TaskDetail.vue 补 forceCloseEvent computed 和警告横幅
- [x] EMPI Tab 搜索框：前端过滤，支持姓名/外部ID/身份证/手机/内部患者ID，与来源 radio 叠加
- [x] `views/admin/Users.vue` 重写（账号列表 stub + 新增弹窗 stub）
- [x] 管理员权限隔离（N6-S8）：新建 `requireDoctor` 中间件；`/api/patients` 及 `clinical-view` 限医生（403）；新增 `GET /api/admin/patients`（只返回基本信息+EMPI状态，不含 HIS/LIS/PACS 临床数据）；新建 `views/admin/PatientAdmin.vue`；admin 登录后跳 `/admin/patients`；前端路由守卫隔离 `/clinical/*` 和 `/patients` 仅医生可访问
- [x] UC-09 用户账号管理（N6-S9）：`doctors` 表补 `is_active`/`deleted_at` 列；`adminRouter` 实现 GET/POST/PATCH/PUT/DELETE `/api/admin/users`；`Users.vue` 接真实接口，支持新增、禁用/启用、重置密码、删除（含最后管理员保护）

---

## 现在不要做

| 事项 | 原因 |
|------|------|
| Redis 引入 | 防抖用内存 Map 足够，无持久化需求 |
| EMPI 冲突扫描前端展示 | 后端接口已有，延后 |
| DiagnosisDialog.vue 改造或删除 | 当前不阻塞，不动 |
| test/index.html 修复 | 已废弃 |
| ConnectionMonitor/ResourceReclaimer 抽象重构 | stream.js 内联逻辑功能等价，重构收益低 |
| ImageCompare 旧任务左图占位处理 | from-pacs 任务已正常，旧任务占位不阻塞 |

---

## 已知问题 / 风险

| ID | 问题 | 状态 |
|----|------|------|
| KI-001 | EventSource 无法发自定义请求头，SSE 鉴权依赖 httpOnly cookie（EventSource 自动携带 cookie，当前可行） | 🟡 活跃风险，已 workaround |
| KI-002 | test/index.html 无 cookie 机制，接口全 401 | 🔴 已废弃，不修复 |
| KI-003 | TaskDetail.vue 快照模式与 live 模式切换逻辑正确；快照格式（Array of events）与 SSE 事件格式一致，依赖 taskService.saveSnapshot 的格式约定 | 🟢 已验证 |
| KI-004 | patientService.list() 不含 has_pacs/has_lis/empi_id 字段，前端过滤功能无效 | ✅ N1 已修复，前端待验证 |
| KI-005 | docker-compose 只初始化 derma_app，derma_his/lis/pacs 库不存在会导致 app.js 启动建表失败 | 🟡 N4 要修复 |
| KI-006 | stream.js 断连处理是内联逻辑（req.on close），未实现 ConnectionMonitor/ResourceReclaimer 抽象 | ✅ UC-11 已实装：sseRegistry.js 实现注册表，stream.js 已 register/unregister/touch（每个 data chunk 更新 lastHeartbeat） |
| KI-007 | SSEResultEvent.status 无枚举约束，AI 侧返回非预期值导致前端判断失效 | 🟡 backend-ai 协作者职责 |
| KI-008 | from-pacs 触发分析是手动，Webhook 自动触发机制未实现 | ✅ N2 已实现（mock_push + debounceManager） |
| KI-009 | seed 数据量少且内容雷同，不能体现多源异构/缺模态/孤立记录等场景 | ✅ 已修复：8患者/系统，覆盖情况A-E，test患者已清除，内部患者改为 EMPI reconcile 自动建档 |
