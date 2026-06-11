# 智能推理域 (AI) 接口联调契约 v3.1

**基础 URL**：`http://124.222.0.186/ai`（通过 app 侧配置项统一管理，Node/Express 使用 `AI_BASE_URL` 访问 AI 服务；前端 Vue 不直接写死 AI 地址。）

**交互协议**：推理接口采用 SSE (Server-Sent Events) 长连接流式响应。app 侧技术栈确定为 **Vue + Node/Express**，调用路径固定为 **Vue -> Node/Express -> AI Service**。

**app 侧联调主线**：统一基于 **`task_id + SSE`**。前端页面不直接依赖 AI 内部实现，只依赖共享接口契约。

**⚠️ v3.1 核心架构升级说明**：
1. **专科化重构**：病历 Agent 已对齐 PAD-UFES-20 真实数据集；原“化验 Agent”已彻底替换为“病理与分子 Agent”，对齐 TCGA-SKCM / AJCC 8th 分期标准。
2. **全中文防线**：AI 推理域全线强制纯中文输出，严禁返回 `male/melanoma/SLNB` 等英文术语，前端可直接渲染。
3. **动态缺失兼容**：系统支持任意模态缺失。SSE 流采用动态窗口机制，前端必须基于收到的步级事件按需渲染，**严禁硬编码期待所有步骤事件都出现**。
4. **报告降级标识**：最终报告新增 `status: "incomplete" / "complete"` 字段，标识核心金标准是否缺失，前端必须据此进行 UI 降级提示。

**⚠️ app 侧开发约束**：

1. app 侧技术栈固定为 **Vue + Node/Express**。
2. Vue 只调用 app 侧接口，不直接拼接或依赖 AI 服务公网地址。
3. Node/Express 负责：
   - 转发上传请求
   - 代理 SSE 流
   - 统一超时、错误、日志处理
   - 统一管理 `AI_BASE_URL`
4. 前端与 Node 侧开发时，必须直接适配 v3.1 契约。

**请工程端务必按照新契约适配，旧版 v2.0 代码将无法解析！**

---

## 1. 多模态数据上传

- **接口**：`POST /upload`
- **Content-Type**：`multipart/form-data`
- **请求参数**（全可选，但至少需提供一项）：

| Key | Type | Required | Description | v3.1 变更说明 |
| :-- | :-- | :-- | :-- | :-- |
| `file` | File | No | 皮肤镜影像，支持 PNG/JPG 格式 | 无 |
| `clinical_text` | Text | No | 病历自由文本 | 无 |
| `clinical_json` | Text | No | 结构化病历 JSON 字符串 | **⚠️ 破坏性变更：Schema 必须对齐 PAD-UFES-20**（见下方示例） |
| `lab_json` | Text | No | 病理与分子数据 JSON 字符串 | **⚠️ 破坏性变更：字段名仍叫 `lab_json` 以兼容数据库，但内部语义已变更为病理分期与分子靶向数据**（见下方示例） |

**`clinical_json` 请求示例（对齐 PAD-UFES-20）**：

```json
{
  "patient_info": {"age": 65, "gender": "男"},
  "lesion_clinical": {"region": "左足底", "diameter_1_mm": 15.0, "elevation": true},
  "lesion_symptoms": {"itch": true, "grew": true}
}
```

**`lab_json` 请求示例（对齐 TCGA-SKCM/AJCC 8th）**：

```json
{
  "breslow_thickness_mm": 5.2,
  "ulceration": true,
  "braf_mutation": "突变型",
  "lymph_node_status": null
}
```

- **成功响应（202 Accepted）**：

```json
{
  "task_id": "08662db1-669d-4630-8905-b8dd762f15f1",
  "status": "accepted"
}
```

⚠️ **核心约束**：
1. 后续建立 SSE 连接的路径参数**必须且只能使用 `task_id`**，**严禁使用**旧的 `image_uid`。
2. 响应体中不再返回 `image_uid`、`filename` 等影像专属字段。

⚠️ **app 侧实现要求**：

1. Vue 表单提交目标固定为 Node/Express 提供的 app 接口，例如：`POST /api/tasks/upload`。
2. Node/Express 收到请求后，再转发到 AI 原始接口 `POST /upload`。
3. 如果用户没有上传文件，则 **不要传空的 `file` 字段**。
4. `clinical_json`、`lab_json` 在前端若以对象形式维护，提交前必须序列化为字符串。
5. app 侧上传成功后，只保存和传递 `task_id`；不要以 `image_uid` 设计主流程。

---

## 2. 获取 AI 结构化报告（SSE 流）

- **接口**：`GET /stream/{task_id}`
- **路径参数**：`task_id`（String）— 由上传接口返回。
- **响应类型**：`text/event-stream`

### 2.1 SSE 协议规范

服务端推送的 SSE 消息严格遵循以下格式：

```text
event: <event_type>\ndata: <json_string>\n\n
```

应用域需根据 `event` 字段分发处理逻辑。

**⚠️ app 侧实现要求**：

1. Vue 不直接消费 AI SSE，统一通过 Node/Express 暴露的 app 接口消费，例如：`GET /api/tasks/:taskId/stream`。
2. Node/Express 必须按**流式**方式代理 SSE，不得把整条响应读完后再返回。
3. 前端收到 `event` 后，必须根据事件类型动态更新界面；不得假设所有步骤按固定顺序出现。
4. 页面离开、任务切换、组件销毁时，前端必须主动关闭 SSE 连接。

### 2.2 事件类型与数据契约（⚠️ 重大重构）

#### ① `step` 事件（中间推理流）

推理过程中按需触发，携带当前模态的产出物，用于前端实时渲染各模态的解析进度。**注意：根据上传数据的不同，以下 step 事件可能只触发部分，顺序不固定，前端必须采用动态渲染窗口。**

**Step：视觉定位与形态学（`image_done`）**  
触发条件：上传了 `file`。  
*变更说明：新增 `coverage` 和 `location` 纯中文特征字段。*

```json
{
  "step": "image_done",
  "message": "视觉定位与形态学完成",
  "data": {
    "image_url": "/ai-static/heatmaps/img_xxx_evidence.png",
    "morphology": {
      "border": "不规则，呈地图样改变",
      "pigment_network": "非典型色素网络，呈局灶性增粗",
      "color_distribution": "多色不均匀，混杂棕色与黑色区域",
      "vascular_pattern": "点状不规则血管",
      "special_structures": "未见明显特殊结构"
    },
    "coverage": 0.25,
    "location": "中心"
  }
}
```

**Step：病历解析（`clinical_done`）**  
触发条件：上传了 `clinical_json` 或 `clinical_text`。  
*⚠️ 破坏性变更：数据结构完全重构为 PAD-UFES-20 标准，强制全中文输出。*

```json
{
  "step": "clinical_done",
  "message": "病历结构化解析完成",
  "data": {
    "patient_info": {"age": 65, "gender": "男", "fitzpatrick_skin_type": null},
    "lifestyle_history": {"smoke": false, "drink": false, "pesticide_exposure": false},
    "family_history": {"background_father": null, "background_mother": null},
    "personal_history": {"skin_cancer_history": false, "other_cancer_history": false},
    "lesion_clinical": {"region": "左足底", "diameter_1_mm": 15.0, "diameter_2_mm": null, "elevation": true, "biopsed": false},
    "lesion_symptoms": {"itch": true, "hurt": false, "changed": true, "bleed": false, "grew": true}
  }
}
```

**Step：病理与分子规则引擎（`pathology_done`）**  
触发条件：上传了 `lab_json`（即病理数据）。  
*⚠️ 破坏性变更：事件名从 `lab_done` 变更为 `pathology_done`。数据结构变更为精准 T 分期与靶向建议。*

```json
{
  "step": "pathology_done",
  "message": "病理与分子规则引擎完成",
  "data": {
    "t_stage": "T4b",
    "treatment_recommendations": [
      "目前分期为T4b，强烈建议行前哨淋巴结活检(SLNB)明确淋巴结状态",
      "BRAF V600突变阳性，推荐靶向治疗方案(达拉非尼+曲美替尼)",
      "肢端型黑色素瘤侵袭性可能更强，建议密切随访及考虑基因检测(如KIT突变)"
    ],
    "missing_data_warnings": []
  }
}
```

**app 侧事件适配要求（新增明确）**：

- step 子类型必须按 v3.1 处理：
  - `image_done`
  - `clinical_done`
  - `pathology_done`
- 旧版字段和事件名不得再使用：
  - 不再使用 `lab_done`
  - 不再使用 `msg`
  - 统一使用 `message`
- 前端 UI 应采用“收到什么渲染什么”的策略：
  - 收到 `image_done` 再渲染图像模块
  - 收到 `clinical_done` 再渲染病历模块
  - 收到 `pathology_done` 再渲染病理模块
- 不允许写死“必须先后出现全部步骤”的流程判断。

#### ② `result` 事件（成功终结）

所有可用模态处理完毕，由整合 Agent 汇总生成最终结构化报告。  
*⚠️ 核心变更：新增 `status` 字段标记报告完整性；`source_id` 变更为带前缀的强引用格式；全管线强制纯中文输出。*

```json
{
  "task_id": "08662db1-...",
  "risk_level": "极高危",
  "key_concerns": [
    {"item": "病理分期T4b，提示肿瘤厚度大于4毫米伴溃疡", "source_id": "[AJCC-05]"},
    {"item": "BRAF基因突变阳性", "source_id": "[NCCN-05]"}
  ],
  "recommendations": [
    {"item": "强烈建议行前哨淋巴结活检以明确淋巴结状态", "source_id": "[AJCC-05]"},
    {"item": "推荐达拉非尼联合曲美替尼靶向治疗", "source_id": "[NCCN-05]"}
  ],
  "differential": ["肢端型黑色素瘤", "肢端色素痣恶变"],
  "disclaimer": "本系统结果仅供临床参考，不具有最终诊断效力，请执业医师结合临床判断",
  "status": "complete"
}
```

**`status` 字段说明（前端必须适配）**：

- `"complete"`：核心确诊数据（如病理 Breslow 厚度）完整，报告可供参考。
- `"incomplete"`：核心金标准数据缺失，系统降级输出。**前端必须在此状态下显式提示医生“报告因数据缺失降级，建议完善相关确诊检查”**，且渲染样式需与 `complete` 状态区分（如置灰或加警告边框）。

**app 侧结果渲染要求（新增明确）**：

- 前端必须根据 `status` 区分完整报告与降级报告。
- 若 `status === "incomplete"`：
  - 显示明显警告提示
  - 视觉样式与正常结果区分
  - 提醒用户补充检查/补充数据
- `source_id` 直接按后端返回内容显示，不在前端自行拼接。

#### ③ `error` 事件（业务异常）

推理失败或证据链断裂时推送。

```json
{
  "error_code": "INFERENCE_FAILED",
  "message": "具体错误信息"
}
```

**app 侧错误处理要求**：

1. 收到 `event: error` 后，前端必须显示友好错误提示。
2. 不得因为单次 AI 错误导致页面崩溃。
3. 应保留已收到的 `step` 内容，并允许用户重新发起任务。

#### ④ `heartbeat` 事件（连接保活）

防止中间件静默断连，应用域收到后仅需忽略或刷新超时计时器，无需向业务层透传。

---

## 3. 静态资源访问规则

SSE 返回的图片路径均为相对路径，前端渲染时不得写死公网 IP，必须通过 app 侧配置拼接完整地址。

- **Node/Express 直连 AI 静态资源时规则**：`AI_BASE_URL` + `相对路径`
- **若 Node/Express 已做静态资源代理**：前端直接走 app 域名即可
- **示例**：`http://localhost:8000/ai-static/heatmaps/img_xxx_evidence.png`

**app 侧实现要求（新增明确）**：

- Vue 组件不得直接写 `http://124.222.0.186` 这类公网地址。
- 图片访问地址统一由以下任一方式处理：
  - Node/Express 代理层处理
  - 前端配置项统一拼接
- 本地开发、测试环境、生产环境必须可通过配置切换，不得改代码硬编码。

---

## 4. Vue + Node/Express 联调约束

- **超时配置**：AI 推理耗时约 10-30 秒，Node/Express 代理 SSE 时的读取超时时间必须设置为 **大于 5 分钟**，防止长连接被提前切断。
- **流式代理**：Node/Express 必须以流式方式转发 SSE，禁止整包缓存后一次性返回。
- **异常降级**：若收到 `event: error`，前端必须展示友好错误状态，不得直接抛出未处理异常。
- **动态渲染约束**：前端解析 `step` 事件时，严禁硬编码事件顺序或期待所有 step 都出现。必须基于 `step` 的值（`image_done`、`clinical_done`、`pathology_done`）动态挂载渲染组件，无该事件则不渲染对应模块。
- **全中文直出**：AI 推理域已实施全中文强制防线，所有输出均为规范中文。前端若存在旧版英文词典映射必须移除，直接渲染中文即可。
- **强引用展示**：`result` 事件中的 `source_id` 现为带前缀格式（如 `[AJCC-05]`），前端展示引用来源时应直接显示，不再自行加工。
- **连接关闭**：用户离开页面、切换任务或组件销毁时，前端必须主动关闭 SSE 连接；Node/Express 也应回收下游无效连接。
- **app 侧固定接口设计**：建议 app 侧至少暴露：
  - `POST /api/tasks/upload`
  - `GET /api/tasks/:taskId/stream`
- Vue 只调用这两个 app 接口，不直接调用 AI 原始接口。
- **旧版字段禁用**：app 侧代码中不得继续使用下列旧版字段/事件：
  - `lab_done`
  - `msg`
  - 旧版固定步骤数组逻辑
- **当前开发基线**：app 侧从现在开始统一以 v3.1 为唯一联调基线开发，不再兼容 v2.0。
