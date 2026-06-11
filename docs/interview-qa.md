# interview-qa.md — 面试问题库

> 只记录和这个项目直接相关的问题。每轮迭代结束后更新本轮涉及的条目。
> 回答状态：未整理 / 初稿 / 已可面试回答

---

## 1. 项目介绍类

### Q: 这个项目是做什么的，解决了什么问题？
**回答素材**：面向皮肤科门诊的多源数据集成与 AI 辅助诊断平台。解决三个问题：①HIS/PACS/LIS 异构导致数据孤岛，患者标识在各系统不统一；②初诊常缺病理金标准，单模态图像无法支撑精准分期；③端到端模型不透明，LLM 易产生幻觉和英文漂移，临床不可用。系统让医生在一个界面里汇聚多源数据，触发 AI 多模态分析，实时看到推理过程（SSE 步骤流），最终获得可解释的诊断报告。
**设计决策要点**：多模态（图像 + 病历文本 + 病理数据）三路输入，Agent 链分步推理，每步通过 SSE 实时推送。
**回答状态**：初稿

### Q: 你在这个项目里负责哪部分，和合作者怎么协作？
**回答素材**：我负责工程端：Node/Express 代理层（SSE 流式转发、multipart 上传转发、健康检查）、前端 Vue 3 工作站、EMPI 主索引映射、FHIR R4 适配。合作方负责算法端（FastAPI + 多模态 Agent + RAG）。两端进程级隔离，唯一协作通道是一份 v3.1 契约文档，接口变更先改契约再改代码。
**设计决策要点**：进程级隔离保证两端可以独立开发部署，互不干扰。契约文档作为唯一基线，避免口头沟通导致接口不一致。
**回答状态**：初稿

---

## 2. 架构设计类

### Q: 为什么前端不直接调 AI 服务，要多一层 Node/Express？
**回答素材**：有三个原因。①安全：AI 服务 IP 不能暴露给浏览器，`AI_BASE_URL` 只存在服务端环境变量里；②统一鉴权和日志：所有请求都经过 Node 层，方便加 token 校验、请求日志、限流；③跨域隔离：前端只需要访问同域的 Node 服务，不存在 CORS 问题。
**设计决策要点**：这是契约文档中明确约定的架构，Vue 不直接访问 AI 服务是强制约束。
**回答状态**：初稿

### Q: 两个后端（Node/Express 和 FastAPI）怎么协作，边界在哪里？
**回答素材**：边界清晰：FastAPI 只做 AI 推理域（上传、推理、SSE 流输出），Node/Express 只做应用域（代理转发、患者业务、FHIR 适配、前端服务）。两端通过 HTTP API 通信，Node 把前端的请求转发给 FastAPI，再把结果透传回前端。数据库也是物理隔离的：FastAPI 用 MySQL 3307 和 Qdrant，Node 用 MySQL 3306。
**设计决策要点**：进程级、数据库级双重隔离，防止业务逻辑污染推理域。
**回答状态**：初稿

### Q: 这个系统的数据流是什么样的？
**回答素材**：①医生在 Vue 前端填写病历、上传图像；②前端 `POST /api/tasks/upload` 到 Node；③Node 用 multer 解析 multipart，重新构造 FormData，通过 Node 18 内置 fetch 转发给 FastAPI `/upload`；④FastAPI 返回 `task_id`，Node 原样透传给前端；⑤前端拿到 `task_id` 后建立 `EventSource`，连接 Node `GET /api/tasks/:taskId/stream`；⑥Node 用原生 `http` 模块连接 FastAPI SSE 流，chunk 到达就立即 `res.write()` 给前端，不缓冲；⑦前端按事件类型（step/result/error）分别渲染。
**设计决策要点**：upload 和 stream 是分开的两步，用 `task_id` 关联，这样 AI 推理是异步的，upload 立即返回，推理过程通过 SSE 异步推送。
**回答状态**：初稿

---

## 3. AI 联调类

### Q: 怎么确保 app 侧和 AI 侧不会出现接口不一致？
**回答素材**：三个措施：①唯一基线文档——`docs/DermaIntegrate 多模态数据契约 v3.1(1).md`，任何接口变更先改契约再改代码，两端都以此版本为准；②联调测试页面——`test/index.html` 直接打印 SSE 原始事件 JSON，视觉上能立刻发现字段名和字段值的差异；③分歧记录——发现不一致（比如 `"completed"` vs `"complete"`）立即写入 `docs/known-issues.md`，不靠记忆。
**设计决策要点**：契约文档是双向约束，不是 AI 侧单方面定义的。
**回答状态**：初稿

### Q: 联调过程中遇到了什么问题，怎么排查的？
**回答素材**：AI 侧返回 500，通过直接 curl AI 服务定位是上游错误而非代理层 bug；发现 `status` 字段值分歧（`"completed"` vs `"complete"`）通过 git show 读源码确认。另外还有字段名问题：原来是 `msg`，契约要求 `message`；事件名是 `lab_done`，契约要求 `pathology_done`——这两个通过 `git show origin/feat/ai/multimodal-agents:backend-ai/api/main.py` 读到了已修复的代码。
**设计决策要点**：排查思路是把代理层和 AI 层分开验证，先直接 curl AI 服务，确认是否是代理层引入的问题。
**回答状态**：初稿

### Q: AI 推理是同步还是异步的，为什么？
**回答素材**：异步。上传接口 `/upload` 立即返回 202 和 `task_id`，AI 推理在后台运行，结果通过 SSE 流异步推送。原因：多模态推理涉及 VLM 图像分析 + 多个 Agent 串行 + RAG 检索，耗时 10-30 秒甚至更长，同步阻塞对医生体验很差，也容易触发网关超时。异步 + SSE 能让医生看到实时推理进度。
**设计决策要点**：`task_id` 是异步模式的核心，上传和流式读取解耦，允许前端刷新后重新订阅同一个任务的流。
**回答状态**：初稿

---

## 4. Node/Express 代理层问题

### Q: upload 转发怎么实现的，为什么用 multer？
**回答素材**：用 `multer` 解析前端发来的 `multipart/form-data`（图像文件 + 三种文本字段），解析后用 Node 18 内置的 `FormData` + `Blob` 重新构造，再用 `fetch` 转发给 FastAPI。选 multer 因为它是 Node multipart 解析的事实标准，配置简单，内存模式不落盘，适合代理转发场景。
**设计决策要点**：不能直接 pipe 原始请求，因为前端连接的 boundary 和 Node 到 AI 的 boundary 是不同的 HTTP 连接；必须先解析再重新构造。
**回答状态**：初稿

### Q: 你的 Node 服务挂了怎么办，有没有容错？
**回答素材**：当前 Phase 0 没有做容错，这是 Phase 1 要做的。计划是：用 PM2 进程守护自动重启；SSE 断连后前端的 `EventSource` 默认有自动重连机制；upload 接口的 `task_id` 已经在 AI 侧持久化，重连后可以重新 subscribe 同一个 task 的流。
**设计决策要点**：AI 侧推理是幂等的（同一 task_id 多次 subscribe 不会重复推理），这使得代理层重启后客户端重连是安全的。
**回答状态**：初稿

---

## 5. SSE 与流式通信问题

### Q: SSE 是什么，和 WebSocket 有什么区别，为什么选 SSE？
**回答素材**：SSE（Server-Sent Events）是基于 HTTP 的单向推送协议，服务端向客户端推流，客户端只读。WebSocket 是全双工双向通信。选 SSE 的原因：①AI 推理结果只需要服务端推给前端，没有前端向 AI 发送消息的需求，SSE 语义更合适；②SSE 基于普通 HTTP，不需要协议升级，Nginx 代理更简单（`proxy_buffering off` 就够）；③浏览器原生支持 `EventSource`，不需要额外库；④AI 侧契约文档已经定义了 SSE 格式，技术栈已锁定。
**设计决策要点**：如果未来有前端向 AI 发消息的需求（如实时调整推理参数），才需要考虑 WebSocket。
**回答状态**：已可面试回答

### Q: Node/Express 怎么实现 SSE 流式代理，有什么坑？
**回答素材**：用原生 `http` 模块建立到 AI 的连接，将响应 chunk 直接 `res.write()` 给客户端，不缓冲。坑：`url.port` 为空字符串时须用 `parseInt` 避免类型问题；代理超时需大于 AI 推理耗时（10-30s）。
**设计决策要点**：不用 `http-proxy-middleware` 是因为它对 SSE 需要额外配置 `selfHandleResponse`，反而容易出现缓冲问题。原生 `http` 模块 pipe 更直接可控。
**回答状态**：已可面试回答

### Q: 如果客户端断开连接，服务端怎么处理？
**回答素材**：监听 `req.on('close')`，触发时调用 `aiRequest.destroy()`，AI 侧的推理线程通过 cancel_event 感知断连后终止。同时也监听了 `req.on('error')` 做同样的清理，防止异常断连的情况。
**设计决策要点**：如果不主动 destroy，AI 侧推理会跑完整个流程做无效计算，浪费 GPU 资源。
**回答状态**：已可面试回答

### Q: SSE 的 heartbeat 有什么用，你怎么处理的？
**回答素材**：heartbeat 是 AI 侧周期性发送的空事件，作用是防止代理层/Nginx/CDN 因为长时间无数据传输而断开 TCP 连接（很多负载均衡器有 60s 空闲超时）。前端的处理：`test/index.html` 里注册了 `heartbeat` 事件监听器但不做任何展示，只是消费掉，避免触发 `EventSource` 的默认错误处理。
**设计决策要点**：Node 代理层不需要处理 heartbeat，直接透传即可，前端静默消费。
**回答状态**：初稿

---

## 6. 前端状态管理问题

### Q: 前端怎么处理步骤事件不按顺序到来的情况？
**回答素材**：契约规定的设计原则是"收到什么渲染什么"，不假设步骤顺序。具体做法：每个 step 事件触发独立的 UI 模块展示（image_done 展示图像模块，clinical_done 展示病历模块，pathology_done 展示病理模块），各模块之间没有依赖关系，不会因为某个步骤缺失而阻塞渲染。
**设计决策要点**：这是 Phase 6 的实现目标，目前 test/index.html 里是按时间顺序追加事件列表，Vue 组件里的状态机实现待开发。
**回答状态**：初稿

### Q: 什么是"降级报告"，前端怎么展示？
**回答素材**：当某个模态数据缺失（比如没有上传图像，或者病理数据不完整），AI 侧仍会完成推理，但 result 事件里的 `status` 字段值为 `"incomplete"` 而非 `"complete"`，报告会注明哪个模块数据缺失、置信度受影响。前端通过 `status` 字段区分渲染样式，`incomplete` 用警示色，并展示缺失字段说明。
**设计决策要点**：降级报告让系统在单模态输入时也能给出有价值的参考，而不是直接报错拒绝。这是这个项目相比于单纯分类模型的重要工程价值。
**回答状态**：初稿

---

## 7. 错误处理与稳定性问题

### Q: AI 服务返回 error 事件时，你的系统怎么响应？
**回答素材**：`stream.js` 里监听了 `aiResponse.on('error')` 和 `aiRequest.on('error')` 两种错误。AI 侧如果推流过程中出错，Node 代理会向前端写入 `event: error\ndata: {...}\n\n` 并关闭连接。前端的 `EventSource` 监听了命名的 `error` 事件，收到后显示错误提示并调用 `currentEventSource.close()`。注意：命名的 `error` 事件（AI 推理业务错误）和 `onerror` 回调（SSE 连接断开）是不同的，前端分别处理。
**设计决策要点**：把业务错误用命名事件（`event: error`）表达，而不是直接断连，让前端能拿到错误详情（error_code 和 message）。
**回答状态**：初稿

### Q: 如果 AI 推理超时怎么办？
**回答素材**：当前 Phase 0 的 `stream.js` 没有设置显式超时，这是 Phase 1 任务 1.1 要解决的。Node http.request 默认没有超时，需要加 `aiRequest.setTimeout()`，超时时向前端发 error 事件后关闭。SSE 代理的超时阈值必须大于 AI 推理的最大耗时（30s），设置为 5 分钟。
**设计决策要点**：超时值不能设太短，AI 的多模态 Agent 链在高负载下可能接近 30 秒。
**回答状态**：初稿

---

## 8. 为什么这样做 / 为什么不用别的方案

### Q: 为什么不用 WebSocket 而用 SSE？
**回答素材**：契约文档已经定义 AI 侧用 SSE 格式输出，技术栈已锁定。即使重新选择，SSE 也更合适：推理结果是单向的服务端推流，不需要全双工；SSE 基于 HTTP/1.1，Nginx 代理配置简单；浏览器原生 `EventSource` 支持自动重连；连接管理比 WebSocket 简单。WebSocket 的优势在于低延迟双向通信，这个场景不需要。
**设计决策要点**：
**回答状态**：已可面试回答

### Q: 为什么不用 Spring Boot 做后端？
**回答素材**：契约文档明确指定 Vue + Node/Express，技术栈由双方在项目启动时约定，主要考虑是工程端侧重轻量代理而非重型业务框架。
**设计决策要点**：
**回答状态**：初稿

### Q: 为什么 Node 里不直接用 `http-proxy-middleware`？
**回答素材**：`http-proxy-middleware` 对 SSE 需要额外配置 `selfHandleResponse: true`，否则它会缓冲响应再转发，导致 SSE 事件不实时。原生 `http` 模块 pipe 更直接，chunk 到达立即 `res.write()`，没有缓冲中间层，行为更可预期，出问题也更容易排查。
**设计决策要点**：
**回答状态**：已可面试回答

---

## 9. 你在项目中的个人贡献

### Q: 你具体做了哪些技术决策？
**回答素材**：①用原生 `http` 模块而非 `http-proxy-middleware` 做 SSE 代理；②选 multer 内存模式处理 multipart，不落盘，直接用 Node 18 内置 `Blob` + `FormData` 重构转发；③联调测试页面（`test/index.html`）的设计，让双方可以独立验证 SSE 格式正确性，不依赖前端 Vue 开发完成；④发现 `url.port` 空字符串问题，加 `parseInt(...) || defaultPort` 防御；⑤断连处理：同时监听 `req.on('close')` 和 `req.on('error')` 两个事件，两种情况都销毁上游连接。
**设计决策要点**：
**回答状态**：初稿

---

## 10. 项目亮点与难点

### Q: 这个项目最难的地方是什么？
**回答素材**：两个难点。①SSE 流式代理的正确性：中间有 Nginx 反代、Node 代理、浏览器三层，每一层都可能缓冲数据。原生 `http` 模块保证了 Node 层不缓冲，但 Nginx 需要 `proxy_buffering off`，这个配置是 Phase 8 才做，目前只有本地直连验证。②契约对齐：两端独立开发，字段名/字段值的细节分歧（如 `"completed"` vs `"complete"`）只有在联调时才能发现，事先很难完全对齐，需要有系统的问题追踪机制（known-issues.md）和可独立验证的测试页面。
**设计决策要点**：
**回答状态**：初稿

### Q: 项目里有哪些值得说的工程实践？
**回答素材**：①事实状态三档（`writing-rules.md`）：文档里每条结论必须标注"已验证/推理得出/待确认"，防止把规划描述写成已完成实现；②联调测试页面独立于前端框架：`test/index.html` 是纯 HTML + 原生 JS，不依赖 Vue 构建，随时可以跑；③进程级双域隔离 + 契约文档作为唯一基线：两人可以完全独立开发，互不 review 对方代码；④known-issues.md 即时记录分歧，不靠记忆和口头约定。
**设计决策要点**：
**回答状态**：初稿
