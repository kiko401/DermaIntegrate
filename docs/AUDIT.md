# AUDIT.md — 代码排查清单

> 新会话读取此文件可直接接上排查进度。
> 与 TODO.md 分离：TODO.md 跟踪里程碑（M1-M4），本文件跟踪具体代码缺陷。
> 最后更新：2026-06-17

---

## 状态说明

- `[ ]` 待排查/待修复
- `[?]` 需验证（先看现状再决定是否修改）
- `[x]` 已修复

---

## A — 数据层（优先级：🔴 功能性）

### A1 · 两套 schema 并存，数据库名不同 `[x]`

**结论：** `pools/app.js` 连接 `derma_app`（`APP_DB_NAME`，默认值）。`schema/app.sql` 是当前正式 schema，`ai_tasks` 已含 `patient_id` + `pacs_record_id`。`schema.sql`（`derma_integrate`）已废弃，已在文件头加 DEPRECATED 注释。

---

### A2 · app.js 中旧 ext_* 建表语句是单库残留 `[x]`

**位置：** `backend-app/src/app.js`（已删除）

**修复：** 删除 `extTables` 数组及 for 循环（原 22-67 行）。`ext_*` 表由多库 schema/his.sql/lis.sql/pacs.sql 管理。

---

### A3 · app.js 迁移不完整：缺 patient_id 列 `[x]`

**结论：** 不需要修改。已确认使用 `derma_app`，`schema/app.sql` 建表时 `ai_tasks` 就含 `patient_id`，无需运行时迁移补列。

---

### A4 · 旧 seed.js 与新 seed/ 目录并存 `[x]`

**结论：** `package.json` 的 `npm run seed` 已修改为 `node src/db/seed/index.js`（多库版）。旧 `db/seed.js` 已加 DEPRECATED 注释。

---

## B — 后端服务层（优先级：🔴 影响主流程）

### B1 · taskService.listAll() from-pacs 任务 patient_name 为 null `[x]`

**修复：** `taskService.js:50` JOIN 条件改为 `p.id = v.patient_id OR p.id = t.patient_id`，与 getDetail 一致。

---

### B2 · empiService.getClinicalView ai_tasks 子查询过滤掉 from-pacs 任务 `[x]`

**修复：** `empiService.js` WHERE 条件改为 `COALESCE(t.patient_id, v.patient_id) = ?`。

---

## C — 前端导航（优先级：🟡 入口缺失）

### C1 · AppHeader 无导航菜单，Integration 页无全局入口 `[x]`

**修复：** AppHeader.vue 加三条导航链接（工作台 / 数据集成 / AI 记录），当前路由高亮蓝色。

---

## D — 前端 Integration.vue（优先级：🟡）

### D1 · 概览 Tab EMPI 映射行 ext_name 字段不存在 `[x]`

**修复：** 删除 `mapping-sep` 和 `mapping-name` 两个 span，不显示外部系统姓名（后端不返回该字段）。

---

### D2 · AI 任务 Tab r.id 为 undefined，缺跳转链接 `[x]`

**修复：** `r.id` → `r.task_id?.slice(0, 8)`；`v-for` key 改为 `task_id`；加"查看"按钮跳转 `/tasks/:task_id`。

---

### D3 · 无 URL 参数支持，外部跳转无法自动定位患者 `[x]`

**修复：** 引入 `useRoute`，`onMounted` 改为 async，先 `fetchSources` 再读 `route.query.patient_id` 自动调 `selectPatient`。

---

## E — 前端 TaskDetail.vue（优先级：🟡）

### E1 · from-pacs 任务侧边栏"就诊信息"字段全空 `[x]`

**修复：** `task.pacs_record_id && !task.visit_id` 时显示"PACS 来源"卡片（来源类型 + PACS 记录 ID），否则显示原就诊信息卡。

---

### E2 · "重新分析"按钮跳转到 /patients 而非 /integration `[x]`

**修复：** `router.push` 目标改为 `/integration?patient_id=...`，配合 D3 自动定位患者。

---

## F — 前端 Dashboard.vue（优先级：🟡）

### F1 · "最近就诊" from-pacs 任务字段全空 `[x]`

**修复：** `recentVisits` / `recentTasks` 的 `complaint` 映射加 `pacs_record_id` 判断，无主诉时显示 `[PACS 影像分析]`；`date` 改为 `visit_date || created_at`。

---

### F2 · 鉴权路由守卫依赖 localStorage，cookie 过期不感知 `[x]`

**修复：** `beforeEach` 改为 async，首次受保护导航时请求 `/api/auth/me` 验证 cookie，401 则清 localStorage 并跳登录页。用 `router._cookieVerified` flag 确保只验一次，后续依赖 apiFetch 401 兜底。

---

## 执行顺序

```
A1（验证）→ A2（删旧建表）→ A3（视A1结论）→ A4（验证seed）
→ B1（taskService JOIN）→ B2（getClinicalView WHERE）
→ C1（AppHeader 导航）
→ D1+D2+D3（Integration.vue 三处，同一文件）
→ E1+E2（TaskDetail.vue 两处，同一文件）
→ F1（Dashboard.vue）
→ F2（可选）
```
