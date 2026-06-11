# architecture.md — 系统架构设计

> 本文档描述目标架构与核心设计决策。
> 状态标记：✅ 已实现 / ⬜ 待实现

---

## 一、两域隔离原则

系统划分为两个进程级隔离的服务域，唯一协作通道是 HTTP API 契约。

```
┌─────────────────────────────────┐     HTTP / SSE      ┌─────────────────────────────────┐
│        应用平台域                │ ──────────────────> │        智能推理域                │
│   Node 18 + Express             │                     │   FastAPI + Python 3.11         │
│   Vue 3 前端                    │ <────────────────── │   Multi-Agent + RAG + ONNX      │
│   MySQL 3306（业务数据）         │    SSE 事件流        │   MySQL 3307 + Qdrant 6333      │
└─────────────────────────────────┘                     └─────────────────────────────────┘
```

**为什么要隔离**：
- 两端独立开发部署，互不 review 对方代码
- 推理域崩溃不影响应用域业务数据
- 数据库物理隔离，防止业务逻辑污染推理域

---

## 二、请求链路

### 2.1 上传链路

```
Vue 前端
  → POST /api/tasks/upload (multipart)
  → Node/Express (multer 解析 → 重构 FormData → fetch 转发)
  → FastAPI POST /upload
  → 返回 { task_id, status: "accepted" }
  → Node 透传 202 给前端
```

### 2.2 SSE 推理链路

```
Vue 前端 (EventSource)
  → GET /api/tasks/:taskId/stream
  → Node/Express (原生 http 模块，零缓冲透传)
  → FastAPI GET /stream/{task_id}
  → AI 逐步推送事件：image_done → clinical_done → pathology_done → result
  → Node chunk 到达即 res.write()，不等推理完成
  → 前端按事件类型动态渲染
```

### 2.3 静态图片链路（代码已实现，未 curl 验证）

```
Vue 前端 (img src)
  → GET /ai-static/heatmaps/{filename}
  → Node/Express 代理
  → FastAPI 静态文件服务
```

---

## 三、应用域内部分层

```
backend-app/src/
├── routes/      HTTP 层：参数校验、调 service、返回响应（不写 SQL）
├── services/    业务层：业务规则（不知道 HTTP，不知道 SQL 细节）
└── db/          数据层：连接池、查询封装（不知道业务规则）
```

### 应用域数据库 Schema（MySQL 3306）⬜

```sql
patients        患者主表（id / name / id_number / phone / birth_date / gender）
  └── visits    就诊记录（id / patient_id / chief_complaint / visit_date）
        └── ai_tasks  AI 任务映射（id / task_id / visit_id / status）
```

`ai_tasks.task_id` 是与推理域对接的唯一键，由 FastAPI `/upload` 生成，应用域只存储不生成。

---

## 四、前端架构（Vue 3）⬜

```
frontend/
├── views/
│   ├── PatientList.vue      患者列表
│   └── VisitDetail.vue      就诊详情 + AI 诊断入口
├── components/
│   ├── DiagnosisDialog.vue  SSE 流式诊断对话框
│   └── ImageCompare.vue     影像滑动对比组件（原图 / 热力图）
└── hooks/
    └── useSSE.js            SSE 连接管理（建立 / 断连 / 事件分发）
```

**关键约束**：
- Vue 严禁直接访问 `AI_BASE_URL`，所有请求经 Node/Express 代理
- 组件卸载时必须调用 `eventSource.close()`，释放 SSE 连接
- 影像渲染使用 `createObjectURL`，组件卸载时调用 `revokeObjectURL` 防内存泄漏

---

## 五、SSE 事件契约（摘要）

完整定义见 `docs/DermaIntegrate 多模态数据契约 v3.1(1).md` 和 `docs/api-contract.yaml`。

| 事件类型 | 触发时机 | 前端动作 |
|:---|:---|:---|
| `image_done` | 图像 Agent 完成 | 渲染热力图模块 |
| `clinical_done` | 病历 Agent 完成 | 渲染病历解析模块 |
| `pathology_done` | 病理 Agent 完成 | 渲染病理分期模块 |
| `result` | 整合 Agent 完成 | 渲染最终报告，区分 `complete` / `incomplete` |
| `heartbeat` | 周期保活 | 静默消费，防代理超时断连 |
| `error` | 推理失败 | 展示错误提示，关闭 SSE 连接 |

---

## 六、基础设施（Phase 8）⬜

```
Nginx 网关
  ├── /          → Vue 前端静态资源
  ├── /api/      → Node/Express 应用域（3000）
  └── /ai/       → FastAPI 推理域（8000）

Nginx SSE 必要配置：
  proxy_buffering off;
  proxy_cache off;
  proxy_read_timeout 300s;
```

Docker Compose 编排：MySQL × 2（3306 / 3307）、Qdrant（6333）、Redis（6379）、FastAPI、Node、Nginx。

---

## 七、核心设计决策

| 决策 | 选择 | 原因 |
|:---|:---|:---|
| SSE vs WebSocket | SSE | 推理结果单向推送，无需全双工；HTTP 代理配置简单 |
| 原生 http 模块 vs http-proxy-middleware | 原生 http | proxy-middleware 缓冲 SSE 响应，原生模块零缓冲直传 |
| multer 内存模式 | 不落盘 | 代理转发场景无需持久化，Node 18 原生 Blob/FormData 直接重构 |
| 双数据库隔离 | MySQL 3306 / 3307 | 业务逻辑与推理数据物理隔离，互不污染 |
| 前端不直连 AI | Node 代理层 | 安全（IP 不暴露）+ 统一鉴权入口 + 无 CORS 问题 |
