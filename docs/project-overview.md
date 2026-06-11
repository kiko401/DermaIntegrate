# project-overview.md

> 状态：2026-06-08 初稿。每次开发会话后更新"当前状态"与"联调状态"两节。

---

## 项目目标

面向皮肤科门诊，构建一套多源数据集成与 AI 辅助诊断系统，解决三个核心问题：

1. **数据孤岛**：HIS/PACS/LIS 异构，患者标识不一，无法形成完整临床视图
2. **单模态局限**：初诊常缺病理金标准，单图无法支撑分期
3. **AI 不可解释**：端到端模型无推理依据，LLM 易产生英文漂移和幻觉

---

## 系统架构（两域隔离）

```
[前端 Vue 3]
     ↓
[Node/Express — 代理层 + 业务服务]   ← 工程端负责
     ↓
[FastAPI — AI 推理域]                 ← 算法端负责
     ↓
[MySQL / Qdrant / Redis]
```

两域进程级隔离，唯一协作通道是 `docs/DermaIntegrate 多模态数据契约 v3.1(1).md`。

---

## 前后端分工

### 算法端（朋友）— `backend-ai/`

**文件已存在（已验证·目录树读取）**：
- `api/main.py`、`config.py`、`models/database.py`、`preprocessing/dicom_parser.py`、`agents/vlm_agent.py`、`cnn/lesion_extractor.py`、`rag/knowledge_base.py`、`sql/init.sql`
- `agents/clinical_agent.py`、`agents/pathology_agent.py`、`agents/integration_agent.py`（存在于目录树；源码内容未读取）
- `rag/docs/` 下 4 份专科文档（AJCC_8th.txt、NCCN_2024.txt、卫健委2022.txt、常见色素性皮损鉴别.txt）

**功能描述（推理得出·来自 README 描述 + main.py 读取，非源码全量验证）**：
- FastAPI 路由框架：`/upload`、`/stream/{task_id}`、`/images/{image_uid}`、`/features/{task_id}`、`/health`（已验证·读 main.py）
- `task_id` 驱动的多模态 SSE 推理管线（已验证·读 main.py）
- DICOM 防御性转码（已验证·读 dicom_parser.py）
- VLM 形态学特征提取，DeepSeek-VL2，支持 mock（已验证·读 vlm_agent.py）
- 病历 / 病理 / 整合 Agent 的功能描述（推理得出·来自 README，源码未读）
- RAG 知识库使用 Qdrant + bge-small-zh-v1.5（推理得出·来自 README；云端是否已初始化，待确认）
- MySQL 三表 ORM（已验证·读 database.py）
- Docker Compose 编排（已验证·读 docker-compose.yml）

### 工程端（用户）— `backend-app/` + `frontend/`

待建（目录在 repo 中尚不存在）：
- Node/Express 代理层（转发 upload、流式代理 SSE、统一超时/错误/日志处理）
- Node/Express 业务服务（EMPI 主索引映射、FHIR R4 适配、患者 CRUD、任务记录）
- Vue 3 前端（医生工作站、影像滑动对比、AI 流式对话框）
- 应用域 MySQL（独立于推理域数据库，端口 3306）

---

## 联调现状

| 项目 | 状态 | 说明 |
| :--- | :--- | :--- |
| AI 服务云端部署 | ⬜ 待确认 | 地址 `http://124.222.0.186/ai` 来自契约文档；实际在线状态未 curl 验证 |
| `/health` 接口 | ⬜ 待确认 | 未 curl |
| `/upload` 接口 | ⬜ 待确认 | 未 curl |
| `/stream/{task_id}` SSE | ⬜ 待确认 | 未联调 |
| `status` 字段值修复 | 🟡 用户口头确认 | 用户确认已改为 `"complete"`；AI 助手未二次 git show 验证，云端部署状态未确认 |
| `message` 字段名修复 | 🟡 用户口头确认 | 用户确认已修复；AI 助手通过 git show 读到 `feat/ai/multimodal-agents` 分支已是 `message`（已验证·git show）；云端是否已部署，待确认 |
| `pathology_done` 事件名修复 | 🟡 用户口头确认 | 同上，git show 已验证代码；云端部署待确认 |
| app 侧骨架 | ❌ 尚未开始 | `backend-app/` 和 `frontend/` 目录不存在（已验证·目录树） |

---

## 当前状态（2026-06-08）

- AI 侧文件结构完整（已验证·目录树）；v3.1 关键字段修复用户已口头确认，云端部署状态待确认
- 工程端处于 Phase 0（联调准备），尚未建任何代码
- 下一步：建 `feat/app/sse-integration` 分支，搭 Node/Express 骨架，完成首次联调握手

---

## 关键约束（不可违反）

1. Vue 不直接调用 AI 服务，必须经过 Node/Express
2. `AI_BASE_URL` 由环境变量管理，不硬编码 IP
3. SSE 代理必须流式转发，不可整包缓冲
4. 前端渲染采用"收到什么渲染什么"策略，不假设步骤顺序
5. 应用域 MySQL（3306）与推理域 MySQL（3307）物理隔离，不共用
