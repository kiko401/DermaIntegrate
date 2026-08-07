# DermaIntegrate

皮肤科多源数据整合与 AI 辅助诊断平台

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Node](https://img.shields.io/badge/Node-18%2B-green)
![Vue](https://img.shields.io/badge/Vue-3-brightgreen)

---

## 概览

DermaIntegrate 面向皮肤科门诊与临床协同场景，解决 HIS / LIS / PACS 等多源异构数据难以统一、初诊信息不完整、AI 结果缺乏可解释性等问题。

系统采用双域架构：

- **应用平台域**：负责数据接入、患者聚合、任务管理与前端交互
- **智能推理域**：负责多模态输入处理、知识检索、AI 分析与结构化输出

两个域通过 `docs/api-contract.yaml` 定义的接口进行交互，保持职责隔离与边界清晰。

---

## 核心问题与解决思路

| 问题 | 解决思路 |
|------|------|
| 多源异构数据孤岛 | EMPI 与标准化适配，统一患者与业务数据 |
| 初诊信息缺失 | 多模态任务驱动推理与定向补全建议 |
| AI 黑盒与幻觉风险 | RAG 增强、证据引用与规则约束 |
| 术语不一致 | 术语清洗、标准映射与后置规范化 |
| 长时间推理占用资源 | SSE 流式推送、断连感知与资源回收 |

---

## 功能模块

### 应用平台域

- 用户认证与权限控制
- 患者管理与临床视图
- 任务创建、跟踪与结果展示
- 前端交互与 SSE 接收
- 外部医疗系统数据接入与聚合

### RAG 知识库子系统

- 知识库生命周期管理（创建 / 克隆 / 升级申请）
- 文档管理（上传 / 版本 / 回滚 / 差异对比）
- 会话问答主链（流式 SSE + 引用来源 + 医疗免责声明）
- 患者上下文问答（临床摘要脱敏注入，PHI 二次守护）
- 统一 API（OpenAI 风格兼容接口 + API Key 管理）
- ETL 管理（URL / 数据库 / 文件三类来源，PHI 黑名单检查）
- 工具与 Agent（工具注册 / 快捷模板 / LangGraph 节点 trace）
- RAG 治理（规则回答 / 拒答规则 / 敏感词 / 安全审计 / 模型配置）
- 日志与反馈（问答日志落库 / 导出 csv|excel / 反馈导出 jsonl / 归档）

### 智能推理域

- 图像预处理与模态识别
- 病历文本解析
- RAG 检索增强
- 多 Agent 协同推理
- 结构化诊断结果生成

---

## 架构概览

```text
DermaIntegrate
├─ backend-app/   # 应用平台域：Node / Express / MySQL
├─ frontend/      # 应用平台域前端：Vue 3
├─ backend-ai/    # 智能推理域：Python / FastAPI / 推理与检索
├─ infra/        # 容器、网关与部署配置
└─ docs/         # 接口契约与补充文档
```

---

## 技术栈

- **应用平台域**：Vue 3、Node.js、Express、MySQL
- **智能推理域**：Python 3.11、FastAPI、ONNX Runtime、Qdrant、LangGraph
- **基础设施**：Docker、Docker Compose、Nginx

---

## 快速开始

### 1. 环境要求

**应用平台域**
- Node.js 18+
- MySQL 8.0

**智能推理域**
- Python 3.11
- Docker & Docker Compose

### 2. 启动应用平台域

```bash
cd backend-app
npm install
npm run seed
node src/app.js
```

如需启动前端：

```bash
cd frontend
npm install
npm run dev
```

### 3. 配置应用平台域环境变量

在 `backend-app/.env` 中配置：

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
JWT_SECRET=your_jwt_secret
AI_BASE_URL=http://localhost:8000/ai
RAG_AI_BASE_URL=http://localhost:8000
X_INTERNAL_SECRET=your_internal_secret
```

### 4. 启动智能推理域

```bash
cp backend-ai/.env.example backend-ai/.env
docker-compose up -d mysql qdrant
docker-compose up -d --build fastapi
docker exec -it derma-fastapi python init_rag.py
```

初始化内置知识库（首次部署必须执行一次）：

```bash
curl -X POST http://localhost:8000/rag/init/from-docs \
  -H "Content-Type: application/json" \
  -d '{"recreate": false}'
```

### 5. 访问系统

默认前端地址通常为：

```text
http://localhost:3000
```

实际地址以 `Nginx` 或本地开发配置为准。

---

## 接口契约

应用平台域与智能推理域通过以下两类通道交互：

**业务流 1 — 图像诊断**
- `POST /upload`
- `GET /stream/{task_id}`

**业务流 2 — RAG 知识库问答**
- `POST /rag/chat`
- `POST /rag/stream/{conversation_id}`
- `POST /rag/ingest`、`POST /rag/delete-index` 等文档管理接口

详细定义见：

- `docs/api-contract.yaml`
- `docs/API_SPEC.md`

---

## 目录结构

```text
DermaIntegrate/
├─ backend-ai/                  # 智能推理域
│  ├─ agents/                   # Multi-Agent 逻辑
│  ├─ api/                      # FastAPI 路由与 SSE 接口
│  ├─ cnn/                      # 视觉模型推理
│  ├─ modules/
│  │  └─ kb_rag/                # RAG 子系统（检索 / 生成 / 治理 / Agent）
│  ├─ preprocessing/            # DICOM 预处理
│  ├─ rag/                      # 图像诊断用内置知识库
│  └─ init_rag.py               # 知识库初始化脚本
├─ backend-app/                 # 应用平台域后端
│  ├─ src/routes/               # HTTP 路由
│  ├─ src/services/             # 业务逻辑
│  └─ src/db/                   # 数据库连接与初始化
├─ frontend/                    # 应用平台域前端
│  ├─ src/views/                # 页面
│  ├─ src/components/          # UI 组件
│  └─ src/router/              # 路由
├─ infra/                       # 部署配置
└─ docs/                        # 文档与接口契约
```

---

## 协作规范

### 分支建议

- `main`：稳定主线
- `feat/app/*`：应用平台域功能开发
- `feat/ai/*`：智能推理域功能开发

### 开发约定

- 两个域只通过 API 契约交互
- 不要直接调用对方内部实现
- 应用平台域不修改 `backend-ai/`
- 智能推理域不修改 `backend-app/` 和 `frontend/`
- 提交前完成本地自测

---

## 说明

本系统提供的 AI 辅助诊断结果仅供临床参考，最终诊断应由执业医师结合患者实际情况作出。

---

## License

MIT License，详见 [LICENSE](LICENSE)

