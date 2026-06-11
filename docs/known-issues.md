# known-issues.md

> 记录当前已知的契约、代码、联调不一致与风险。
> 状态：🔴 阻塞 / 🟡 风险或待验证 / 🟢 已解决（须有代码/部署/联调验证） / ⬜ 待确认
> 写作规则：见 `docs/writing-rules.md`，每条状态必须注明动作来源。

---

## 契约 vs 代码不一致

### KI-001 `status` 默认值拼写错误
- **位置**：`backend-ai/api/main.py:106`，`SSEResultEvent.status`
- **问题**：默认值为 `"completed"`，v3.1 要求 `"complete"` 或 `"incomplete"`
- **影响**：app 侧 `if status === "complete"` 判断永远失败，降级 UI 永远不触发
- **状态**：🟡 存在分歧，待联调验证
- **依据**：AI 助手 `git show origin/feat/ai/multimodal-agents` 读到第 106 行仍为 `"completed"`（已验证·git show）；用户口头确认已修改（对话）。两者不一致，联调时须二次确认

### KI-002 步骤事件字段名 `msg` → `message`
- **位置**：`backend-ai/api/main.py:208,224,238`
- **问题**：旧版用 `msg`，v3.1 要求 `message`
- **影响**：app 侧读 `event.message` 会得到 `undefined`
- **状态**：🟡 代码已修复，云端部署待确认
- **依据**：`git show origin/feat/ai/multimodal-agents` 读到已是 `message`（已验证·git show）；云端是否已部署该分支，待 curl 确认

### KI-003 事件名 `lab_done` → `pathology_done`
- **位置**：`backend-ai/api/main.py:238`
- **问题**：旧版推送 `step: "lab_done"`，v3.1 要求 `step: "pathology_done"`
- **影响**：app 侧按 `pathology_done` 监听时无法触发病理模块渲染
- **状态**：🟡 代码已修复，云端部署待确认
- **依据**：同 KI-002

---

## 联调风险

### KI-004 AI 服务云端实际在线状态未验证
- **问题**：`http://124.222.0.186/ai` 地址来自契约文档，尚未实际 curl 验证
- **影响**：如果服务未启动，Phase 0 全部阻塞
- **状态**：⬜ 待确认（Phase 0.5 任务）
- **处理**：建分支后第一件事：`curl http://124.222.0.186/ai/health`

### KI-005 云端 Mock 开关状态未知
- **问题**：`USE_MOCK_VLM` 和 `USE_MOCK_INTEGRATION` 的云端实际值不清楚
- **影响**：若两者均为 `false` 且没有配置真实 API Key，推理管线会因 API 调用失败而返回 error 事件
- **状态**：⬜ 待确认
- **处理**：联调时先发只含 `clinical_text` 的请求（不含图片、不含 lab_json），观察返回是否正常

### KI-006 RAG 知识库云端初始化状态未知
- **问题**：不确定云端是否已执行过 `init_rag.py`
- **影响**：若 Qdrant 为空，整合 Agent 的 RAG 检索会返回 0 结果，但系统应能降级（尚未验证降级行为）
- **状态**：⬜ 待确认

### KI-007 `SSEResultEvent` 模型 `status` 字段无枚举约束
- **位置**：`backend-ai/api/main.py:106`
- **问题**：`status: str = "complete"` 是普通字符串，没有枚举校验。整合 Agent LLM 如果返回其他值（如中文"完整"）会直接写入
- **影响**：app 侧 `status === "complete"` 判断可能失效
- **状态**：🟡 风险（非阻塞，建议算法端加 `Literal["complete", "incomplete"]` 类型约束）

---

## 工程端待决策

### KI-008 Node/Express 代理层与业务服务层的职责边界
- **问题**：Node/Express 是否同时承担代理和业务逻辑（EMPI、FHIR、CRUD），或者分两个进程？契约只明确了代理职责，业务部分未说明
- **当前理解（推理得出，待确认）**：
  - 单进程 Node/Express：同时做代理（`/api/tasks/*`）和业务（患者 CRUD、EMPI 路由、FHIR 解析）
  - Vue：纯展示层，只调 Node 接口
- **状态**：⬜ 待确认（建议 Phase 0 前与项目方确认，影响目录结构设计）

### KI-009 应用域数据库 schema 尚未设计
- **问题**：`backend-app/sql/` 在 README 目录树中存在，但实际文件不存在
- **状态**：⬜ Phase 2 任务，尚未开始

### KI-010 `image_done` 步骤中 `coverage` 和 `location` 字段的前端展示方式
- **问题**：v3.1 新增 `coverage`（浮点，病灶覆盖率）和 `location`（纯中文，如"中心"）
- **当前理解**：`coverage` 展示为百分比，`location` 直接渲染
- **状态**：⬜ Phase 6 设计时确认

---

## 已关闭问题

> 暂无
