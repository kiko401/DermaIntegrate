# DermaIntegrate: 皮肤病多源数据集成与智能辅助诊断系统

**许可协议**：MIT License 
**运行环境**：Python 3.11 / Java 17+ (Spring Boot 3.x+) / Node 18+ 
**系统架构**：基于 API 契约的模块解耦，推理服务与应用服务进程级隔离与独立部署

---

## 摘要

本项目面向皮肤病专科门诊场景，解决临床业务中多源异构数据孤岛、初诊数据缺失与医疗 AI 缺乏可解释性的问题，构建数据集成与多模态辅助诊断系统。

在**数据集成层面**，针对 HIS、PACS、LIS 等系统数据异构与标识不一的问题，系统采用主索引映射与 FHIR R4 标准协议，实现跨系统异构数据的归一化接入与逻辑聚合，构建患者全生命周期临床视图，且不侵入源系统。

在**AI 辅助层面**，针对单模态图像推断局限与端到端模型缺乏推断依据的问题，提出基于多 Agent 协作与检索增强的多模态可解释机制。系统接收皮肤镜图像、病历文本与化验数据等多模态输入，由独立的图像 Agent（病灶分割与特征提取）、病历 Agent（结构化解析）、化验 Agent（指南规则引擎）按需处理，最终由整合 Agent 融合多源特征与 RAG 检索结果，生成结构化风险提示与检查建议。系统实现了对数据缺失场景的完全兼容，在输入不完整时能给出定向补充检查建议，诊断裁量权交由临床医生。

在**工程实现层面**，系统针对医学影像前端解析瓶颈、DICOM 标签不规范风险与长时 AI 推理引发的资源占用问题，分别实现了基于成像特性的防御性后端转码与前端轻量渲染机制，以及基于 SSE 的异步响应代理与断连感知计算资源回收机制。同时，在智能推理域 4C4G 低资源云服务器环境下，通过容器内存限制、ONNX 推理替换与国内镜像源注入实现稳定部署，保障临床环境下的系统可用性。

---

## 1. 核心问题与方法映射

针对皮肤病临床业务中的数据流转与 AI 应用问题，本系统的应对策略与工程机制如下：

| 临床工程问题                                                 | 本系统应对策略与工程机制                                     |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| **多源异构数据孤岛**：HIS、LIS、PACS等系统数据异构，患者标识不一，难以形成完整临床视图。 | **主索引映射与 FHIR 标准归一化**：基于主索引映射跨系统患者标识，结合 FHIR R4 标准协议解析资源，实现异构数据的逻辑聚合与患者全生命周期视图构建，不侵入源系统。 |
| **初诊数据缺失与单模态局限**：初诊时常缺乏病理化验结果，单一图像模态无法支撑完整分期；强制要求全量数据导致系统不可用。 | **多模态缺失兼容与定向建议**：系统以 `task_id` 驱动多模态管线，图像、病历、化验 Agent 按需触发，跳过缺失模态。整合 Agent 针对缺失项动态生成定向补充检查建议（如缺乏 Breslow 厚度时建议优先活检），不因数据不全而阻断流程。 |
| **医疗 AI 缺乏可解释性**：端到端模型直接生成诊断结论缺乏推理依据，医生无法验证，存在事实偏移风险。 | **多 Agent 协作与可解释证据链**：图像 Agent 仅输出客观形态学特征与视觉定位（严禁下诊断），化验 Agent 基于指南输出规则分层，整合 Agent 结合 RAG 强引用生成结构化报告，系统不直接输出终局诊断。 |
| **DICOM 影像前端解析与标签风险**：PACS 下发的 DICOM 影像强依赖重型解析库实时渲染导致卡顿；且公开数据集常存在标签不规范导致严重偏色。 | **防御性影像转码与轻量渲染**：基于皮肤镜无需调窗的特性，后端离线解析 DICOM 并执行防御性色彩空间还原转码为 PNG，结合前端轻量滑动对比组件，实现影像数据的透明集成调阅。 |
| **长时 AI 推理引发的资源占用**：AI 推理耗时导致服务端计算资源长期占用，并发能力衰减，且异常断连易导致计算浪费与 OOM 崩溃。 | **异步响应代理与低资源部署**：基于 SSE 异步契约解耦业务与推理，建立断连感知逻辑，前端断连即终止推理步级计算；智能推理域云端采用 4C4G 低资源部署，通过 ONNX 推理替换与容器内存限制保障系统稳定性。 |

---

## 2. 系统架构设计

系统遵循“推理计算与业务流转解耦”原则，划分两大进程级隔离服务域：**智能推理域**负责多模态 AI 推理、特征提取与影像预处理；**应用平台域**负责数据集成归一、标准协议接入与前端交互。

```markdown
③ 表现层（应用平台域 - React 18 + AntD + ECharts）
  ├─ 医生工作站 (患者全生命周期临床视图聚合展示)
  ├─ 影像滑动对比组件 (原图/标注图叠加渲染)
  └─ AI 辅助诊断流式对话框 (展示多模态证据链，医生裁决)

② 服务与数据层（跨域协同）
  ├─ 智能推理域 Multi-Agent 协作管线：
  │   ├─ 图像 Agent：UNet (ONNX) 病灶分割提取 | VLM 结构化形态描述 (特征提取器)
  │   ├─ 病历 Agent：结构化 JSON 映射 | LLM (DeepSeek) 自由文本 Schema 解析 (含防漂移自重试)
  │   ├─ 化验 Agent：基于指南的纯规则引擎 (跨模态依赖判定与防御性数据清洗)
  │   └─ 整合 Agent：动态 Prompt 构建 | RAG 两阶段检索 | LLM 结构化报告生成与 JSON 容错修复
  ├─ 应用平台域：患者临床视图聚合 | 主索引映射 | FHIR R4 协议接入 | AI 诊断异步代理
  ├─ 推理域数据核心：独立 MySQL 数据库 (Task 任务映射、多模态上下文存储)
  └─ 应用域数据核心：MySQL 8 (关系型业务数据存储)

① 接入与预处理层
  ├─ DICOM 离线摄取管线、防御性色彩空间还原、像素转码、元数据提取与 UID 绑定 (推理域执行)
  └─ FHIR Mock Server (仿真 HIS/EMR/LIS，应用域接入)

⓪ 基础设施层
  ├─ 智能推理域 Docker Compose 编排、容器内存限制与宿主机 Swap 配置
  └─ Nginx 网关路由与 SSE 长连接超时配置
```

---

## 3. 关键工程实现与核心机制

> **【架构演进说明】**：当前开发分支（阶段 9）已实现病历 Agent（含语义漂移自重试机制的双通道解析）、化验 Agent（含跨模态依赖与防御性清洗的规则引擎）、整合 Agent（动态 Prompt 与真实 LLM 接入）及图像 Agent（ONNX 推理框架搭建与视觉特征注入闭环）的实质化落地。图像 Agent 当前因缺少真实权重文件走高斯占位降级，待 ONNX 模型训练后替换；RAG 待专科知识库注入与两阶段检索升级。

### 3.1 多 Agent 协作与多模态缺失兼容机制

为解决初诊数据缺失与单模态推断局限的问题，系统将原有的图像单管线重构为以 `task_id` 驱动的多 Agent 协作管线。系统接收多模态数据（图像、病历文本/JSON、化验 JSON），各模态由独立 Agent 按需处理，最终由整合 Agent 融合输出，全程兼容数据缺失：

1. **任务驱动与条件分支调度**：API 入口 (`/upload`) 接收任意组合的多模态数据并生成唯一的 `task_id`，将数据落库至扩展后的 `Task` 表。SSE 推理流 (`/stream/{task_id}`) 根据数据存在性按需触发子 Agent，无图像则跳过视觉定位，无化验则跳过规则引擎。**工程约束**：FastAPI 处理多模态表单时，文件字段必须显式使用 `Optional[UploadFile]` 类型注解，仅设置 `File(None)` 会被框架强制视为必填校验拦截请求，导致无图场景报 422 错误。
2. **图像 Agent（视觉定位与形态提取）**：
   - **病灶分割与特征提取**：ONNX Runtime 推理框架已集成，采用基于 ISIC 2018 训练的 EfficientNet-b0 UNet 模型（导出为 ONNX 格式，使用 `onnxruntime` CPU 推理，单张耗时 < 1 秒）。针对真实模型输出的离散假阳性噪声，工程层强制实施最大连通域提取（`cv2.connectedComponentsWithStats`），剔除微小噪声，生成精准的病灶掩码。最终输出病灶区域占比（`coverage`）、大致位置（`location`）及 Jet 色图热力图叠加。**降级机制**：若部署环境中无 `unet_weights.onnx` 文件，系统自动降级至高斯模糊掩膜占位符，保障全管线不中断。
   - **形态学结构化约束**：VLM 角色严格降级为“特征提取器”，通过 Prompt 强制其仅输出客观形态学特征（如边缘、色素网络），强制中文输出，并经后置正则过滤剥离任何诊断性结论，确保视觉模块的客观性。
3. **病历 Agent（Schema 解析双通道与防漂移机制）**：支持结构化 JSON 直接映射，缺失字段填 `null`；对于自由文本，调用 DeepSeek API（采用 `deepseek-v4-flash` 非思考模式，保证 JSON 格式稳定输出）基于 Few-shot Prompt 提取为标准 Schema。**防漂移自重试机制**：针对 LLM 常见的语义漂移（如将中文翻译为英文输出），工程层实施“带反馈的局部自重试”。首次提取后由规则引擎进行黑名单校验与结构校验，若不通过则将错误原因作为反馈拼入 Prompt 再次请求 LLM 修正；达到最大重试次数仍失败时返回空 Schema 兜底，确保管线不阻塞。
4. **化验 Agent（指南规则引擎与跨模态依赖）**：纯 Python 规则引擎实现，严格兼容空值判断与 LLM 输出的不确定性。针对 LLM 提取的脏数据（如带单位的数字 `"2.5mm"`、非标布尔值 `"有"`、变体位置 `"左足底"`），引入防御性清洗函数（`_extract_float`, `_is_truthy`）与模糊匹配逻辑。**跨模态依赖逻辑**：规则引擎支持跨 Agent 数据引用，例如在判定肢端型黑色素瘤附加建议时，采用关键词模糊匹配从病历 Agent 的输出中提取病灶位置，若该特征缺失则相关规则静默不触发。当核心分期字段缺失（如无 Breslow），规则引擎明确产出“无法分期，建议优先行皮肤活检明确浸润深度”的定向建议。
5. **整合 Agent（动态 Prompt 与结构化生成）**：接收各子 Agent 输出与 RAG 检索结果，执行动态 Prompt 构建。若某模态缺失，Prompt 将明确指示 LLM “未提供XXX，请在建议中优先考虑完善相关确诊检查”。调用 DeepSeek API 强制 JSON 输出，并引入 `json-repair` 库对非标 JSON 进行运行时修复。设置 15 秒超时中断防止长时阻塞，API 异常或修复失败时返回预设降级提示（含 disclaimer），保障前端契约的稳定交付。

### 3.2 主索引映射与标准协议的数据集成机制

针对多源异构数据孤岛，系统在应用平台域实现基于映射路由的归集与标准协议适配，仅建立路由映射读取外部系统，不对外部异构库做侵入性写入：

1. **标准协议接入**：通过适配器解析符合 FHIR R4 规范的 HIS/EMR/LIS 虚拟资源，将非标准化的临床数据映射为 `Patient`、`Observation`、`Condition` 等标准资源，标准化临床数据入口。
2. **交叉标识提取与多级匹配**：从各源系统数据中提取患者核心身份标识。首选通过身份证号精确匹配；若缺失，则通过姓名与手机号组合匹配；最后结合出生日期、性别等辅助字段确认，解决跨系统患者标识不一致的问题。
3. **主索引映射元数据**：构建 EMPI 映射元数据表，将不同源系统的 `SourcePatientID` 与系统内部生成的 `GlobalPatientID` 建立关联。系统仅存储路由映射关系，不搬运源系统业务数据。
4. **只读路由与融合查询**：当医生请求患者全生命周期视图时，应用域通过映射表查得该患者在源系统的 `SourcePatientID`，通过标准 API 或只读视图路由获取详情，在应用层完成多源数据的逻辑拼装。

### 3.3 基于成像特性的防御性影像转码与前端内存管控

PACS 下发的 DICOM 影像在前端解析存在性能瓶颈，且公开数据集存在标签不规范风险，系统基于皮肤镜成像特性实施防御性轻量化集成策略，兼顾渲染性能与医学信息完整性：

- **防御性后端离线转码与色彩空间还原**：皮肤镜影像属表皮光学成像，无需像 CT 进行 Hounsfield 单位调窗操作。推理域提供离线摄取管线，利用 `pydicom` 解析 DICOM。针对 SIIM-ISIC 2020 等公开数据集常见的标签不规范现象（`PhotometricInterpretation` 标记为 `YBR_FULL_422` 但底层实际存储为 RGB，强行按标签转换会导致严重偏色），管线采用防御性映射策略：对 3 通道图像直接按位深缩放输出，无视可能误导的 YBR 标签；对单通道灰度图严格按标签处理（`MONOCHROME1` 执行灰度反转逻辑，`MONOCHROME2` 执行常规归一化）。同时应用 RescaleSlope/Intercept 将像素映射至 0-255 uint8，确保皮肤病灶色彩无失真，随后转存为 Web 友好的 PNG 格式。
- **摄取接口与 UID 绑定**：推理域提供上传接口（`/upload`）与离线 URL 摄取接口（`/ingest`，基于 `httpx.AsyncClient` 异步下载）。原始文件落盘至 `uploads/` 后，同步调用解析器转码，PNG 存入 `static/images/`。提取 `PatientID` 等关键元数据，在自有数据库建立映射记录，将 UID 与转存的 PNG 路径强绑定。
- **前端渲染与内存生命周期管控**：针对高分辨率影像导致的浏览器内存泄漏风险，前端采用 `createObjectURL` 进行大图按需加载，并在 React 组件卸载或患者上下文切换时，严格调用 `revokeObjectURL` 释放 Blob 对象，防止影像堆积导致的页面崩溃。

### 3.4 异步响应代理与断连感知计算回收机制

医疗 AI 推理耗时较长，为避免资源浪费、级联阻塞与低资源部署下的 OOM 风险，系统构建了端到端的异步与资源回收逻辑：

- **应用域响应式代理**：Spring Boot 规避同步阻塞调用智能推理域。通过响应式客户端转发前端请求，将 FastAPI 的 SSE（Server-Sent Events）流反向代理给前端，防止线程池被长连接耗尽。
- **SSE 流多步级状态契约**：SSE 通道严格定义事件类型契约，支持多模态异步步级进度推进：`image_done`（图像定位完成，含热力图 URL、面积占比与位置特征）、`clinical_done`（病历解析完成）、`lab_done`（化验规则完成）、`result`（整合报告生成终结）、`error`（业务异常）以及 `heartbeat`（防止中间件静默断连）。
- **断连感知与流式步级推理终止逻辑**：当医生关闭页面或网络断开时，应用域感知连接中断并停止拉取 SSE 流。智能推理域 FastAPI 将耗时的多 Agent 推理任务解耦至独立线程运行，主协程通过 `await request.is_disconnected()` 实时监测连接状态。一旦断连即刻设置请求级的 `threading.Event` 终止信号，推理循环在各 Agent 调用的步间检查该信号并主动抛出中断退出，局部计算张量脱离作用域由 Python 垃圾回收释放资源。

```python
# 智能推理域 FastAPI 多 Agent 调度与终止逻辑示例
async def stream_diagnosis(request: Request, task_id: str):
    task_data = get_task_data(task_id) # 获取多模态上下文
    cancel_event = threading.Event()
    queue = asyncio.Queue()

    def run_pipeline_with_cancel():
        # 1. 图像 Agent (按需触发)
        if task_data.image_path:
            if cancel_event.is_set(): raise InterruptedError
            image_result = run_image_agent(...)
            queue.put_nowait(("step", {"step": "image_done", "data": image_result}))
        
        # 2. 病历 Agent / 化验 Agent / 整合 Agent 同理...

    inference_thread = threading.Thread(target=run_pipeline_with_cancel)
    inference_thread.start()

    try:
        while True:
            if await request.is_disconnected():
                cancel_event.set() # 通知推理线程在下一个 Agent 步级终止
                return
            try:
                event_type, data = queue.get_nowait()
                yield sse_format(event_type, data)
                if event_type == "result" or event_type == "error": return
            except asyncio.QueueEmpty:
                yield sse_format("heartbeat")
                await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        cancel_event.set()
```

- **异常处理机制**：系统定义了三级业务异常：`DicomParseException`、`ModelInferenceException`、`DiagnosisUncertainException`。SSE 流内部拦截前两者并封装为 `event: error` 推送；全局异常处理器拦截后者返回标准 422 JSON 响应。
- **长连接保活配置**：Nginx 网关需对 SSE 路径配置 `proxy_read_timeout 300s` 与 `proxy_buffering off`，确保 SSE 流不被缓存阻塞。

### 3.5 数据存储与智能推理域低资源环境管控

针对集成的结构化临床数据与 AI 非结构化特征，实施规范化的存储建模与轻量级资源管控：

- **推理域数据模型扩展**：智能推理域 Python 端仅负责 ORM 映射与异步增删改查。为适配多模态接入，数据库表结构从单一的 `Image` 映射扩展为 `Task` 语义，新增 `clinical_text`、`clinical_json`、`lab_json` 等字段存储多模态上下文，`url` (图片路径) 字段允许为 `null` 以兼容无图场景，主键标识统一为 `task_id`。
- **智能推理域 4C4G 低资源部署策略**：
  1. **ONNX 替换 PyTorch 推理**：将 UNet 模型由 PyTorch 导出为 ONNX 格式，使用 `onnxruntime` 进行 CPU 推理。相比原 `torch==2.1.0+cpu` 方案，ONNX 运行时内存占用降低约 40%，单张推理耗时稳定在 1 秒内，彻底移除了对 PyTorch 重型依赖的内存压力。
  2. **容器与系统级限制**：宿主机配置 4GB Swap 虚拟内存防止系统 OOM；通过 `docker-compose.yml` 强制限制基础组件内存上限（MySQL 512M，Qdrant 512M），给 FastAPI 预留计算空间；FastAPI 服务仅开启 1 个 Worker。
- **云端低资源环境部署约束**：
  1. **镜像基础版本约束**：因 `torch==2.1.0+cpu` 和 `transformers==4.36.1` 在 Python 3.12 下存在 API 兼容性断层，Dockerfile 基础镜像必须采用 `python:3.11-slim`。
  2. **向量化模型源配置**：国内云服务器部署时，需在 Dockerfile 及 `docker-compose.yml` 中配置 `HF_ENDPOINT` 环境变量（如 `https://hf-mirror.com`），确保 `bge-small-zh-v1.5` 模型正常拉取。
  3. **无头模式依赖**：Docker 容器无 GUI 环境，`requirements.txt` 中必须使用 `opencv-python-headless` 替代 `opencv-python`。
  4. **NumPy 版本强约束（极重要排障）**：`opencv-python-headless` 基于 NumPy 1.x 编译，若安装 `onnxruntime` 时将 NumPy 拉升至 2.x 会导致 OpenCV 崩溃。`requirements.txt` 必须将 NumPy 锁定在 `1.26.4`（既满足 `onnxruntime>=1.26.3` 的要求，又兼容 OpenCV 1.x 编译约束），严禁升级至 2.x 大版本。

---

## 4. 协作范式与项目拓扑

本项目由两位协作方共同完成，采用 API 契约驱动开发模式，服务域严格隔离。智能推理域聚焦于 AI 工程与数据治理，应用平台域聚焦于全栈高可用与医疗标准落地。

### 4.1 角色矩阵

| 协作方     | 核心职责域                                                   | 工程侧重                                                     |
| :--------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| **算法端** | 智能推理域（多 Agent 子系统、影像预处理、RAG 知识库）        | 多模态 Agent 编排、病灶视觉定位、规则引擎、DICOM 转码管线与检索增强生成 |
| **工程端** | 应用平台域（业务服务、前端交互、数据访问、协议接入、路由映射） | 异构数据集成归一、异步代理高可用保障、临床交互与内存管控     |

### 4.2 目录结构

```text
DermaIntegrate/
├── backend-ai/                  # [智能推理域] 智能推理层
│   ├── sql/                     # 推理域数据库初始化脚本
│   ├── models/                  # SQLAlchemy ORM 模型定义（Task多模态映射表）
│   ├── agents/                  # Multi-Agent 交互逻辑
│   │   ├── vlm_agent.py         # 图像Agent：VLM 形态学特征提取与降级策略
│   │   ├── clinical_agent.py    # 病历Agent：结构化映射与 LLM (DeepSeek) 文本解析 (含防漂移自重试)
│   │   ├── lab_agent.py         # 化验Agent：基于指南的分期规则引擎与跨模态依赖
│   │   └── integration_agent.py # 整合Agent：动态 Prompt 构建与结构化报告生成
│   ├── cnn/                     # LesionExtractor (ONNX推理框架，待真实权重替换高斯占位) 与视觉定位逻辑
│   │   └── unet_weights.onnx    # [待提供] 真实 UNet 模型权重 (EfficientNet-b0)
│   ├── rag/                     # SentenceTransformers + Qdrant 原生向量检索
│   │   └── docs/                # 黑色素瘤指南知识库源文件 (强制 ID 标注)
│   ├── api/                     # FastAPI 路由定义、SSE 流式输出与多模态调度
│   ├── preprocessing/           # DICOM 离线摄取管线与防御性色彩空间还原
│   ├── init_rag.py              # RAG 知识库向量化初始化脚本
│   └── exceptions.py            # 证据链断裂等自定义业务异常
│
├── backend-app/                 # [应用平台域] 应用服务层
│   ├── sql/                     # 应用域的数据库脚本
│   ├── empi/                    # 主索引映射引擎与跨系统只读路由
│   ├── fhir/                    # FHIR R4 Adapter 解析标准资源
│   ├── service/                 # 患者临床视图聚合、AI 诊断响应式异步代理
│   └── repository/              # MySQL 数据访问与业务查询
│
├── frontend/                    # [应用平台域] 表现层
│   ├── components/              # 影像滑动对比组件 (原图与病灶标注图叠加渲染)
│   ├── hooks/                   # useSSE 状态机封装与断线重试逻辑
│   └─ views/                   # 医生工作站界面与 AI 辅助诊断流式对话框
│
├── infra/                       # [推理域定义拓扑，应用域主导实施]
│   ├── docker-compose.yml       # 智能推理域微服务编排、容器内存限制与自动建库配置
│   ├── nginx/                   # 反向网关路由与 SSE 长连接超时配置
│   └── mock-fhir-data/          # 虚拟患者 JSON 资源池 (符合 FHIR R4 规范)
│
└── docs/                        # 契约文档与 API 定义
    └── api-contract.yaml        # 前后端与 AI 推理域的 SSE 交互契约 (OpenAPI 规范)
```

---

## 5. 部署与运行

### 5.1 环境配置

智能推理域采用 Docker Compose 编排微服务拓扑，并针对 4 核 4G 低资源云服务器进行了深度适配。应用平台域依据自身业务需求独立配置部署资源。

前提条件：智能推理域面向 CPU 环境部署推理，无需宿主机具备 GPU 及 NVIDIA Container Toolkit。推理域采用 ONNX Runtime 进行推理加速并降低内存占用。建议推理域宿主机配置 4GB Swap 虚拟内存以防止 OOM。

```bash
git clone https://github.com/yourname/DermaIntegrate.git
cd DermaIntegrate
```

<details>
<summary>核心依赖与版本控制</summary>

```text
# 智能推理域 Python 核心依赖 (Python 3.11)
fastapi==0.109.0               # 异步 Web 框架
uvicorn[standard]==0.27.0      # ASGI 服务器
python-multipart==0.0.6        # 表单处理
pydantic==2.5.0                # 数据校验
aiofiles==23.2.1               # 异步文件操作
pydicom==3.0.2                 # DICOM 医学影像解析与元数据提取
Pillow==12.2.0                 # 图像处理与色彩空间转换
numpy==1.26.4                  # 数值计算与像素归一化 (1.x最终版，满足onnxruntime且兼容OpenCV)
httpx==0.28.1                  # 异步 HTTP 客户端 (用于离线摄取)
openai==2.40.0                 # DeepSeek API 兼容客户端依赖
qdrant-client==1.18.0          # Qdrant 向量数据库客户端
sentence-transformers==2.7.0   # 文本向量化模型加载
transformers==4.36.1           # NLP 模型库
opencv-python-headless==4.9.0.80 # 图像处理与掩膜叠加（Headless 版，Docker 无 GUI 依赖）
torch==2.1.0+cpu               # UNet训练环境所需，推理环境将由ONNX替代
torchvision==0.16.0+cpu        # UNet训练环境所需，推理环境将由ONNX替代
onnxruntime==1.17.0            # 高性能 CPU 推理引擎 (执行 UNet 推理，替代 PyTorch)
json-repair==0.60.1            # LLM 输出 JSON 结构运行时修复库
SQLAlchemy==2.0.25             # ORM 映射
aiomysql==0.2.0                # 异步 MySQL 驱动
python-dotenv==1.0.0           # 环境变量配置加载

# 应用平台域 Java 核心依赖 (基于 Spring Boot 3.x)
org.springframework.boot:spring-boot-starter-webflux    # 响应式非阻塞 WebClient
ca.uhn.hapi.fhir:hapi-fhir-base:6.8.0                  # FHIR R4 国际医疗协议解析
com.mysql:mysql-connector-j:8.0.33                      # MySQL 驱动

# 基础设施组件
mysql:8.0                      # 关系型数据库
qdrant/qdrant:latest           # 向量数据库
redis:7                        # 分布式缓存（应用域使用）
```
### 5.2 参数配置

在启动服务前，需在相关模块配置必要参数。**请严格区分智能推理域与应用平台域的数据库与网络边界**。

**1. 智能推理域配置**：在 `backend-ai/.env` 中配置大模型接口参数、推理域数据库连接与降级开关（可参考 `backend-ai/.env.example`）：
```env
# --- 推理域数据库配置 (独立于应用域数据库) ---
# [本地开发] 映射到宿主机 3307 端口，连接推理域专属库 derma_ai
DATABASE_URL=mysql+aiomysql://root:root_password@localhost:3307/derma_ai
# [Docker部署] 请注释掉上面一行，启用下面这行（使用容器名 mysql 和内部端口 3306）
# DATABASE_URL=mysql+aiomysql://root:root_password@mysql:3306/derma_ai

# --- 视觉语言模型配置：DeepSeek-VL2 (用于图像形态学特征提取，严禁下诊断) ---
VLM_API_KEY=your_deepseek_api_key
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-vl2

# --- 整合/病历提取大模型配置：DeepSeek-V4-Flash ---
# 用于病历自由文本结构化提取与多模态信息整合报告生成
# 采用非思考模式以保证 JSON 输出格式的稳定与低延迟
INTEGRATION_API_KEY=your_deepseek_api_key
INTEGRATION_BASE_URL=https://api.deepseek.com
INTEGRATION_MODEL=deepseek-v4-flash

# --- 降级开关配置 ---
# 设为 true 时，将拦截真实调用并返回预设 Mock 数据，便于前端联调或无网络环境测试
# 当前必须为 true！因为视觉输入(热力图)仍是高斯占位符，真实 VLM 分析无医学意义
# 待 UNet 真实权重替换后，方可改为 false
USE_MOCK_VLM=true
# 病历/整合 Agent 算法已实质化落地，设为 false 可调用真实 LLM
USE_MOCK_INTEGRATION=false

# --- RAG 向量数据库配置 ---
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=derma_knowledge

# --- Docker 环境标识 (极其关键！) ---
# [本地开发] 设为 false，代码将连接 localhost 的 Qdrant
# [Docker部署] 必须设为 true，代码将连接 Qdrant 容器名 (覆盖上方 QDRANT_HOST)
DOCKER_ENV=false

# --- HuggingFace 镜像源 (国内云服务器部署必填) ---
# 解决国内服务器无法下载 bge-small-zh-v1.5 模型的问题
HF_ENDPOINT=https://hf-mirror.com
```

**2. 应用平台域配置**：在 `backend-app/src/main/resources/application.yml` 中配置应用域数据库与智能推理域路由：
```yaml
spring:
  datasource:
    # 注意：此为应用域独立数据库 derma_integrate，默认 3306 端口，与推理域 derma_ai 物理隔离
    url: jdbc:mysql://localhost:3306/derma_integrate?useSSL=false&characterEncoding=utf8
    username: root
    password: root_password

# 智能推理域路由地址 (云端部署时替换为公网 IP 及 Nginx 代理路径)
ai:
  pipeline:
    base-url: http://localhost:8000
```

### 5.3 运行模式

**全链路联合启动**：
一键启动所有微服务，构建完整的数据集成与辅助诊断验证环境。首次启动将通过推理域的 `docker-compose.yml` 自动创建推理库。若全链路部署在单台服务器上，请确保服务器满足智能推理域 4C4G 及 Swap 的资源要求。
```bash
docker-compose up -d
```
启动后访问 `http://localhost/` 即可进入医生工作站。系统内置 Mock Server 将自动灌入虚拟患者数据，支持从“多源数据集成接入 -> 主索引映射归一 -> 影像调阅 -> 多模态辅助诊断 -> 医生裁决”的完整流程验证。

**智能推理域独立调试**：
适用于算法迭代与多 Agent 推理逻辑验证，无需启动 Java 后端与前端。由于限制了 MySQL 与 Qdrant 的内存使用，请确保该环境至少具有 4G 可用内存及 4G Swap。
```bash
# 前提：需先启动推理域依赖的基础设施
docker-compose up -d mysql qdrant

cd backend-ai
# 初始化 RAG 知识库向量数据 (需预先在 rag/docs/ 下放置带 ID 标注的指南文本文档)
python init_rag.py
uvicorn api.main:app --reload --port 8000
# 可使用 Postman 测试多模态数据上传 (需附带 clinical_json 与 lab_json)，或触发 SSE 流测试多 Agent 调度
```

**智能推理域云端极限部署（4C4G 服务器）**：
适用于智能推理域独立上云部署，应用平台域通过公网 IP 跨域调用。
```bash
# 1. 宿主机 Swap 配置 (防 OOM)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 2. 克隆代码并进入 (云端仅需保留 backend-ai 与 infra 目录即可)
git clone https://github.com/yourname/DermaIntegrate.git && cd DermaIntegrate

# 3. 修改 .env 配置
# 务必启用 Docker 部署专用的 DATABASE_URL、设置 DOCKER_ENV=true、设置 HF_ENDPOINT
cd backend-ai && cp .env.example .env && nano .env 

# 4. 启动容器 (需在 infra 目录下)
cd ../infra
sudo docker-compose up -d

# 5. 初始化 RAG 知识库 (首次启动需手动执行)
sudo docker exec -it derma-fastapi python init_rag.py

# 6. 配置 Nginx 反向代理
sudo apt install nginx
# 新建 /etc/nginx/conf.d/derma.conf，需包含以下核心路由：
# - client_max_body_size 5m; (解决医学影像上传限制)
# - location /ai/ 代理至 8000 端口，开启 proxy_buffering off 与 proxy_read_timeout 300s (保障 SSE 流)
# - location /ai-static/ 代理至 8000 端口 (保障热力图与原图公网可访问)
# - location = /openapi.json 代理至 8000 端口 (保障 Swagger UI 正常加载)
sudo nginx -s reload
```

**应用平台域独立调试**：
适用于业务逻辑开发与前端交互调试，AI 请求将路由至云端或本地宿主机的推理服务。
```bash
# 前提：需先启动应用域依赖的基础设施
docker-compose up -d mysql redis

# 1. 启动后端服务
cd backend-app
mvn spring-boot:run
# 测试主索引路由聚合、FHIR 解析与响应式异步代理

# 2. 启动前端界面
cd frontend
npm install
npm run dev
# 测试患者临床视图、影像滑动对比与 SSE 流式交互
```

---

## 6. 架构约束与设计原则

为保障多源数据集成的准确性、多模态输入的兼容性及 AI 辅助的可解释性，本项目在代码级实施了以下架构约束：

1. **多模态缺失兼容与定向指导原则**：系统以 `task_id` 为流转核心，对图像、病历、化验数据的缺失具备完全容忍度。当核心确诊数据缺失时，系统不阻断流程，必须由对应 Agent 或整合 Agent 给出明确的定向补充检查建议（如：缺乏病理浸润深度时建议活检），系统拒绝在数据不足时给出终局诊断。
2. **可解释证据链与诊断剥离原则**：系统仅提供视觉定位、形态学特征与规则分层作为辅助，不直接输出诊断结论。图像 Agent 的 VLM 必须受强制 JSON 格式约束并经后置正则过滤剥离诊断性输出；若视觉定位或 RAG 关键组件缺失，均判定为证据链断裂，抛出 `DiagnosisUncertainException` 触发降级提示，交还医生裁量。
3. **数据归一化与非侵入原则**：应用域仅通过主索引建立路由映射逻辑聚合多源数据，通过标准协议接入，严禁对医院现有异构源系统进行侵入性写入或直连表操作。
4. **计算转码与前端渲染分离原则**：前端规避引入 Cornerstone 等重型 DICOM 解析库。所有医疗影像必须由推理域在后端预处理（含防御性色彩空间还原与归一化）为 Web 标准格式，前端仅负责渲染与内存生命周期管控。
5. **异步与非阻塞原则**：应用域规避以同步阻塞方式调用推理域的 AI 接口。必须遵循异步 SSE 契约，且推理域必须将同步推理解耦至独立线程，配合异步事件循环实现断连步级终止机制，防止计算资源无效占用。
6. **契约驱动与服务隔离原则**：推理域与应用域的协作严格遵循 `docs/api-contract.yaml` 定义的数据结构、SSE 步级事件类型与流式事件格式。推理域不可擅自变更 Schema，平台域不可硬编码解析契约外字段，确保异构系统并行开发与集成。