# knowledge-base.md — 技术决策与排坑记录

> 记录本项目的关键技术决策、已踩的坑和对应解法。供面试准备和后续开发参考。
> 状态标记同 writing-rules.md：✅ 已验证 / 🔶 推理得出 / ⬜ 待确认

---

## SSE 流式代理

### 为什么用原生 `http` 模块而非 `http-proxy-middleware`
`http-proxy-middleware` 处理 SSE 需要设置 `selfHandleResponse: true`，否则它会缓冲完整响应再转发，SSE 事件无法实时到达客户端。原生 `http` 模块在 `aiResponse.on('data')` 回调里直接 `res.write(chunk)`，没有任何缓冲中间层，行为完全可预期。
**来源**：✅ 已验证·读源码（`backend-app/src/routes/stream.js`）

### `url.port` 空字符串防御
`new URL(...)` 解析 URL 时，如果 URL 中没有显式端口号（如 `http://host/path`），`url.port` 返回空字符串 `""`，直接传给 `http.request` 的 `port` 选项会导致请求失败。解法：`parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80)`。
**来源**：✅ 已验证·读源码（`backend-app/src/routes/stream.js:22`）

### 客户端断连的双重监听
同时监听 `req.on('close')` 和 `req.on('error')`，两种情况都调用 `aiRequest.destroy()`。只监听 `close` 不够，网络异常断连可能只触发 `error` 不触发 `close`。
**来源**：✅ 已验证·读源码（`backend-app/src/routes/stream.js:71-78`）

---

## multipart 上传转发

### multer 内存模式 + Node 18 原生 FormData
multer 配置 `multer()`（无存储选项）默认使用内存存储，文件存在 `req.files[x][0].buffer`。转发时用 `new Blob([file.buffer], { type: file.mimetype })` 包装后 `FormData.append()`，不落盘，适合代理转发场景。Node 18+ 内置 `Blob`、`FormData`、`fetch`，无需额外依赖。
**来源**：✅ 已验证·读源码（`backend-app/src/routes/upload.js`）

### 为什么不能直接 pipe 原始请求
前端到 Node 和 Node 到 AI 是两个独立的 HTTP 连接，multipart boundary 不同。必须先用 multer 解析，再重新构造 FormData 转发。
**来源**：🔶 推理得出·来自 HTTP multipart 协议规范

---

## 契约对齐

### 已发现的字段分歧（Phase 0 联调前）

| 字段 | 旧值（AI 侧原代码） | 契约要求 | 状态 |
| :--- | :--- | :--- | :--- |
| 错误信息字段名 | `msg` | `message` | 🟡 git show 已验证修复；云端部署待确认 |
| 任务完成事件名 | `lab_done` | `pathology_done` | 🟡 git show 已验证修复；云端部署待确认 |
| result 状态值 | `"completed"` | `"complete"` / `"incomplete"` | 🟡 用户口头确认已修改；AI 助手 git show 读到仍是 `"completed"`，存在分歧，联调时需二次验证 |

**排查方法**：`git show origin/feat/ai/multimodal-agents:backend-ai/api/main.py`

---

## Node/Express 代理层架构决策

### 为什么要有 Node 中间层
- AI 服务 IP 不暴露给浏览器（安全）
- 统一鉴权、日志、限流入口
- 前端只需访问同域 Node 服务，无 CORS 问题
- 契约文档强制约束：Vue 不直接访问 AI 服务

### 应用域与推理域数据库物理隔离
- 推理域：MySQL 3307（FastAPI 使用）
- 应用域：MySQL 3306（Node/Express 使用，Phase 2 实现）
- 两者不共用，防止业务逻辑污染推理域数据

---

## Nginx 配置（Phase 8，待实现）

SSE 长连接需要在 Nginx 配置中加：
```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 300s;
```
⬜ 待确认：云端 Nginx 当前配置是否已有这些设置。

---

## 联调测试策略

### test/index.html 独立于 Vue 框架
纯 HTML + 原生 JS，不依赖构建工具，任意时候可以直接在浏览器里跑。用途：验证 SSE 事件格式是否符合 v3.1 契约，不需要等 Vue 前端开发完成。
**来源**：✅ 已验证·读源码（`test/index.html`）

### 命名 error 事件 vs EventSource.onerror
- `addEventListener('error', ...)` 监听 AI 侧业务错误事件（有 `error_code` 和 `message` 字段）
- `onerror` 回调响应 SSE 连接断开或网络错误
- 两者不同，必须分别处理
**来源**：✅ 已验证·读源码（`test/index.html:208-221`）
