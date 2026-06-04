# DermaIntegrate: 皮肤病多源数据集成与智能辅助诊断平台

**许可协议**：MIT License 
**运行环境**：Python 3.10+ / Java 17+ (Spring Boot 3.x+) / Node 18+ 
**系统架构**：基于API契约的模块解耦，推理服务与应用服务进程级隔离与独立部署

---

## 摘要

本项目面向皮肤病专科门诊场景，针对临床业务中多源异构数据孤岛与医疗AI缺乏可解释性的双重问题，构建数据集成与可解释辅助诊断平台。在数据集成层面，针对HIS、PACS、LIS等系统数据异构、标识不一的问题，采用主索引映射与FHIR R4标准协议，实现跨系统异构数据的归一化接入与逻辑聚合，构建患者全生命周期临床视图；在AI辅助层面，针对端到端模型直接输出诊断结论缺乏推理依据的问题，提出基于显著性区域定位与检索增强的可解释机制：通过CNN提取特征并生成Grad-CAM热力图提供客观视觉定位，约束视觉语言模型输出结构化形态学描述，并融合RAG检索构建辅助证据链，将算法推断过程透明化，最终诊断裁量权交由临床医生。工程层面，系统针对医学影像前端解析瓶颈与长时AI推理引发的资源占用风险，分别实现了基于成像特性的后端转码与前端轻量渲染机制，以及基于SSE的异步响应代理与断连感知计算资源回收机制，保障临床环境下的系统可用性。

---

## 1. 核心问题与方法映射

针对皮肤病临床业务中的数据流转与AI应用问题，本平台的应对策略与工程机制如下：

| 临床工程问题                                                 | 本系统应对策略与工程机制                                     |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| **多源异构数据孤岛**：HIS、LIS、PACS等系统数据异构，患者标识不一，难以形成完整临床视图。 | **主索引映射与FHIR标准归一化**：基于主索引映射跨系统患者标识，结合标准协议解析R4资源，实现异构数据的逻辑聚合与患者全生命周期视图构建，不侵入源系统。 |
| **医疗AI缺乏可解释性**：端到端模型直接生成诊断结论缺乏推理依据，医生无法验证，存在事实偏移风险。 | **显著性视觉定位与可解释证据链**：基于CNN生成显著性热力图提供视觉定位，约束大模型输出结构化形态学描述，并融合RAG文献检索，构建可验证的辅助证据链，系统不直接输出诊断结论。 |
| **DICOM影像前端解析瓶颈**：PACS下发的DICOM影像强依赖重型解析库实时渲染，导致浏览器内存溢出与交互卡顿。 | **基于成像特性的影像转码与轻量渲染**：基于皮肤镜无需调窗的特性，后端离线解析DICOM并执行色彩空间还原转码为PNG，结合前端轻量滑动对比组件，实现影像数据的透明集成调阅。 |
| **长时AI推理引发的资源占用**：AI推理耗时导致服务端计算资源长期占用，并发能力衰减，且异常断连易导致计算浪费。 | **异步响应代理与计算资源回收**：基于SSE异步契约解耦业务与推理，建立断连感知逻辑，前端断连即终止推理步级计算，防止计算资源无效占用。 |

---

## 2. 系统架构设计

系统遵循“推理计算与业务流转解耦”原则，划分两大进程级隔离服务域：**智能推理域**负责AI推理、特征提取与影像预处理；**应用平台域**负责数据集成归一、标准协议接入与前端交互。

```text
③ 表现层（应用平台域 - React 18 + AntD + ECharts）
  ├─ 医生工作站 (患者全生命周期临床视图聚合展示)
  ├─ 影像滑动对比组件 (原图/标注图叠加渲染)
  └─ AI辅助诊断流式对话框 (展示可解释证据链，医生裁决)

② 服务与数据层（跨域协同）
  ├─ 智能推理域：ResNet50 + Grad-CAM 视觉定位提取 | DeepSeek-VL2 结构化形态描述 | RAG 知识检索 (LlamaIndex + Qdrant)
  ├─ 应用平台域：患者临床视图聚合 | 主索引映射 | 标准协议接入 | AI诊断异步代理
  ├─ 推理域数据核心：独立MySQL数据库 (影像UID映射、AI特征与DICOM元数据存储)
  └─ 应用域数据核心：MySQL 8 (关系型业务数据存储)

① 接入与预处理层
  ├─ DICOM离线摄取管线、色彩空间还原、像素转码、元数据提取与UID绑定 (推理域执行)
  └─ FHIR Mock Server (仿真HIS/EMR/LIS，应用域接入)

⓪ 基础设施层
  ├─ Docker Compose 编排与容器内存限制配置
  └─ Nginx 网关路由与SSE长连接超时配置
```

---

## 3. 关键工程实现与核心机制

### 3.1 基于视觉定位与检索增强的可解释辅助机制

为解决医疗AI缺乏可解释性的问题，系统定位于提供客观依据的辅助工具，不直接输出诊断结论。系统构建了管道式的证据链生成机制，将算法推断过程透明化，交由医生裁决：

1. **特征提取与显著性视觉定位生成**：基于预训练ResNet50对皮肤镜影像进行深层特征提取，利用Grad-CAM算法计算目标类别对最后卷积层的梯度权重，生成病灶显著性区域热力图。该热力图客观标定病灶位置与关注区域，作为后续推理的视觉定位依据。工程上，需使用`register_full_backward_hook`替代PyTorch已废弃的`register_backward_hook`，确保梯度抓取的准确性。
2. **形态学结构化约束与诊断结论剥离**：将热力图与原图共同输入视觉语言模型（DeepSeek-VL2）。为规避生成式模型无约束推断带来的事实偏移，系统通过严格的Prompt设计强制模型输出JSON格式的形态学描述（如边缘不规则、色素网络变异等）。此外，工程解析层实现正则过滤方法（`_filter_diagnosis`），直接剥离模型输出中夹带在描述字段内的诊断性陈述，确保形态描述的客观性。
3. **RAG文献补充与辅助证据链构建**：集成模块基于形态学描述执行RAG检索，利用`BAAI/bge-small-zh-v1.5`模型将查询向量化，从Qdrant向量知识库中召回相关医学文献片段并拼接上下文。系统最终交付医生的辅助视图包含：原图、热力图标注、客观形态描述、文献参考。
4. **证据链完整性校验与降级策略**：在工程逻辑层，系统强制校验证据组件的存在性。若Grad-CAM生成失败或RAG无有效文献支撑，系统判定证据链断裂，抛出`DiagnosisUncertainException`异常，前端执行降级提示。同时，针对VLM API不可用或超时的场景，系统实现降级开关（读取环境变量`USE_MOCK_VLM`），当开关开启或API调用异常时，自动捕获错误并返回预设的Mock JSON，保障演示与基础流程的连贯性。

### 3.2 主索引映射与标准协议的数据集成机制

针对多源异构数据孤岛，系统在应用平台域实现基于映射路由的归集与标准协议适配，仅建立路由映射读取外部系统，不对外部异构库做侵入性写入：

1. **标准协议接入**：通过适配器解析符合FHIR R4规范的HIS/EMR/LIS虚拟资源，将非标准化的临床数据映射为`Patient`、`Observation`、`Condition`等标准资源，标准化临床数据入口。
2. **交叉标识提取与多级匹配**：从各源系统数据中提取患者核心身份标识。首选通过身份证号精确匹配；若缺失，则通过姓名与手机号组合匹配；最后结合出生日期、性别等辅助字段确认，解决跨系统患者标识不一致的问题。
3. **主索引映射元数据**：构建EMPI映射元数据表，将不同源系统的`SourcePatientID`与系统内部生成的`GlobalPatientID`建立关联。系统仅存储路由映射关系，不搬运源系统业务数据。
4. **只读路由与融合查询**：当医生请求患者全生命周期视图时，应用域通过映射表查得该患者在源系统的`SourcePatientID`，通过标准API或只读视图路由获取详情，在应用层完成多源数据的逻辑拼装。

### 3.3 基于成像特性的影像转码与前端内存管控

PACS下发的DICOM影像在前端解析存在性能瓶颈，系统基于皮肤镜成像特性实施轻量化集成策略，兼顾渲染性能与医学信息完整性：

- **后端离线转码与色彩空间还原**：皮肤镜影像属表皮光学成像，无需像CT进行Hounsfield单位调窗操作。推理域提供离线摄取管线，利用`pydicom`解析DICOM。针对皮肤病诊断对色彩的高敏感度，管线依据`PhotometricInterpretation`标签执行精确的色彩空间还原逻辑：针对`YBR_FULL_422`/`YBR_FULL`，必须使用`convert_color_space`转回RGB；针对`MONOCHROME1`执行灰度反转逻辑（`255 - pixel_array`）；针对`MONOCHROME2`执行常规归一化。同时应用RescaleSlope/Intercept将像素映射至0-255 uint8，确保皮肤病灶色彩无失真，随后转存为Web友好的PNG格式。
- **摄取接口与UID绑定**：推理域提供上传接口（`/upload`）与离线URL摄取接口（`/ingest`，基于`httpx.AsyncClient`实现异步下载，超时设置15秒防阻塞）。原始文件落盘至`uploads/`后，同步调用解析器转码，PNG存入`static/images/`。提取`PatientID`、`StudyInstanceUID`等关键元数据，在自有数据库建立映射记录，将UID与转存的PNG路径强绑定，并记录真实宽高与DICOM原始标签。
- **前端渲染与内存生命周期管控**：针对高分辨率影像导致的浏览器内存泄漏风险，前端采用`createObjectURL`进行大图按需加载，并在React组件卸载或患者上下文切换时，严格调用`revokeObjectURL`释放Blob对象，防止影像堆积导致的页面崩溃。

### 3.4 异步响应代理与断连感知计算回收机制

医疗AI推理耗时较长，为避免资源浪费与级联阻塞，系统构建了端到端的异步与资源回收逻辑：

- **应用域响应式代理**：Spring Boot规避同步阻塞调用智能推理域。通过响应式客户端转发前端请求，将FastAPI的SSE（Server-Sent Events）流反向代理给前端，防止线程池被长连接耗尽。
- **SSE流状态契约**：SSE通道严格定义事件类型契约：`step`（中间推理流）、`result`（成功终结）、`error`（业务异常如证据链断裂）以及`heartbeat`（防止中间件静默断连）。前端状态机据此实现完整的交互逻辑与降级提示。
- **断连感知与流式步级推理终止逻辑**：当医生关闭页面或网络断开时，应用域感知连接中断并停止拉取SSE流。由于深度学习模型前向推理属于密集计算，Python无法直接中断正在执行的C++底层张量运算。因此，智能推理域FastAPI将耗时的推理任务（Grad-CAM、VLM调用）解耦至独立线程池运行（`asyncio.to_thread`），主协程通过`await request.is_disconnected()`实时监测连接状态。一旦断连即刻设置请求级的`threading.Event`终止信号，GPU推理循环在**流式生成的步间**（如Grad-CAM结束、VLM调用前、RAG检索前）检查该信号并主动退出循环，局部计算张量脱离作用域由Python垃圾回收释放资源，防止计算资源无效占用。

```python
# 智能推理域 FastAPI 核心推理终止逻辑
async def stream_diagnosis(request: Request, task_id: str):
    # 构建请求级的取消事件，严禁使用全局Event导致并发污染
    cancel_event = threading.Event()
    # 将同步推理解耦至独立线程，保障异步断连感知不阻塞
    inference_task = asyncio.create_task(
        asyncio.to_thread(run_agent_pipeline, cancel_event)
    )
    try:
        while not inference_task.done():
            if await request.is_disconnected():
                logger.warning(f"Client disconnected. Aborting task: {task_id}")
                cancel_event.set() # 通知推理线程在下一个生成步终止
                return # 终止SSE流，不再推送给已断开的客户端
            yield sse_format("heartbeat") # 兑现心跳契约
            await asyncio.sleep(0.1)
        # 正常完成推理，输出最终结果
        result_data = await inference_task
        yield sse_format(result_data)
    except asyncio.CancelledError:
        cancel_event.set()

# --- 推理域推理线程中的步级终止检查示例 ---
def run_agent_pipeline(cancel_event):
    for step in model_generate_steps: 
        # 在每个生成步的间隔检查终止信号，无法中断单步内部的张量计算
        if cancel_event.is_set():
            logger.info("Inference cancelled at step level, exiting loop.")
            return None # 退出计算循环，局部张量释放
        # 执行单步推理并产出...
```

- **长连接保活配置**：Nginx网关需对SSE路径配置`proxy_read_timeout 300s`与`proxy_buffering off`，确保SSE流不被缓存阻塞。

### 3.5 数据存储与资源限制配置

针对集成的结构化临床数据与AI非结构化特征，实施规范化的存储建模与轻量级资源管控：

- **多模态数据存储映射**：推理域采用SQLAlchemy ORM映射数据库表结构。针对影像资源，设立`status`字段标识处理状态（`processing`/`ready`），`url`字段记录转码后路径，`original_dicom_tags`字段以JSON形式存储DICOM元数据，`width`与`height`记录真实影像维度，兼顾关系型查询的严谨性与非结构化元数据的存储需求。
- **低资源环境容器约束**：在2核4G的极限部署环境下，通过`docker-compose.yml`强制限制基础组件内存上限（如MySQL限制512M，Qdrant限制512M），防止OOM导致进程被杀。同时，深度学习框架强制指定CPU版本（如`torch==2.1.0+cpu`），剔除冗余的CUDA库，将镜像体积压缩至可部署范围。

---

## 4. 协作范式与项目拓扑

本项目由两位协作方共同完成，采用API契约驱动开发模式，服务域严格隔离。智能推理域聚焦于AI工程与数据治理，应用平台域聚焦于全栈高可用与医疗标准落地。

### 4.1 角色矩阵

| 协作方     | 核心职责域                                                   | 工程侧重                                                    |
| :--------- | :----------------------------------------------------------- | :---------------------------------------------------------- |
| **算法端** | 智能推理域（AI子系统、影像预处理、RAG知识库）                | 视觉定位提取、形态学结构化约束、DICOM转码管线与检索增强生成 |
| **工程端** | 应用平台域（业务服务、前端交互、数据访问、协议接入、路由映射） | 异构数据集成归一、异步代理高可用保障、临床交互与内存管控    |

### 4.2 目录结构

```text
DermaIntegrate/
├── backend-ai/                  # [智能推理域] 智能推理层
│   ├── sql/                     # 推理域数据库初始化脚本
│   ├── models/                  # SQLAlchemy ORM 模型定义（数据库访问层）
│   ├── agents/                  # Multi-Agent交互逻辑与VLM降级策略
│   ├── cnn/                     # ResNet50与Grad-CAM生成器
│   ├── rag/                     # LlamaIndex + Qdrant 向量检索与文档加载
│   ├── api/                     # FastAPI路由定义与SSE流式输出
│   ├── preprocessing/           # DICOM离线摄取管线与色彩空间还原
│   └── exceptions.py            # 证据链断裂等自定义业务异常
│
├── backend-app/                 # [应用平台域] 应用服务层
│   ├── sql/                     # 应用域的数据库脚本
│   ├── empi/                    # 主索引映射引擎与跨系统只读路由
│   ├── fhir/                    # FHIR R4 Adapter解析标准资源
│   ├── service/                 # 患者临床视图聚合、AI诊断响应式异步代理
│   └── repository/              # MySQL数据访问与业务查询
│
├── frontend/                    # [应用平台域] 表现层
│   ├── components/              # 影像滑动对比组件 (原图与病灶标注图叠加渲染)
│   ├── hooks/                   # useSSE状态机封装与断线重试逻辑
│   └── views/                   # 医生工作站界面与AI辅助诊断流式对话框
│
├── infra/                       # [推理域定义拓扑，应用域主导实施]
│   ├── docker-compose.yml       # 微服务编排与容器内存限制配置
│   ├── nginx/                   # 反向网关路由与SSE长连接超时配置
│   └── mock-fhir-data/          # 虚拟患者JSON资源池 (符合FHIR R4规范)
│
└── docs/                        # 契约文档与API定义
    └── api-contract.yaml        # 前后端与AI推理域的SSE交互契约 (OpenAPI规范)
```

---

## 5. 部署与运行

### 5.1 环境配置

系统采用Docker Compose编排微服务拓扑，针对2核4G低资源环境进行了深度适配。

前提条件：由于本系统在当前阶段主要面向CPU环境部署推理，无需宿主机具备GPU及NVIDIA Container Toolkit。系统已在Dockerfile中指定PyTorch CPU版本。

```bash
git clone https://github.com/yourname/DermaIntegrate.git
cd DermaIntegrate
```

<details>
<summary>核心依赖与版本控制</summary>

```text
# 智能推理域 Python 核心依赖
torch==2.1.0+cpu               # 深度学习框架（CPU版本，显著缩减镜像体积）
pytorch-grad-cam==1.5.0        # 基于梯度的类激活图(热力图)生成
fastapi==0.109.0               # 高性能异步Web框架
uvicorn==0.27.0                # ASGI服务器
llama-index==0.10.0            # RAG检索增强生成框架
qdrant-client==1.7.0           # Qdrant向量数据库客户端
sentence-transformers==2.3.1   # 文本向量化模型加载
pydicom==2.4.3                 # DICOM医学影像解析与元数据提取
Pillow==10.1.0                 # 图像处理与色彩空间转换
numpy==1.26.2                  # 数值计算与像素归一化
httpx==0.25.2                  # 异步HTTP客户端(用于离线摄取)
openai>=1.0.0                  # DeepSeek API 兼容客户端依赖
python-dotenv==1.0.0           # 环境变量配置加载

# 应用平台域 Java 核心依赖 (基于 Spring Boot 3.x)
org.springframework.boot:spring-boot-starter-webflux    # 响应式非阻塞WebClient
ca.uhn.hapi.fhir:hapi-fhir-base:6.8.0                  # FHIR R4国际医疗协议解析
com.mysql:mysql-connector-j:8.0.33                      # MySQL驱动

# 基础设施组件
mysql:8.0                      # 关系型数据库
qdrant/qdrant:latest           # 高性能RAG向量数据库
redis:7                        # 分布式缓存（应用域使用）
```
</details>

### 5.2 参数配置
在启动服务前，需在相关模块配置必要参数：

**1. 智能推理域配置**：在 `backend-ai/.env` 中配置大模型接口参数、数据库连接与降级开关：
```env
# 数据库连接配置 (需与docker-compose映射端口一致，如本地3306被占用可改为3307)
DATABASE_URL=mysql+aiomysql://root:root_password@localhost:3307/derma_ai

# 视觉语言模型配置：DeepSeek-VL2 (用于形态学描述)
VLM_API_KEY=your_deepseek_api_key
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-vl2

# RAG向量数据库配置
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=derma_knowledge

# 降级开关配置：当设置为true时，VLM调用将被拦截并返回Mock数据
USE_MOCK_VLM=false
```

**2. 应用平台域配置**：在 `backend-app/src/main/resources/application.yml` 中配置数据库与智能推理域路由：
```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/derma_integrate?useSSL=false&characterEncoding=utf8
    username: root
    password: root_password

# 智能推理域路由地址
ai:
  pipeline:
    base-url: http://localhost:8000
```

### 5.3 运行模式

**全链路联合启动**：
一键启动所有微服务，构建完整的数据集成与辅助诊断验证环境。首次启动将自动挂载初始化脚本建库建表。由于限制了MySQL与Qdrant的内存使用，请确保服务器至少具有4G可用内存。
```bash
docker-compose up -d
```
启动后访问 `http://localhost/` 即可进入医生工作站。系统内置Mock Server将自动灌入虚拟患者数据，支持从“多源数据集成接入 -> 主索引映射归一 -> 影像调阅 -> AI可解释证据链辅助 -> 医生裁决”的完整流程验证。

**智能推理域独立调试**：
适用于算法迭代与模型推理逻辑验证，无需启动Java后端与前端。
```bash
# 前提：需先启动依赖的基础设施
docker-compose up -d mysql qdrant

cd backend-ai
# 初始化RAG知识库向量数据 (需预先在rag/docs/下放置文本文档)
python rag/init_knowledge_base.py
uvicorn api.main:app --reload --port 8000
# 可使用Postman上传真实.dcm文件测试转码，或触发SSE流测试推理管线与降级逻辑
```

**应用平台域独立调试**：
适用于业务逻辑开发与前端交互调试，AI请求将路由至云端或本地宿主机的推理服务。
```bash
# 前提：需先启动依赖的基础设施
docker-compose up -d mysql redis

# 1. 启动后端服务
cd backend-app
mvn spring-boot:run
# 测试主索引路由聚合、FHIR解析与响应式异步代理

# 2. 启动前端界面
cd frontend
npm install
npm run dev
# 测试患者临床视图、影像滑动对比与SSE流式交互
```

---

## 6. 架构约束与设计原则

为保障多源数据集成的准确性及AI辅助的可解释性，本项目在代码级实施了以下硬性约束，任何联调与迭代均不可逾越：

1. **可解释证据链优先原则**：系统仅提供视觉定位与形态学特征作为辅助，不直接输出诊断结论。VLM必须受强制JSON格式约束并经后端过滤剥离诊断性输出；若Grad-CAM或RAG关键组件缺失，均判定为证据链断裂，抛出`DiagnosisUncertainException`触发降级提示，交还医生裁量。
2. **数据归一化与非侵入原则**：应用域仅通过主索引建立路由映射逻辑聚合多源数据，通过标准协议接入，严禁对医院现有异构源系统进行侵入性写入或直连表操作。
3. **计算转码与前端渲染分离原则**：前端规避引入Cornerstone等重型DICOM解析库。所有医疗影像必须由推理域在后端预处理（含色彩空间还原与归一化）为Web标准格式，前端仅负责渲染与内存生命周期管控。
4. **异步与非阻塞原则**：应用域规避以同步阻塞方式调用推理域的AI接口。必须遵循异步SSE契约，且推理域必须将同步推理解耦至独立线程，配合异步事件循环实现断连步级终止机制，防止计算资源无效占用。
5. **契约驱动与服务隔离原则**：推理域与应用域的协作严格遵循`docs/api-contract.yaml`定义的数据结构、SSE事件类型与流式事件格式。推理域不可擅自变更Schema，平台域不可硬编码解析契约外字段，确保异构系统并行开发与集成。