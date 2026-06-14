# frontend-plan.md — 前端页面设计方案

> 本文档描述医生工作站前端的页面结构、职责、数据来源与实现顺序。
> 状态标记：✅ 已实现 / 🔶 设计占位 / ⬜ 待实现

---

## 一、医生工作流

```
找到患者 → 进入就诊详情 → 新建就诊 → 发起 AI 分析 → 看诊断结果
```

---

## 二、页面结构

> 已更新为当前实际实现（2026-06-15）

### 布局

App.vue 为侧边栏布局（200px 固定侧边栏 + 主内容区），侧边栏含路由导航和退出登录。登录页独立全屏，不含侧边栏。

### 路由与组件

| 路由 | 组件 | 职责 | 状态 |
|:---|:---|:---|:---|
| `/login` | `LoginView.vue` | 医生登录，httpOnly cookie 鉴权 | ✅ |
| `/dashboard` | `Dashboard.vue` | 工作台，统计卡片 + 最近就诊/任务 | ✅ 基本成形（静态内容为主） |
| `/patients` | `PatientList.vue` | 患者横向卡片 + 右侧就诊工作台 | ✅ 完整 |
| `/patients/:id` | `VisitDetail.vue` | 独立就诊详情页 + AI 分析入口 | ✅ 完整 |
| `/tasks` | `Tasks.vue` | AI 分析记录汇总 | ⬜ 占位（静态 mock 数据） |
| `/integration` | `Integration.vue` | 数据集成（Phase 3/4） | ⬜ 占位（展示"建设中"） |
| （组件）| `DiagnosisDialog.vue` | SSE 流式诊断 Drawer | ✅ 完整 |

---

## 三、各页面数据与接口

### PatientList.vue

| 动作 | 接口 |
|:---|:---|
| 加载列表 | `GET /api/patients` |
| 新建患者 | `POST /api/patients` |
| 跳转详情 | 前端路由 `/patients/:id` |

### VisitDetail.vue

| 动作 | 接口 |
|:---|:---|
| 加载患者信息 | `GET /api/patients/:id` |
| 加载就诊列表 | `GET /api/patients/:id/visits` |
| 新建就诊 | `POST /api/patients/:id/visits` |
| 发起 AI 分析 | `POST /api/tasks/upload`（带 `visit_id` + `clinical_text`） |
| 订阅推理进度 | `GET /api/tasks/:taskId/stream`（SSE，Phase 6） |

### DiagnosisDialog.vue（已实现）

| SSE 事件 | 渲染动作 |
|:---|:---|
| `image_done` | 显示图像分析模块（含热力图 + 形态学特征打字机） |
| `clinical_done` | 显示病历解析模块（打字机） |
| `pathology_done` | 显示病理分期模块（打字机） |
| `result` | 显示最终报告 Drawer，区分 `complete` / `incomplete`，风险等级色块 |
| `error` | 显示错误提示，关闭连接 |

---

## 四、接口与页面对应关系

| 接口 | Node 侧状态 | 前端使用页面 |
|:---|:---|:---|
| `GET /api/patients` | ✅ | PatientList |
| `POST /api/patients` | ✅ | PatientList |
| `GET /api/patients/:id` | ✅ | VisitDetail |
| `GET /api/patients/:id/visits` | ✅ | VisitDetail |
| `POST /api/patients/:id/visits` | ✅ | VisitDetail |
| `POST /api/tasks/upload` | ✅ | VisitDetail |
| `GET /api/tasks/:taskId/stream` | ✅ 代理层已实现 | DiagnosisDialog（Phase 6） |

---

## 五、最小实现顺序

**Phase 5（已完成）**：PatientList + VisitDetail + 上传拿 task_id + Dashboard + 侧边栏布局

**Phase 6（已完成）**：useSSE.js + DiagnosisDialog.vue + VisitDetail 集成

**Phase 7（待做）**：
- `src/components/ImageCompare.vue` — 原图 / 热力图滑动对比，Blob 内存管控

**Tasks.vue 真实化（待做）**：接真实接口，展示历史 ai_tasks 记录

**Integration.vue 真实化（待做）**：Phase 3 EMPI 完成后实现

---

## 六、低保真布局建议

### PatientList.vue

```
┌─────────────────────────────────────────┐
│  患者列表                    [新建患者]  │  ← 标题左，操作右
├─────────────────────────────────────────┤
│  姓名 │ 身份证号 │ 手机 │ 创建时间 │ 操作 │  ← 表格
│  ...  │  ...    │ ... │   ...   │查看就诊│
│  ...  │  ...    │ ... │   ...   │查看就诊│
└─────────────────────────────────────────┘
```

- 顶部：标题 + 新建按钮（space-between）
- 主体：a-table，操作列最右
- 弹窗：新建患者表单（姓名必填，身份证/手机可选）

### VisitDetail.vue

```
┌─────────────────────────────────────────┐
│  ← 返回列表                              │
├─────────────────────────────────────────┤
│  患者信息卡片                            │  ← a-descriptions，上半部分
│  姓名：xxx   手机：xxx   身份证：xxx      │
├─────────────────────────────────────────┤
│  就诊记录               [新建就诊]       │  ← 标题左，操作右
│  就诊日期 │ 主诉 │ 创建时间 │ 操作       │  ← 表格
│  ...      │ ... │   ...   │发起AI分析   │
├─────────────────────────────────────────┤
│  ✅ AI 任务已创建：task_id: xxxxx        │  ← 拿到 task_id 后展示（Phase 5）
│  （Phase 6：此处展示诊断对话框）          │
└─────────────────────────────────────────┘
```

- 上方：返回按钮 + 患者信息卡片（固定，不随滚动消失）
- 中间：就诊记录表格（核心内容区）
- 操作列："发起 AI 分析"弹出输入框再提交
- 底部：task_id 展示 alert（Phase 6 替换为诊断对话框）

### DiagnosisDialog.vue（Phase 6 参考）

```
┌─────────────────────────────────────────┐
│  AI 辅助诊断                        [x] │
├─────────────────────────────────────────┤
│  🔄 图像分析中...                        │  ← image_done 前
│  ✅ 图像特征：病灶位于左足底，直径约5mm   │  ← image_done 后
│  ✅ 病历解析：肢端黑素瘤高风险            │  ← clinical_done 后
│  ✅ 病理分期：T2b，建议完整切除          │  ← pathology_done 后
├─────────────────────────────────────────┤
│  最终报告（complete / incomplete badge） │  ← result 后
│  [参考文献引用]                          │
└─────────────────────────────────────────┘
```

- 整体用 a-modal 或右侧抽屉（a-drawer）
- 每个 Agent 结果用 a-steps 或分卡片展示，收到事件后动态追加
- incomplete 状态用 warning badge 标出缺失项
