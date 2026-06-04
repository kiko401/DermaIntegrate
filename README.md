# DermaIntegrate: 皮肤病多源数据集成与智能辅助诊断平台

**许可协议**：MIT License 
**运行环境**：Python 3.10+ / Java 17+ (Spring Boot 3.x+) / Node 18+ 
**系统架构**：基于API契约的模块解耦，推理服务与应用服务进程级隔离与独立部署

---

## 摘要

本项目面向皮肤病专科门诊场景，针对临床业务中多源异构数据孤岛与医疗AI缺乏可解释性的双重问题，构建数据集成与可解释辅助诊断平台。在数据集成层面，针对HIS、PACS、LIS等系统数据异构、标识不一的问题，基于FHIR R4标准与EMPI主索引映射，实现跨系统异构数据的归一化接入与逻辑聚合，构建患者全生命周期临床视图；在AI辅助层面，针对端到端模型直接输出诊断结论缺乏推理依据的问题，提出基于显著性区域定位与检索增强的可解释机制：通过CNN提取特征并生成Grad-CAM热力图提供客观视觉定位，约束视觉语言模型输出结构化形态学描述，并融合RAG检索构建辅助证据链，将算法推断过程透明化，最终诊断裁量权交由临床医生。工程层面，系统针对医学影像前端解析瓶颈与长时AI推理引发的级联故障风险，分别实现了基于成像特性的后端转码与前端轻量渲染机制，以及基于SSE的异步响应代理与断连感知计算资源回收机制，保障临床环境下的系统可用性。

---

## 1. 核心问题与方法映射

针对皮肤病临床业务中的数据流转与AI应用问题，本平台的应对策略与工程机制如下：

| 临床工程问题                                                 | 本系统应对策略与工程机制                                     |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| **多源异构数据孤岛**：HIS、LIS、PACS等系统数据异构，患者标识不一，难以形成完整临床视图。 | **EMPI主索引与FHIR标准归一化**：基于EMPI映射跨系统患者标识，结合HAPI FHIR适配器解析R4标准资源，实现异构数据的逻辑聚合与患者全生命周期视图构建，不侵入源系统。 |
| **医疗AI缺乏可解释性**：端到端模型直接生成诊断结论缺乏推理依据，医生无法验证，存在事实偏移风险。 | **显著性视觉定位与可解释证据链**：基于CNN生成显著性热力图提供视觉定位，约束大模型输出结构化形态学描述，并融合RAG文献检索，构建可验证的辅助证据链，系统不直接输出诊断结论。 |
| **DICOM影像前端解析瓶颈**：PACS下发的DICOM影像强依赖重型解析库实时渲染，导致浏览器内存溢出与交互卡顿。 | **基于成像特性的影像转码与轻量渲染**：基于皮肤镜无需调窗的特性，后端离线解析DICOM并执行色彩空间还原转码为PNG，结合前端轻量滑动对比组件，实现影像数据的透明集成调阅。 |
| **长时AI推理引发的级联故障**：AI推理耗时导致业务线程池长期占用，微服务并发能力衰减甚至引发级联崩溃。 | **异步响应代理与计算资源回收**：基于SSE异步契约解耦业务与推理，建立断连感知逻辑，前端断连即终止GPU流式推理步，防止计算资源无效占用与线程池耗尽。 |

---

## 2. 系统架构设计

系统遵循“推理计算与业务流转解耦”原则，划分两大进程级隔离服务域：**智能推理域**负责AI推理、特征提取与影像预处理；**应用平台域**负责数据集成归一、标准协议接入与前端交互。

```text
③ 表现层（应用平台域 - React 18 + AntD + ECharts）
  ├─ 医生工作站 (患者全生命周期临床视图聚合展示)
  ├─ 影像滑动对比组件 (原图/标注图叠加渲染)
  └─ AI辅助诊断流式对话框 (展示可解释证据链，医生裁决)

② 服务与数据层（跨域协同）
  ├─ 智能推理域：ResNet50 + Grad-CAM 视觉定位提取 | DeepSeek-VL2 结构化形态描述 | DeepSeek-V3 + RAG 知识检索
  ├─ 应用平台域：患者临床视图聚合 | EMPI主索引映射 | FHIR R4 Adapter | AI诊断异步代理 | Sentinel 熔断
  ├─ 推理域数据核心：独立数据库 (影像UID映射、AI特征与元数据存储)
  ├─ 应用域数据核心：MySQL 8 (关系与文档混合存储及虚拟生成列索引)
  └─ 缓存核心：Redis (布隆过滤器防穿透 | 随机TTL防缓存雪崩)

① 接入与预处理层
  ├─ DICOM离线摄取管线、色彩空间还原、像素转码、元数据提取与UID绑定 (推理域执行)
  └─ HAPI FHIR Mock Server (仿真HIS/EMR/LIS，应用域接入)

⓪ 基础设施层
  ├─ Docker Compose 编排与GPU显存隔离配置
  └─ Nginx 网关路由与SSE长连接超时配置
```

---

## 3. 关键工程实现与核心机制

### 3.1 基于视觉定位与检索增强的可解释辅助机制

为解决医疗AI缺乏可解释性的问题，系统定位于提供客观依据的辅助工具，不直接输出诊断结论。系统构建了管道式的证据链生成机制，将算法推断过程透明化，交由医生裁决：

1. **特征提取与显著性视觉定位生成**：基于微调ResNet50对皮肤镜影像进行深层特征提取，利用Grad-CAM算法计算目标类别对最后卷积层的梯度权重，生成病灶显著性区域热力图。该热力图客观标定病灶位置与关注区域，作为后续推理的视觉定位依据。
2. **形态学结构化约束与诊断结论剥离**：将热力图与原图共同输入视觉语言模型（DeepSeek-VL2）。为规避生成式模型无约束推断带来的事实偏移，系统通过严格的Prompt设计结合`response_format`强制JSON输出格式，限制模型仅输出对病灶客观形态学特征的描述（如边缘不规则、色素网络变异等）。此外，工程解析层对模型输出实施正则过滤，直接剥离任何夹带在描述字段中的诊断性陈述，确保形态描述的客观性。
3. **RAG文献补充与辅助证据链构建**：`IntegratorAgent`（基于DeepSeek-V3编排）基于形态学描述执行RAG检索，从向量知识库中召回相关医学文献片段并拼接上下文。系统最终交付医生的辅助视图包含：原图、热力图标注、客观形态描述、文献参考。
4. **证据链完整性校验与降级**：在工程逻辑层，系统强制校验证据组件的存在性。若Grad-CAM生成失败或RAG无有效文献支撑（Citation上下文为空），系统判定证据链断裂，抛出`DiagnosisUncertainException`异常，前端执行降级提示，拒绝展示缺乏依据的推断结果。

### 3.2 EMPI主索引与FHIR标准的数据集成机制

针对多源异构数据孤岛，系统在应用平台域实现基于映射路由的EMPI归集与FHIR标准适配，仅建立路由映射读取外部系统，不对外部异构库做侵入性写入：

1. **FHIR标准协议接入**：引入HAPI FHIR构建适配器，解析符合R4规范的HIS/EMR/LIS虚拟资源，将非标准化的临床数据映射为`Patient`、`Observation`、`Condition`等标准资源，标准化临床数据入口。
2. **交叉标识提取与多级匹配**：从各源系统数据中提取患者核心身份标识。首选通过身份证号精确匹配；若缺失，则通过姓名与手机号组合匹配；最后结合出生日期、性别等辅助字段确认，解决跨系统患者标识不一致的问题。
3. **主索引映射元数据**：在MySQL中构建EMPI映射元数据表，将不同源系统的`SourcePatientID`与系统内部生成的`GlobalPatientID`建立关联。系统仅存储路由映射关系，不搬运源系统业务数据。
4. **只读路由与融合查询**：当医生请求患者全生命周期视图时，应用域通过映射表查得该患者在源系统的`SourcePatientID`，通过标准API或只读视图路由获取详情，在应用层完成多源数据的逻辑拼装。

### 3.3 基于成像特性的影像转码与前端内存管控

PACS下发的DICOM影像在前端解析存在性能瓶颈，系统基于皮肤镜成像特性实施轻量化集成策略，兼顾渲染性能与医学信息完整性：

- **后端离线转码与色彩空间还原**：皮肤镜影像属表皮光学成像，无需像CT进行Hounsfield单位调窗操作。推理域提供离线摄取管线，利用`pydicom`解析DICOM。针对皮肤病诊断对色彩的高敏感度，管线依据DICOM像素属性与内嵌ICC Profile，执行精确的色彩空间还原逻辑（将DICOM常见的`YBR_FULL_422`等医学色彩映射转换至标准RGB色彩空间），确保皮肤病灶色彩无失真，随后转存为Web友好的PNG格式，剥离前端重型解析库依赖。
- **跨域数据路由与UID绑定**：应用域接收到外部系统的影像通知后，异步触发推理域摄取任务。推理域提取`PatientID`、`StudyInstanceUID`等关键元数据，在自有数据库建立`ImageResource`映射表，将UID与转存的PNG路径强绑定。调阅时，应用域携带UID请求推理域获取PNG路径及关联元数据，代理转发前端渲染，确保服务隔离下医学信息的完整关联。
- **前端渲染与内存生命周期管控**：针对高分辨率影像导致的浏览器内存泄漏风险，前端采用`createObjectURL`进行大图按需加载，并在React组件卸载或患者上下文切换时，严格调用`revokeObjectURL`释放Blob对象，防止影像堆积导致的页面崩溃。

### 3.4 异步响应代理与断连感知计算回收机制

医疗AI推理耗时较长，为避免微服务架构下的级联故障与计算资源浪费，系统构建了端到端的异步与资源回收逻辑：

- **应用域响应式代理**：Spring Boot规避同步阻塞调用智能推理域。通过`WebClient`转发前端请求，将FastAPI的SSE（Server-Sent Events）流反向代理给前端，防止Tomcat线程池被长连接耗尽。
- **SSE流状态契约**：SSE通道严格定义事件类型契约：`step`（中间推理流）、`result`（成功终结）、`error`（业务异常如证据链断裂）以及`heartbeat`（防止中间件静默断连）。前端`useSSE`状态机据此实现完整的交互逻辑与降级提示。
- **断连感知与流式步级推理终止逻辑**：当医生关闭页面或网络断开时，应用域的`WebClient`感知连接中断并停止拉取SSE流。由于深度学习模型前向推理（尤其是大语言模型的自回归生成）属于密集计算，Python无法直接中断正在执行的C++底层张量运算。因此，智能推理域FastAPI将GPU推理任务解耦至独立线程池运行，主协程通过`await request.is_disconnected()`实时监测连接状态。一旦断连即刻设置请求级的`threading.Event`终止信号，GPU推理循环在**流式生成的步间**（即每次Token生成返回Python事件循环的间隔）检查该信号并主动退出循环，局部计算张量脱离作用域由Python垃圾回收释放显存，防止计算资源无效占用。

```python
# 智能推理域 FastAPI 核心推理终止逻辑
async def stream_diagnosis(request: Request, task_id: str):
    # 构建请求级的取消事件，严禁使用全局Event导致并发污染
    cancel_event = threading.Event()
    # 将同步GPU推理解耦至独立线程，保障异步断连感知不阻塞
    inference_task = asyncio.create_task(
        asyncio.to_thread(run_agent_pipeline, cancel_event)
    )
    try:
        while not inference_task.done():
            if await request.is_disconnected():
                logger.warning(f"Client disconnected. Aborting GPU task: {task_id}")
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
    # 假设 model_generate_steps 为流式生成的迭代器
    for step in model_generate_steps: 
        # 在每个生成步的间隔检查终止信号，无法中断单步内部的张量计算
        if cancel_event.is_set():
            logger.info("Inference cancelled at step level, exiting loop.")
            return None # 退出计算循环，局部张量释放显存
        # 执行单步推理并产出Token...
```

- **长连接保活配置**：Nginx网关需对SSE路径配置`proxy_read_timeout 300s`与`proxy_buffering off`，Java WebClient需配置匹配的响应式读取超时，确保SSE流的稳定传输。

### 3.5 关系与文档混合存储及缓存防护

针对集成的结构化临床数据与AI非结构化特征，实施精细化建模与防护：

- **关系与文档混合结构（MySQL JSON + 虚拟生成列）**：采用`ai_features(JSON)`存储大模型输出的非结构化描述与RAG检索上下文。为避免JSON列滥用导致的全表扫描性能衰退，系统利用MySQL 8的**虚拟生成列**技术，将高频查询与过滤字段（如`lesion_type`和`confidence`）从JSON中自动提取为虚拟关系化列，并对虚拟列建立B-Tree索引。此方案既保留了JSON的灵活性，又获得了等价于传统关系型字段的查询性能，且无需应用层双写同步。
  ```sql
  -- DDL 示例：利用生成列实现 JSON 内部字段的高效索引
  CREATE TABLE patient_diagnosis (
      id BIGINT PRIMARY KEY,
      ai_features JSON NOT NULL,
      -- 虚拟生成列：从JSON提取病灶类型与置信度
      lesion_type VARCHAR(50) GENERATED ALWAYS AS (json_unquote(json_extract(ai_features, '$.lesion_type'))) VIRTUAL,
      confidence DECIMAL(5,4) GENERATED ALWAYS AS (CAST(json_extract(ai_features, '$.confidence') AS DECIMAL(5,4))) VIRTUAL,
      -- 对生成列建索引，等同于对JSON内部字段建索引
      INDEX idx_lesion_type (lesion_type),
      INDEX idx_confidence (confidence)
  );
  ```
- **缓存高可用防护策略**：在Redis缓存层面，针对不存在的无效查询采用布隆过滤器拦截防穿透（系统启动加载高频标识并监听动态更新）；针对热点数据采用随机TTL防缓存雪崩；针对极热Key过期瞬间的并发穿透采用互斥锁或逻辑过期防击穿，保障高并发下数据库的安全。

---

## 4. 协作范式与项目拓扑

本项目由两位协作方共同完成，采用API契约驱动开发模式，服务域严格隔离。智能推理域聚焦于AI工程与数据治理，应用平台域聚焦于全栈高可用与医疗标准落地。

### 4.1 角色矩阵

| 协作方     | 核心职责域                                                   | 工程侧重                                                   |
| :--------- | :----------------------------------------------------------- | :--------------------------------------------------------- |
| **算法端** | 智能推理域（AI子系统、影像预处理、RAG知识库）                | 视觉定位提取、形态学结构化约束、多源数据治理与检索增强生成 |
| **工程端** | 应用平台域（业务服务、前端交互、数据访问、FHIR接入、EMPI路由） | 异构数据集成归一、异步代理高可用保障、临床交互与内存管控   |

### 4.2 目录结构

```text
DermaIntegrate/
├── backend-ai/                  # [智能推理域] 智能推理层
│   ├── sql/                     # 推理域数据库初始化脚本
│   ├── models/                  # SQLAlchemy ORM 模型定义（数据库访问层）
│   ├── agents/                  # Multi-Agent交互逻辑
│   ├── cnn/                     # ResNet50微调与Grad-CAM
│   ├── rag/                     # LlamaIndex + Qdrant
│   ├── api/                     # FastAPI路由定义
│   └── preprocessing/           # DICOM离线摄取管线
│
├── backend-app/                 # [应用平台域] 应用服务层
│   ├── sql/                     # 应用域的数据库脚本
│   ├── empi/                    # EMPI主索引映射引擎与跨系统只读路由
│   ├── fhir/                    # HAPI FHIR Adapter解析标准R4资源
│   ├── service/                 # 患者临床视图聚合、AI诊断响应式异步代理
│   ├── config/                  # Sentinel熔断降级与线程池隔离配置
│   └── repository/              # MySQL数据访问(含JSON与生成列映射)与缓存防护策略
│
├── frontend/                    # [应用平台域] 表现层
│   ├── components/              # 影像滑动对比组件 (原图与病灶标注图叠加渲染)
│   ├── hooks/                   # useSSE状态机封装与断线重试逻辑
│   └── views/                   # 医生工作站界面与AI辅助诊断流式对话框
│
├── infra/                       # [推理域定义拓扑，应用域主导实施]
│   ├── docker-compose.yml       # 异构微服务编排与GPU显存隔离配置
│   ├── nginx/                   # 反向网关路由与SSE长连接超时配置
│   └── mock-fhir-data/          # 虚拟患者JSON资源池 (符合FHIR R4规范)
│
└── docs/                        # 契约文档与API定义
    └── api-contract.yaml        # 前后端与AI推理域的SSE交互契约 (OpenAPI规范)
```

---

## 5. 部署与运行

### 5.1 环境配置

系统采用Docker Compose编排异构微服务拓扑，屏蔽底层环境差异。

前提条件：如需体验AI辅助诊断功能，宿主机需安装NVIDIA Container Toolkit以支持容器级别的GPU显存隔离与调度，并在 `docker-compose.yml` 中正确配置 `deploy.resources.reservations.devices`。

```bash
git clone https://github.com/yourname/DermaIntegrate.git
cd DermaIntegrate
```

<details>
<summary>核心依赖与版本控制</summary>

```text
# 智能推理域 Python 核心依赖
torch==2.1.0+cu118             # 深度学习框架与CUDA支持
pytorch-grad-cam==1.5.0        # 基于梯度的类激活图(热力图)生成
fastapi==0.109.0               # 高性能异步Web框架
llama-index==0.10.0            # RAG检索增强生成框架
pydicom==2.4.3                 # DICOM医学影像解析与元数据提取
openai>=1.0.0                  # DeepSeek API 兼容客户端依赖

# 应用平台域 Java 核心依赖 (基于 Spring Boot 3.x)
org.springframework.boot:spring-boot-starter-webflux    # 响应式非阻塞WebClient
org.springframework.boot:spring-boot-starter-data-redis # Redis缓存与布隆过滤器支持
ca.uhn.hapi.fhir:hapi-fhir-base:6.8.0                  # FHIR R4国际医疗协议解析
com.alibaba.csp:sentinel-datasource-nacos               # 微服务熔断降级与流量控制
com.mysql:mysql-connector-j:8.0.33                      # MySQL驱动(支持JSON与生成列)

# 基础设施组件
mysql:8.0                      # 关系型数据库 (支持JSON与虚拟生成列索引)
qdrant/qdrant:latest           # 高性能RAG向量数据库
redis:7                        # 分布式缓存与防护组件
```
</details>

### 5.2 参数配置
在启动服务前，需在相关模块配置必要参数：

**1. 智能推理域配置**：在 `backend-ai/.env` 中配置大模型接口参数与向量库连接：
```env
# 视觉语言模型配置：DeepSeek-VL2 (用于形态学描述)
VLM_API_KEY=your_deepseek_api_key
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-vl2

# 文本语言模型配置：DeepSeek-V3 (用于RAG与Agent逻辑编排)
LLM_API_KEY=your_deepseek_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# RAG向量数据库配置
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=derma_knowledge
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
一键启动所有微服务，构建完整的数据集成与辅助诊断验证环境。首次启动将自动挂载`infra/sql/`下的DDL脚本初始化数据库表结构。
```bash
docker-compose up -d
```
启动后访问 `http://localhost/` 即可进入医生工作站。系统内置FHIR Mock Server将自动灌入虚拟患者数据，支持从“多源数据集成接入 -> EMPI映射归一 -> 影像调阅 -> AI可解释证据链辅助 -> 医生裁决”的完整流程验证。

**智能推理域独立调试**：
适用于算法迭代与模型推理逻辑验证，无需启动Java后端与前端。
```bash
# 前提：需先启动依赖的基础设施
docker-compose up -d mysql qdrant

cd backend-ai
# 初始化RAG知识库向量数据
python rag/init_knowledge_base.py
uvicorn api.main:app --reload --port 8000
# 可使用Mock影像路径直接测试SSE流式输出与形态学结构化约束
```

**应用平台域独立调试**：
适用于业务逻辑开发与前端交互调试，AI请求将路由至云端或本地宿主机的推理服务。
```bash
# 前提：需先启动依赖的基础设施
docker-compose up -d mysql redis

# 1. 启动后端服务
cd backend-app
mvn spring-boot:run
# 测试EMPI路由聚合、FHIR解析、响应式异步代理与JSON生成列映射

# 2. 启动前端界面
cd frontend
npm install
npm run dev
# 测试患者临床视图、影像滑动对比与SSE流式交互
```

---

## 6. 架构约束与设计原则

为保障多源数据集成的准确性及AI辅助的可解释性，本项目在代码级实施了以下硬性约束，任何联调与迭代均不可逾越：

1. **可解释证据链优先原则**：系统仅提供视觉定位与形态学特征作为辅助，不直接输出诊断结论。VLM必须受强制JSON格式约束并经后端过滤剥离诊断性输出；若Grad-CAM或RAG关键组件缺失，均判定为证据链断裂，触发降级提示，交还医生裁量。
2. **数据归一化与非侵入原则**：应用域仅通过EMPI建立路由映射逻辑聚合多源数据，通过FHIR标准协议接入，严禁对医院现有异构源系统进行侵入性写入或直连表操作。
3. **计算转码与前端渲染分离原则**：前端规避引入Cornerstone等重型DICOM解析库。所有医疗影像必须由推理域在后端预处理（含色彩空间还原）为Web标准格式，前端仅负责渲染与内存生命周期管控。
4. **异步与非阻塞原则**：应用域规避以同步阻塞方式调用推理域的AI接口。必须遵循异步SSE契约，且推理域必须将同步GPU推理解耦至独立线程，配合异步事件循环实现断连步级终止机制，防止计算资源无效占用。
5. **契约驱动与服务隔离原则**：推理域与应用域的协作严格遵循`docs/api-contract.yaml`定义的数据结构、SSE事件类型与流式事件格式。推理域不可擅自变更Schema，平台域不可硬编码解析契约外字段，确保异构系统并行开发与集成。