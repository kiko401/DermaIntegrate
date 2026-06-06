# DermaIntegrate: 皮肤病多源数据集成与智能辅助诊断系统

**许可协议**：MIT License 
**运行环境**：Python 3.11 / Java 17+ (Spring Boot 3.x+) / Node 18+ 
**系统架构**：基于 API 契约的模块解耦，推理服务与应用服务进程级隔离与独立部署

---

## 摘要

本项目面向皮肤病专科门诊场景，解决临床业务中多源异构数据孤岛与医疗 AI 缺乏可解释性的问题，构建数据集成与可解释辅助诊断系统。在数据集成层面，针对 HIS、PACS、LIS 等系统数据异构与标识不一的问题，采用主索引映射与 FHIR R4 标准协议，实现跨系统异构数据的归一化接入与逻辑聚合，构建患者全生命周期临床视图；在 AI 辅助层面，针对端到端模型直接输出诊断结论缺乏推断依据的问题，提出基于显著性区域定位与检索增强的可解释机制：通过病灶视觉定位模型提供客观视觉依据，约束视觉语言模型输出结构化形态学描述，并融合 RAG 检索构建辅助证据链，将算法推断过程透明化，诊断裁量权交由临床医生。工程层面，系统针对医学影像前端解析瓶颈、DICOM 标签不规范风险与长时 AI 推理引发的资源占用问题，分别实现了基于成像特性的防御性后端转码、前端轻量渲染机制，以及基于 SSE 的异步响应代理与断连感知计算资源回收机制，并在智能推理域 4C4G 低资源云服务器环境下，通过 Swap、容器限制与国内镜像源注入实现稳定部署，保障临床环境下的系统可用性。

---

## 1. 核心问题与方法映射

针对皮肤病临床业务中的数据流转与 AI 应用问题，本系统的应对策略与工程机制如下：

| 临床工程问题                                                 | 本系统应对策略与工程机制                                     |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| **多源异构数据孤岛**：HIS、LIS、PACS等系统数据异构，患者标识不一，难以形成完整临床视图。 | **主索引映射与 FHIR 标准归一化**：基于主索引映射跨系统患者标识，结合 FHIR R4 标准协议解析资源，实现异构数据的逻辑聚合与患者全生命周期视图构建，不侵入源系统。 |
| **医疗 AI 缺乏可解释性**：端到端模型直接生成诊断结论缺乏推理依据，医生无法验证，存在事实偏移风险。 | **视觉定位与可解释证据链**：基于病灶视觉定位模型提供视觉依据，约束大模型输出结构化形态学描述，并融合 RAG 文献检索，构建可验证的辅助证据链，系统不直接输出诊断结论。 |
| **DICOM 影像前端解析与标签风险**：PACS 下发的 DICOM 影像强依赖重型解析库实时渲染导致卡顿；且公开数据集常存在标签不规范（如 YBR 标 RGB）导致严重偏色。 | **防御性影像转码与轻量渲染**：基于皮肤镜无需调窗的特性，后端离线解析 DICOM 并执行防御性色彩空间还原转码为 PNG，结合前端轻量滑动对比组件，实现影像数据的透明集成调阅。 |
| **长时 AI 推理引发的资源占用**：AI 推理耗时导致服务端计算资源长期占用，并发能力衰减，且异常断连易导致计算浪费与 OOM 崩溃。 | **异步响应代理与低资源部署**：基于 SSE 异步契约解耦业务与推理，建立断连感知逻辑，前端断连即终止推理步级计算；智能推理域云端采用 4C4G 低资源部署，通过 Swap 与容器内存限制保障系统稳定性。 |

---

## 2. 系统架构设计

系统遵循“推理计算与业务流转解耦”原则，划分两大进程级隔离服务域：**智能推理域**负责 AI 推理、特征提取与影像预处理；**应用平台域**负责数据集成归一、标准协议接入与前端交互。

```markdown
③ 表现层（应用平台域 - React 18 + AntD + ECharts）
  ├─ 医生工作站 (患者全生命周期临床视图聚合展示)
  ├─ 影像滑动对比组件 (原图/标注图叠加渲染)
  └─ AI 辅助诊断流式对话框 (展示可解释证据链，医生裁决)

② 服务与数据层（跨域协同）
  ├─ 智能推理域：LesionExtractor (UNet占位) 视觉定位提取 | DeepSeek-VL2 结构化形态描述 | RAG 知识检索 (SentenceTransformers + Qdrant)
  ├─ 应用平台域：患者临床视图聚合 | 主索引映射 | FHIR R4 协议接入 | AI 诊断异步代理
  ├─ 推理域数据核心：独立 MySQL 数据库 (影像 UID 映射、AI 特征与 DICOM 元数据存储)
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

### 3.1 基于视觉定位与检索增强的可解释辅助机制

为解决医疗 AI 缺乏可解释性的问题，系统定位于提供客观依据的辅助工具，不直接输出诊断结论。系统构建管道式的证据链生成机制，将算法推断过程透明化，交由医生裁决：

1. **特征提取与显著性视觉定位生成**：当前阶段采用 `LesionExtractor` 类实现视觉定位。针对预训练 ResNet50 的 Grad-CAM 在非专科数据上热力图缺乏医学意义的问题，系统当前使用高斯模糊掩膜作为占位符，生成红色半透明椭圆覆盖图，为后续自训练 UNet 预留了标准的 `generate(input_path, output_path)` 接口。替换真实 UNet 权重后，将输出精确的病灶分割掩码叠加图，提供客观视觉定位。
2. **形态学结构化约束与诊断结论剥离**：将定位图与原图共同输入视觉语言模型（DeepSeek-VL2）。为规避生成式模型无约束推断带来的事实偏移，系统通过 Prompt 设计强制模型输出 JSON 格式的形态学描述（如边缘不规则、色素网络变异等）。此外，工程解析层实现正则过滤方法（`_filter_diagnosis`），剥离模型输出中夹带在描述字段内的诊断性陈述，确保形态描述的客观性。
3. **RAG 文献补充与辅助证据链构建**：因 `llama-index` 最新版与 Python 3.11 及 `pydantic 2.5` 存在依赖冲突，系统采用 `SentenceTransformers` + `qdrant-client` 原生实现 RAG 检索。利用 `BAAI/bge-small-zh-v1.5` 模型将查询向量化，从 Qdrant 向量知识库中召回相关医学文献片段并拼接上下文。系统最终交付医生的辅助视图包含：原图、定位标注图、客观形态描述、文献参考。
4. **证据链完整性校验与降级策略**：在工程逻辑层，系统强制校验证据组件的存在性。若视觉定位生成失败或 RAG 无有效文献支撑，系统判定证据链断裂，抛出 `DiagnosisUncertainException` 异常，前端执行降级提示。同时，针对 VLM API 不可用或超时的场景，系统实现降级开关（读取环境变量 `USE_MOCK_VLM`），当开关开启或 API 调用异常时，自动捕获错误并返回预设的 Mock JSON，保障基础流程的连贯性。

### 3.2 主索引映射与标准协议的数据集成机制

针对多源异构数据孤岛，系统在应用平台域实现基于映射路由的归集与标准协议适配，仅建立路由映射读取外部系统，不对外部异构库做侵入性写入：

1. **标准协议接入**：通过适配器解析符合 FHIR R4 规范的 HIS/EMR/LIS 虚拟资源，将非标准化的临床数据映射为 `Patient`、`Observation`、`Condition` 等标准资源，标准化临床数据入口。
2. **交叉标识提取与多级匹配**：从各源系统数据中提取患者核心身份标识。首选通过身份证号精确匹配；若缺失，则通过姓名与手机号组合匹配；最后结合出生日期、性别等辅助字段确认，解决跨系统患者标识不一致的问题。
3. **主索引映射元数据**：构建 EMPI 映射元数据表，将不同源系统的 `SourcePatientID` 与系统内部生成的 `GlobalPatientID` 建立关联。系统仅存储路由映射关系，不搬运源系统业务数据。
4. **只读路由与融合查询**：当医生请求患者全生命周期视图时，应用域通过映射表查得该患者在源系统的 `SourcePatientID`，通过标准 API 或只读视图路由获取详情，在应用层完成多源数据的逻辑拼装。

### 3.3 基于成像特性的防御性影像转码与前端内存管控

PACS 下发的 DICOM 影像在前端解析存在性能瓶颈，且公开数据集存在标签不规范风险，系统基于皮肤镜成像特性实施防御性轻量化集成策略，兼顾渲染性能与医学信息完整性：

- **防御性后端离线转码与色彩空间还原**：皮肤镜影像属表皮光学成像，无需像 CT 进行 Hounsfield 单位调窗操作。推理域提供离线摄取管线，利用 `pydicom` 解析 DICOM。针对 SIIM-ISIC 2020 等公开数据集常见的标签不规范现象（`PhotometricInterpretation` 标记为 `YBR_FULL_422` 但底层实际存储为 RGB，强行按标签转换会导致严重偏色），管线采用防御性映射策略：对 3 通道图像直接按位深缩放输出，无视可能误导的 YBR 标签；仅对单通道灰度图严格按标签处理（`MONOCHROME1` 执行灰度反转逻辑，`MONOCHROME2` 执行常规归一化）。同时应用 RescaleSlope/Intercept 将像素映射至 0-255 uint8，确保皮肤病灶色彩无失真，随后转存为 Web 友好的 PNG 格式。
- **摄取接口与 UID 绑定**：推理域提供上传接口（`/upload`）与离线 URL 摄取接口（`/ingest`，基于 `httpx.AsyncClient` 实现异步下载，超时设置 15 秒防阻塞）。原始文件落盘至 `uploads/` 后，同步调用解析器转码，PNG 存入 `static/images/`。提取 `PatientID`、`StudyInstanceUID` 等关键元数据，在自有数据库建立映射记录，将 UID 与转存的 PNG 路径强绑定，并记录真实宽高与 DICOM 原始标签。
- **前端渲染与内存生命周期管控**：针对高分辨率影像导致的浏览器内存泄漏风险，前端采用 `createObjectURL` 进行大图按需加载，并在 React 组件卸载或患者上下文切换时，严格调用 `revokeObjectURL` 释放 Blob 对象，防止影像堆积导致的页面崩溃。

### 3.4 异步响应代理与断连感知计算回收机制

医疗 AI 推理耗时较长，为避免资源浪费、级联阻塞与低资源部署下的 OOM 风险，系统构建了端到端的异步与资源回收逻辑：

- **应用域响应式代理**：Spring Boot 规避同步阻塞调用智能推理域。通过响应式客户端转发前端请求，将 FastAPI 的 SSE（Server-Sent Events）流反向代理给前端，防止线程池被长连接耗尽。
- **SSE 流状态契约**：SSE 通道严格定义事件类型契约：`step`（中间推理流）、`result`（成功终结）、`error`（业务异常如证据链断裂或模型推理失败）以及 `heartbeat`（防止中间件静默断连）。前端状态机据此实现完整的交互逻辑与降级提示。
- **断连感知与流式步级推理终止逻辑**：当医生关闭页面或网络断开时，应用域感知连接中断并停止拉取 SSE 流。由于深度学习模型前向推理属于密集计算，Python 无法直接中断正在执行的 C++ 底层张量运算。因此，智能推理域 FastAPI 将耗时的推理任务解耦至独立线程运行（`asyncio.to_thread`），主协程通过 `await request.is_disconnected()` 实时监测连接状态。一旦断连即刻设置请求级的 `threading.Event` 终止信号，推理循环在**流式生成的步间**（如视觉定位结束、VLM 调用前、RAG 检索前）检查该信号并主动退出循环，局部计算张量脱离作用域由 Python 垃圾回收释放资源，防止计算资源无效占用。

```python
# 智能推理域 FastAPI 核心推理终止逻辑
async def stream_diagnosis(request: Request, task_id: str):
    # 构建请求级的取消事件，防止并发污染
    cancel_event = threading.Event()
    # 将同步推理解耦至独立线程，保障异步断连感知不阻塞
    inference_task = asyncio.create_task(
        asyncio.to_thread(run_pipeline_with_cancel, cancel_event)
    )
    try:
        while not inference_task.done():
            if await request.is_disconnected():
                logger.warning(f"Client disconnected. Aborting task: {task_id}")
                cancel_event.set() # 通知推理线程在下一个生成步终止
                return # 终止 SSE 流
            yield sse_format("heartbeat") # 兑现心跳契约
            await asyncio.sleep(0.1)
        # 正常完成推理，需捕获线程内异常防止协程崩溃
        try:
            result_data = inference_task.result()
            yield sse_format(result_data)
        except Exception as e:
             yield sse_format("error", message=str(e))
    except asyncio.CancelledError:
        cancel_event.set()

# --- 推理域推理线程中的步级终止检查示例 ---
def run_pipeline_with_cancel(cancel_event):
    for step in model_generate_steps: 
        # 在每个生成步的间隔检查终止信号，无法中断单步内部的张量计算
        if cancel_event.is_set():
            logger.info("Inference cancelled at step level, exiting loop.")
            return None # 退出计算循环，局部张量释放
        # 执行单步推理并产出...
```

- **异常处理机制**：系统定义了三级业务异常：`DicomParseException`（DICOM 解析失败）、`ModelInferenceException`（模型推理失败，如视觉证据提取异常）、`DiagnosisUncertainException`（证据链断裂）。SSE 流内部拦截前两者并封装为 `event: error` 推送；全局异常处理器拦截后者返回标准 422 JSON 响应，保障服务不触发 HTTP 500 且连接优雅断开。
- **长连接保活配置**：Nginx 网关需对 SSE 路径配置 `proxy_read_timeout 300s` 与 `proxy_buffering off`，确保 SSE 流不被缓存阻塞。

### 3.5 数据存储与智能推理域低资源环境管控

针对集成的结构化临床数据与 AI 非结构化特征，实施规范化的存储建模与轻量级资源管控：

- **推理域数据库初始化解耦与存储映射**：智能推理域 Python 端仅负责 ORM 映射与异步增删改查，移除同步建库建表逻辑，需在推理域的 `docker-compose.yml` 中配置 `MYSQL_DATABASE: derma_ai` 确保数据库自动创建。推理域采用 SQLAlchemy ORM 映射表结构，针对影像资源设立 `status` 字段标识处理状态（`processing`/`ready`），`url` 字段记录转码后路径，`original_dicom_tags` 字段以 JSON 形式存储 DICOM 元数据，`width` 与 `height` 记录真实影像维度。
- **智能推理域 4C4G 低资源部署策略**：在 4 核 4G 的智能推理域云服务器环境下，首先在宿主机配置 4GB Swap 虚拟内存防止系统 OOM；其次通过推理域 `docker-compose.yml` 强制限制基础组件内存上限（如 MySQL 限制 512M，Qdrant 限制 512M），给 FastAPI + PyTorch 预留计算空间；深度学习框架强制指定 CPU 版本（如 `torch==2.1.0+cpu`），剔除冗余的 CUDA 库，将镜像体积压缩至可部署范围；智能推理域 FastAPI 服务仅开启 1 个 Worker，避免多进程加载模型耗尽内存。
- **云端低资源环境部署约束**：
  1. **镜像基础版本约束**：因 `torch==2.1.0+cpu` 与 `transformers==4.36.1` 在 Python 3.12 下存在底层 API 兼容性断层，Dockerfile 基础镜像必须采用 `python:3.11-slim`。
  2. **向量化模型源配置**：国内云服务器部署时，需配置 `HF_ENDPOINT` 环境变量（如 `https://hf-mirror.com`），确保 `bge-small-zh-v1.5` 模型正常拉取，避免 RAG 初始化超时。
  3. **无头模式依赖**：Docker 容器无 GUI 环境，`requirements.txt` 中必须使用 `opencv-python-headless` 替代 `opencv-python`，规避运行时依赖冲突。

---

## 4. 协作范式与项目拓扑

本项目由两位协作方共同完成，采用 API 契约驱动开发模式，服务域严格隔离。智能推理域聚焦于 AI 工程与数据治理，应用平台域聚焦于全栈高可用与医疗标准落地。

### 4.1 角色矩阵

| 协作方     | 核心职责域                                                   | 工程侧重                                                     |
| :--------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| **算法端** | 智能推理域（AI 子系统、影像预处理、RAG 知识库）              | 病灶视觉定位提取、形态学结构化约束、DICOM 转码管线与检索增强生成 |
| **工程端** | 应用平台域（业务服务、前端交互、数据访问、协议接入、路由映射） | 异构数据集成归一、异步代理高可用保障、临床交互与内存管控     |

### 4.2 目录结构

```text
DermaIntegrate/
├── backend-ai/                  # [智能推理域] 智能推理层
│   ├── sql/                     # 推理域数据库初始化脚本
│   ├── models/                  # SQLAlchemy ORM 模型定义（数据库访问层）
│   ├── agents/                  # Multi-Agent 交互逻辑与 VLM 降级策略
│   ├── cnn/                     # LesionExtractor (UNet占位) 与视觉定位逻辑
│   ├── rag/                     # SentenceTransformers + Qdrant 原生向量检索
│   ├── api/                     # FastAPI 路由定义与 SSE 流式输出
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

前提条件：智能推理域面向 CPU 环境部署推理，无需宿主机具备 GPU 及 NVIDIA Container Toolkit。推理域已在 Dockerfile 中指定 PyTorch CPU 版本。建议推理域宿主机配置 4GB Swap 虚拟内存以防止 OOM。

```bash
git clone https://github.com/yourname/DermaIntegrate.git
cd DermaIntegrate
```

<details>
<summary>核心依赖与版本控制</summary>

```text
# 智能推理域 Python 核心依赖 (Python 3.11)
# ⚠️ 注意：torch 与 torchvision 需在 Dockerfile 中单独安装 CPU 版本，严禁写入 requirements.txt
fastapi==0.109.0               # 异步 Web 框架
uvicorn[standard]==0.27.0      # ASGI 服务器
python-multipart==0.0.6        # 表单处理
pydantic==2.5.0                # 数据校验
aiofiles==23.2.1               # 异步文件操作
pydicom==3.0.2                 # DICOM 医学影像解析与元数据提取
Pillow==12.2.0                 # 图像处理与色彩空间转换
numpy==1.26.2                  # 数值计算与像素归一化（必须<=1.26.x以兼容 torch 2.1.0）
httpx==0.28.1                  # 异步 HTTP 客户端 (用于离线摄取)
openai==2.40.0                 # DeepSeek API 兼容客户端依赖
qdrant-client==1.18.0          # Qdrant 向量数据库客户端
sentence-transformers==2.7.0   # 文本向量化模型加载（降级以兼容 torch 2.1.0）
transformers==4.36.1           # NLP 模型库（显式固定，防止 5.x 与 torch 2.1.0 底层 API 不兼容）
opencv-python-headless==4.9.0.80 # 图像处理与掩膜叠加（Headless 版，Docker 无 GUI 依赖）
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

# --- 视觉语言模型配置：DeepSeek-VL2 (用于形态学描述) ---
VLM_API_KEY=your_deepseek_api_key
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-vl2

# --- 降级开关配置 ---
# 设为 true 时，将拦截真实 VLM 调用并返回预设 Mock 数据，便于前端联调
USE_MOCK_VLM=true

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
启动后访问 `http://localhost/` 即可进入医生工作站。系统内置 Mock Server 将自动灌入虚拟患者数据，支持从“多源数据集成接入 -> 主索引映射归一 -> 影像调阅 -> AI 可解释证据链辅助 -> 医生裁决”的完整流程验证。

**智能推理域独立调试**：
适用于算法迭代与模型推理逻辑验证，无需启动 Java 后端与前端。由于限制了 MySQL 与 Qdrant 的内存使用，请确保该环境至少具有 4G 可用内存及 4G Swap。
```bash
# 前提：需先启动推理域依赖的基础设施
docker-compose up -d mysql qdrant

cd backend-ai
# 初始化 RAG 知识库向量数据 (需预先在 rag/docs/ 下放置文本文档)
python init_rag.py
uvicorn api.main:app --reload --port 8000
# 可使用 Postman 上传真实 .dcm 文件测试转码，或触发 SSE 流测试推理管线与降级逻辑
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

为保障多源数据集成的准确性及 AI 辅助的可解释性，本项目在代码级实施了以下架构约束：

1. **可解释证据链优先原则**：系统仅提供视觉定位与形态学特征作为辅助，不直接输出诊断结论。VLM 必须受强制 JSON 格式约束并经后端过滤剥离诊断性输出；若视觉定位或 RAG 关键组件缺失，均判定为证据链断裂，抛出 `DiagnosisUncertainException` 触发降级提示，交还医生裁量。
2. **数据归一化与非侵入原则**：应用域仅通过主索引建立路由映射逻辑聚合多源数据，通过标准协议接入，严禁对医院现有异构源系统进行侵入性写入或直连表操作。
3. **计算转码与前端渲染分离原则**：前端规避引入 Cornerstone 等重型 DICOM 解析库。所有医疗影像必须由推理域在后端预处理（含防御性色彩空间还原与归一化）为 Web 标准格式，前端仅负责渲染与内存生命周期管控。
4. **异步与非阻塞原则**：应用域规避以同步阻塞方式调用推理域的 AI 接口。必须遵循异步 SSE 契约，且推理域必须将同步推理解耦至独立线程，配合异步事件循环实现断连步级终止机制，防止计算资源无效占用。
5. **契约驱动与服务隔离原则**：推理域与应用域的协作严格遵循 `docs/api-contract.yaml` 定义的数据结构、SSE 事件类型与流式事件格式。推理域不可擅自变更 Schema，平台域不可硬编码解析契约外字段，确保异构系统并行开发与集成。