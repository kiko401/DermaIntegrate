<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { message } from 'ant-design-vue'
import { apiFetch } from '@/utils/api'
import { useSSE } from '@/hooks/useSSE'
import ImageCompare from '@/components/ImageCompare.vue'

const route = useRoute()
const router = useRouter()
const patientId = route.params.patientId

// ── 侧栏拖拽宽度 ──────────────────────────────────────────
const rightWidthPct = ref(30)  // 15~45
const isDragging = ref(false)
const bodyRef = ref(null)

function onDividerMousedown(e) {
  isDragging.value = true
  e.preventDefault()
}

function onMousemove(e) {
  if (!isDragging.value || !bodyRef.value) return
  const rect = bodyRef.value.getBoundingClientRect()
  const pct = ((rect.right - e.clientX) / rect.width) * 100
  rightWidthPct.value = Math.min(45, Math.max(15, Math.round(pct)))
}

function onMouseup() {
  isDragging.value = false
}

// ── AI 参考台账抽屉 ───────────────────────────────────────
const ledgerVisible = ref(false)
const ledgerTasks = ref([])
const ledgerLoading = ref(false)

async function openLedger() {
  ledgerVisible.value = true
  if (ledgerTasks.value.length) return
  ledgerLoading.value = true
  try {
    const res = await apiFetch(`/api/tasks?patient_id=${patientId}`)
    ledgerTasks.value = await res.json()
  } catch {
    message.error('加载历史记录失败')
  } finally {
    ledgerLoading.value = false
  }
}

// ── 临床数据 ──────────────────────────────────────────────
const loading = ref(false)
const patient = ref(null)
const his = ref([])
const lis = ref([])
const pathology = ref([])
const pacs = ref([])
const activeTab = ref('his')

async function fetchClinical() {
  loading.value = true
  try {
    const res = await apiFetch(`/api/patients/${patientId}/clinical-view`)
    const data = await res.json()
    patient.value = data.patient || null
    his.value = data.his || []
    lis.value = data.lis || []
    pathology.value = data.lis_pathology || []
    pacs.value = data.pacs || []
  } catch {
    message.error('加载临床数据失败')
  } finally {
    loading.value = false
  }
}

// ── 任务 & AI 侧栏 ────────────────────────────────────────
const latestTask = ref(null)
const snapshot = ref(null)
const sseMode = ref(false)
const triggeringAnalysis = ref(false)
const selectedPacsRecord = ref(null)  // 当前选中的 PACS 记录
const switchingPacs = ref(false)      // 切换中加载态

const { events: sseEvents, status: sseStatus, connect, close } = useSSE()

// 每张 PACS 记录对应的热力图 URL map: record_id -> url
const pacsHeatmapMap = ref({})

async function fetchAllHeatmaps() {
  if (!pacs.value.length) return
  const results = await Promise.all(
    pacs.value.map(async (r) => {
      try {
        const res = await apiFetch(`/api/tasks?pacs_record_id=${r.record_id}`)
        const list = await res.json()
        const snap = list?.[0]?.result_snapshot
        if (!snap) return [r.record_id, null]
        const events = typeof snap === 'string' ? JSON.parse(snap) : snap
        const url = Array.isArray(events)
          ? events.find(e => e.type === 'image_done')?.data?.image_url || null
          : null
        return [r.record_id, url]
      } catch {
        return [r.record_id, null]
      }
    })
  )
  pacsHeatmapMap.value = Object.fromEntries(results)
}
async function selectPacs(record) {
  if (selectedPacsRecord.value?.record_id === record.record_id) return
  selectedPacsRecord.value = record
  close()
  sseMode.value = false
  sseEvents.value = []
  snapshot.value = null
  latestTask.value = null
  switchingPacs.value = true
  try {
    const res = await apiFetch(`/api/tasks?pacs_record_id=${record.record_id}`)
    const list = await res.json()
    if (list && list.length > 0) {
      latestTask.value = list[0]
      if (list[0].status === 'running' || list[0].status === 'pending') {
        startSSE(list[0].task_id)
      } else if (list[0].result_snapshot) {
        snapshot.value = typeof list[0].result_snapshot === 'string'
          ? JSON.parse(list[0].result_snapshot)
          : list[0].result_snapshot
        // 同步更新热力图 map，让该图立即显示热力图
        const url = Array.isArray(snapshot.value)
          ? snapshot.value.find(e => e.type === 'image_done')?.data?.image_url || null
          : null
        if (url) pacsHeatmapMap.value[record.record_id] = url
      }
    }
  } catch { /* 静默 */ } finally {
    switchingPacs.value = false
  }
}

async function fetchLatestTask() {
  try {
    const res = await apiFetch(`/api/tasks?patient_id=${patientId}`)
    const list = await res.json()
    if (list && list.length > 0) {
      latestTask.value = list[0]
      // 选中该任务对应的 PACS 记录
      if (list[0].pacs_record_id) {
        selectedPacsRecord.value = pacs.value.find(r => r.record_id === list[0].pacs_record_id) || pacs.value[0] || null
      } else {
        selectedPacsRecord.value = pacs.value[0] || null
      }
      if (list[0].status === 'running' || list[0].status === 'pending') {
        startSSE(list[0].task_id)
      } else if (list[0].result_snapshot) {
        snapshot.value = typeof list[0].result_snapshot === 'string'
          ? JSON.parse(list[0].result_snapshot)
          : list[0].result_snapshot
      }
    } else if (pacs.value.length > 0) {
      selectedPacsRecord.value = pacs.value[0]
      await triggerAnalysis(true)
    }
  } catch {
    // 无任务时静默
  }
}

function startSSE(taskId) {
  sseMode.value = true
  sseEvents.value = []
  connect(`/api/tasks/${taskId}/stream`)
}

async function triggerAnalysis(silent = false) {
  if (triggeringAnalysis.value) return
  const pacsRecord = pacs.value[0]
  if (!pacsRecord) {
    if (!silent) message.warning('该患者暂无 PACS 影像记录，无法触发分析')
    return
  }
  triggeringAnalysis.value = true
  try {
    const res = await apiFetch(`/api/tasks/from-pacs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patient_id: patientId, pacs_record_id: pacsRecord.record_id }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      if (!silent) message.error(err.error || '触发分析失败')
      return
    }
    const data = await res.json()
    latestTask.value = { task_id: data.task_id, status: 'running', patient_id: patientId }
    snapshot.value = null
    startSSE(data.task_id)
    if (!silent) message.success('AI 分析已启动')
  } catch {
    if (!silent) message.error('触发分析请求失败')
  } finally {
    triggeringAnalysis.value = false
  }
}

const sseResult = computed(() => sseEvents.value.find(e => e.type === 'result')?.data || null)

// 热力图 URL：优先取 SSE live，其次取快照
const heatmapUrl = computed(() => {
  const fromSSE = sseEvents.value.find(e => e.type === 'image_done')?.data?.image_url
  if (fromSSE) return fromSSE
  if (snapshot.value && Array.isArray(snapshot.value)) {
    return snapshot.value.find(e => e.type === 'image_done')?.data?.image_url || null
  }
  return null
})

const displayResult = computed(() => {
  // sseMode 期间优先读 SSE result（无论连接是否已关闭）
  if (sseMode.value) return sseResult.value
  if (snapshot.value) {
    const r = Array.isArray(snapshot.value)
      ? snapshot.value.find(e => e.type === 'result')?.data
      : snapshot.value
    return r || null
  }
  return null
})

const incompleteWarning = computed(() => displayResult.value?.status === 'incomplete')
const forceCloseEvent  = computed(() => sseEvents.value.find(e => e.type === 'force_close'))

const stepCards = computed(() =>
  sseEvents.value.filter(e => ['image_done', 'clinical_done', 'pathology_done'].includes(e.type))
)

const snapshotSteps = computed(() => {
  if (!snapshot.value || !Array.isArray(snapshot.value)) return []
  return snapshot.value.filter(e => ['image_done', 'clinical_done', 'pathology_done'].includes(e.type))
})

onUnmounted(() => {
  close()
  window.removeEventListener('mousemove', onMousemove)
  window.removeEventListener('mouseup', onMouseup)
})
onBeforeRouteLeave(() => close())

onMounted(async () => {
  await fetchClinical()
  await fetchLatestTask()
  fetchAllHeatmaps()  // 并行预拉所有热力图，不阻塞
  window.addEventListener('mousemove', onMousemove)
  window.addEventListener('mouseup', onMouseup)
})

function genderLabel(g) {
  if (g === 1 || g === '1' || g === '男') return '男'
  if (g === 2 || g === '2' || g === '女') return '女'
  return '-'
}
function calcAge(birthDate) {
  if (!birthDate) return null
  const age = new Date().getFullYear() - new Date(birthDate).getFullYear()
  return age > 0 ? age : null
}
function formatDate(v) {
  if (!v) return '-'
  return String(v).slice(0, 10)
}
function stepLabel(type) {
  const map = { image_done: '视觉分析', clinical_done: '病历解析', pathology_done: '病理规则' }
  return map[type] || type
}
function stepColor(type) {
  const map = { image_done: '#3b82f6', clinical_done: '#10b981', pathology_done: '#f59e0b' }
  return map[type] || '#6366f1'
}
</script>

<template>
  <div class="cv-layout">

    <!-- 顶部面包屑 -->
    <div class="cv-topbar">
      <span class="cv-patient-name" v-if="patient">
        {{ patient.name }}
        <span class="cv-patient-meta">
          ({{ genderLabel(patient.gender) }}/{{ calcAge(patient.birth_date) ? calcAge(patient.birth_date) + '岁' : '-' }})
        </span>
        <span class="cv-patient-id">内部ID: {{ patient.id }}</span>
      </span>
      <a-skeleton-input v-else-if="loading" active size="small" style="width:160px" />
      <a-button type="link" size="small" class="back-btn" @click="router.push('/patients')">
        [返回患者列表]
      </a-button>
    </div>

    <!-- 主体：左右可拖拽分栏 -->
    <div class="cv-body" ref="bodyRef">

      <!-- 左侧：临床多 Tab -->
      <div class="cv-left" :style="{ flex: `0 0 ${100 - rightWidthPct}%` }">
        <a-tabs v-model:activeKey="activeTab" size="small" class="cv-tabs">

          <!-- 基本信息 -->
          <a-tab-pane key="info" tab="基本信息">
            <a-spin :spinning="loading">
              <div v-if="patient" class="info-grid">
                <div class="info-row"><span class="info-label">姓名</span><span>{{ patient.name || '-' }}</span></div>
                <div class="info-row"><span class="info-label">性别</span><span>{{ genderLabel(patient.gender) }}</span></div>
                <div class="info-row"><span class="info-label">年龄</span><span>{{ calcAge(patient.birth_date) ? calcAge(patient.birth_date) + ' 岁' : '-' }}</span></div>
                <div class="info-row"><span class="info-label">出生日期</span><span>{{ formatDate(patient.birth_date) }}</span></div>
                <div class="info-row"><span class="info-label">手机</span><span>{{ patient.phone || '-' }}</span></div>
                <div class="info-row"><span class="info-label">身份证</span><span>{{ patient.id_card || '-' }}</span></div>
                <div class="info-row"><span class="info-label">EMPI</span><span>{{ patient.empi_id || '未归一' }}</span></div>
                <div class="info-row"><span class="info-label">建档时间</span><span>{{ formatDate(patient.created_at) }}</span></div>
              </div>
              <a-empty v-else description="暂无基本信息" />
            </a-spin>
          </a-tab-pane>

          <!-- HIS 就诊 -->
          <a-tab-pane key="his" tab="HIS 就诊">
            <a-spin :spinning="loading">
              <div v-if="his.length" class="record-list">
                <div v-for="(r, i) in his" :key="i" class="record-card">
                  <div class="record-head">
                    <span class="record-dept">{{ r.department || '-' }}</span>
                    <span class="record-date">{{ formatDate(r.visit_date) }}</span>
                  </div>
                  <div v-if="r.chief_complaint" class="record-row"><span class="rl">主诉</span>{{ r.chief_complaint }}</div>
                  <div v-if="r.diagnosis_name" class="record-row"><span class="rl">诊断</span>{{ r.diagnosis_name }}</div>
                  <div v-if="r.visit_type" class="record-row"><span class="rl">就诊类型</span>{{ r.visit_type }}</div>
                </div>
              </div>
              <a-empty v-else description="暂无就诊记录" />
            </a-spin>
          </a-tab-pane>

          <!-- LIS 化验 -->
          <a-tab-pane key="lis" tab="LIS 化验">
            <a-spin :spinning="loading">
              <div v-if="lis.length" class="record-list">
                <div v-for="(r, i) in lis" :key="i" class="record-card">
                  <div class="record-head">
                    <span class="record-dept">{{ r.test_name || '化验' }}</span>
                    <span class="record-date">{{ formatDate(r.reported_at) }}</span>
                  </div>
                  <div v-if="r.value != null" class="record-row">
                    <span class="rl">结果</span>
                    <span :class="r.abnormal_flag ? 'val-abnormal' : ''">{{ r.value }} {{ r.unit || '' }}</span>
                    <span v-if="r.ref_range" class="ref-range">（参考 {{ r.ref_range }}）</span>
                  </div>
                </div>
              </div>
              <a-empty v-else description="暂无化验记录" />
            </a-spin>
          </a-tab-pane>

          <!-- LIS 病理 -->
          <a-tab-pane key="pathology" tab="LIS 病理">
            <a-spin :spinning="loading">
              <div v-if="pathology.length" class="record-list">
                <div v-for="(r, i) in pathology" :key="i" class="record-card">
                  <div class="record-head">
                    <span class="record-dept">病理报告 {{ r.report_no ? '#' + r.report_no : '' }}</span>
                    <span class="record-date">{{ formatDate(r.reported_at) }}</span>
                  </div>
                  <div v-if="r.diagnosis_text" class="record-row"><span class="rl">诊断</span>{{ r.diagnosis_text }}</div>
                  <div v-if="r.histological_type" class="record-row"><span class="rl">组织类型</span>{{ r.histological_type }}</div>
                  <div v-if="r.breslow_thickness_mm != null" class="record-row"><span class="rl">Breslow</span>{{ r.breslow_thickness_mm }} mm</div>
                  <div v-if="r.ulceration != null" class="record-row"><span class="rl">溃疡</span>{{ r.ulceration ? '有' : '无' }}</div>
                  <div v-if="r.braf_mutation" class="record-row"><span class="rl">BRAF</span>{{ r.braf_mutation }}</div>
                  <div v-if="r.t_stage" class="record-row"><span class="rl">T分期</span>{{ r.t_stage }}</div>
                </div>
              </div>
              <a-empty v-else description="暂无病理报告" />
            </a-spin>
          </a-tab-pane>

          <!-- PACS 影像 -->
          <a-tab-pane key="pacs" tab="PACS 影像">
            <a-spin :spinning="loading">
              <div v-if="pacs.length" class="pacs-list">
                <div
                  v-for="(r, i) in pacs"
                  :key="i"
                  class="pacs-item"
                  :class="{ 'pacs-item-selected': selectedPacsRecord?.record_id === r.record_id }"
                  @click="selectPacs(r)"
                >
                  <a-spin :spinning="switchingPacs && selectedPacsRecord?.record_id === r.record_id" size="small">
                    <ImageCompare
                      :leftUrl="r.image_url"
                      :rightUrl="selectedPacsRecord?.record_id === r.record_id
                        ? (heatmapUrl || pacsHeatmapMap[r.record_id])
                        : pacsHeatmapMap[r.record_id]"
                      leftLabel="原图"
                      rightLabel="热力图"
                    />
                  </a-spin>
                  <div class="pacs-item-meta">
                    <span class="pacs-modality">{{ r.modality || '-' }}</span>
                    <span v-if="r.body_part" class="pacs-body">{{ r.body_part }}</span>
                    <span class="pacs-date">{{ formatDate(r.recorded_at || r.created_at) }}</span>
                    <span v-if="r.description" class="pacs-desc">{{ r.description }}</span>
                    <a-tag v-if="selectedPacsRecord?.record_id === r.record_id" color="blue" style="margin:0;font-size:10px">当前分析</a-tag>
                  </div>
                </div>
              </div>
              <a-empty v-else description="暂无影像记录" />
            </a-spin>
          </a-tab-pane>

        </a-tabs>
      </div>

      <!-- 拖拽分割线 -->
      <div class="cv-divider" @mousedown="onDividerMousedown">
        <div class="cv-divider-handle">⋮</div>
      </div>

      <!-- 右侧：AI 侧栏（宽度可拖拽）-->
      <div class="cv-right" :style="{ flex: `0 0 ${rightWidthPct}%` }">
        <div class="ai-panel">
          <div class="ai-panel-head">
            <span class="ai-panel-title">AI 辅助诊断</span>
            <div class="ai-mode-badge" :class="sseMode && sseStatus !== 'closed' && sseStatus !== 'error' ? 'badge-live' : 'badge-snap'">
              {{ sseMode && sseStatus !== 'closed' && sseStatus !== 'error' ? 'LIVE' : '快照' }}
            </div>
          </div>

          <!-- incomplete 警告 -->
          <div v-if="incompleteWarning" class="incomplete-banner">
            ⚠️ 部分数据缺失，本建议为降级结果
          </div>

          <!-- 管理员强制释放提示 -->
          <div v-if="forceCloseEvent" class="incomplete-banner" style="background:#fff7ed;color:#c2410c;border-color:#fed7aa;">
            ⚠️ 会话已被管理员强制释放
          </div>

          <!-- SSE live 模式：动态追加 step 卡片 -->
          <template v-if="sseMode">
            <div v-if="sseStatus === 'connecting' || (sseStatus === 'open' && stepCards.length === 0)" class="ai-connecting">
              <a-spin size="small" /> {{ sseStatus === 'connecting' ? '正在连接 AI 推理流...' : '等待推理结果...' }}
            </div>
            <div v-for="card in stepCards" :key="card.type" class="step-card" :style="{ borderLeftColor: stepColor(card.type) }">
              <div class="step-card-head">
                <span class="step-dot" :style="{ background: stepColor(card.type) }"></span>
                {{ stepLabel(card.type) }}
              </div>
              <div class="step-card-body">
                <template v-if="card.type === 'image_done'">
                  <div v-if="card.data?.image_url" class="step-img-wrap">
                    <img :src="card.data.image_url" class="step-heatmap" alt="热力图" />
                  </div>
                  <div v-if="card.data?.location" class="step-row"><span class="sl">部位</span>{{ card.data.location }}</div>
                  <div v-if="card.data?.coverage != null" class="step-row"><span class="sl">覆盖率</span>{{ (card.data.coverage * 100).toFixed(1) }}%</div>
                  <div v-if="card.data?.morphology?.shape" class="step-row"><span class="sl">形态</span>{{ card.data.morphology.shape }}</div>
                  <div v-if="card.data?.morphology?.color_distribution" class="step-row"><span class="sl">色泽</span>{{ card.data.morphology.color_distribution }}</div>
                </template>
                <template v-else-if="card.type === 'clinical_done'">
                  <div v-if="card.data?.lesion_clinical?.region" class="step-row"><span class="sl">病灶部位</span>{{ card.data.lesion_clinical.region }}</div>
                  <div v-if="card.data?.lesion_symptoms" class="step-row">
                    <span class="sl">症状</span>
                    {{ Object.entries(card.data.lesion_symptoms).filter(([,v]) => v).map(([k]) => k).join('、') || '无' }}
                  </div>
                  <div v-if="card.data?.patient_info?.age" class="step-row"><span class="sl">患者年龄</span>{{ card.data.patient_info.age }}</div>
                </template>
                <template v-else-if="card.type === 'pathology_done'">
                  <div v-if="card.data?.disease_type" class="step-row"><span class="sl">病种</span>{{ card.data.disease_type }}</div>
                  <div v-if="card.data?.t_stage" class="step-row"><span class="sl">T分期</span>{{ card.data.t_stage }}</div>
                  <div v-if="card.data?.treatment_recommendations?.length" class="step-row">
                    <span class="sl">建议</span>{{ card.data.treatment_recommendations[0] }}
                  </div>
                  <div v-if="card.data?.missing_data_warnings?.length" class="step-row warn-text">
                    缺失：{{ card.data.missing_data_warnings.join('、') }}
                  </div>
                </template>
              </div>
            </div>
          </template>

          <!-- 快照模式：展示历史 step 卡片 -->
          <template v-else-if="snapshotSteps.length">
            <div v-for="card in snapshotSteps" :key="card.type" class="step-card" :style="{ borderLeftColor: stepColor(card.type) }">
              <div class="step-card-head">
                <span class="step-dot" :style="{ background: stepColor(card.type) }"></span>
                {{ stepLabel(card.type) }}
              </div>
              <div class="step-card-body">
                <template v-if="card.type === 'image_done'">
                  <div v-if="card.data?.image_url" class="step-img-wrap">
                    <img :src="card.data.image_url" class="step-heatmap" alt="热力图" />
                  </div>
                  <div v-if="card.data?.location" class="step-row"><span class="sl">部位</span>{{ card.data.location }}</div>
                  <div v-if="card.data?.coverage != null" class="step-row"><span class="sl">覆盖率</span>{{ (card.data.coverage * 100).toFixed(1) }}%</div>
                  <div v-if="card.data?.morphology?.shape" class="step-row"><span class="sl">形态</span>{{ card.data.morphology.shape }}</div>
                  <div v-if="card.data?.morphology?.color_distribution" class="step-row"><span class="sl">色泽</span>{{ card.data.morphology.color_distribution }}</div>
                </template>
                <template v-else-if="card.type === 'clinical_done'">
                  <div v-if="card.data?.lesion_clinical?.region" class="step-row"><span class="sl">病灶部位</span>{{ card.data.lesion_clinical.region }}</div>
                  <div v-if="card.data?.lesion_symptoms" class="step-row">
                    <span class="sl">症状</span>
                    {{ Object.entries(card.data.lesion_symptoms).filter(([,v]) => v).map(([k]) => k).join('、') || '无' }}
                  </div>
                  <div v-if="card.data?.patient_info?.age" class="step-row"><span class="sl">患者年龄</span>{{ card.data.patient_info.age }}</div>
                </template>
                <template v-else-if="card.type === 'pathology_done'">
                  <div v-if="card.data?.disease_type" class="step-row"><span class="sl">病种</span>{{ card.data.disease_type }}</div>
                  <div v-if="card.data?.t_stage" class="step-row"><span class="sl">T分期</span>{{ card.data.t_stage }}</div>
                  <div v-if="card.data?.treatment_recommendations?.length" class="step-row">
                    <span class="sl">建议</span>{{ card.data.treatment_recommendations[0] }}
                  </div>
                  <div v-if="card.data?.missing_data_warnings?.length" class="step-row warn-text">
                    缺失：{{ card.data.missing_data_warnings.join('、') }}
                  </div>
                </template>
              </div>
            </div>
          </template>

          <!-- 综合研判区 -->
          <div v-if="displayResult" class="result-section">
            <div class="result-head">综合研判</div>
            <div class="result-risk" :class="'risk-' + (displayResult.risk_level === '高危' ? 'high' : displayResult.risk_level === '中危' ? 'mid' : 'low')">
              风险等级：{{ displayResult.risk_level || '-' }}
            </div>
            <div v-if="displayResult.key_concerns?.length" class="result-block">
              <div class="result-block-title">核心关注</div>
              <ul class="result-list">
                <li v-for="(c, i) in displayResult.key_concerns" :key="i">
                  {{ c.item }} <span class="source-id">{{ c.source_id }}</span>
                </li>
              </ul>
            </div>
            <div v-if="displayResult.recommendations?.length" class="result-block">
              <div class="result-block-title">处置建议</div>
              <ul class="result-list">
                <li v-for="(r, i) in displayResult.recommendations" :key="i">
                  {{ r.item }} <span class="source-id">{{ r.source_id }}</span>
                </li>
              </ul>
            </div>
            <div v-if="displayResult.differential?.length" class="result-block">
              <div class="result-block-title">鉴别诊断</div>
              <div class="differential-tags">
                <a-tag v-for="(d, i) in displayResult.differential" :key="i" color="volcano" class="diff-tag">{{ d }}</a-tag>
              </div>
            </div>
            <div v-if="displayResult.disclaimer" class="disclaimer">{{ displayResult.disclaimer }}</div>
            <div v-if="latestTask?.task_id" class="view-detail-link">
              <a-button type="link" size="small" @click="router.push('/tasks/' + latestTask.task_id)">
                查看详情 →
              </a-button>
            </div>
          </div>

          <!-- 无任务状态：非 sseMode 且无快照 -->
          <div v-if="!sseMode && !displayResult" class="ai-empty">
            <div class="ai-empty-icon">🤖</div>
            <div class="ai-empty-text">暂无 AI 分析结果</div>
            <div class="ai-empty-sub">可点击下方按钮触发分析</div>
          </div>

          <div class="ai-panel-foot">
            <a-button
              type="primary"
              block
              :loading="triggeringAnalysis || (sseMode && sseStatus === 'open')"
              :disabled="sseMode && (sseStatus === 'connecting' || sseStatus === 'open')"
              @click="triggerAnalysis"
              class="trigger-btn"
            >
              {{ sseMode && (sseStatus === 'connecting' || sseStatus === 'open') ? '分析中...' : '重新生成分析' }}
            </a-button>
            <a-button block class="ledger-btn" @click="openLedger">
              AI 参考台账
            </a-button>
          </div>
        </div>
      </div>

    </div>

    <!-- AI 参考台账抽屉 -->
    <a-drawer
      v-model:open="ledgerVisible"
      title="AI 参考台账"
      placement="bottom"
      height="50%"
      :body-style="{ padding: '16px 24px', overflowY: 'auto' }"
    >
      <a-spin :spinning="ledgerLoading">
        <div v-if="ledgerTasks.length" class="ledger-list">
          <div v-for="t in ledgerTasks" :key="t.task_id" class="ledger-row">
            <div class="ledger-meta">
              <span class="ledger-date">{{ formatDate(t.created_at) }}</span>
              <a-tag :color="t.status === 'complete' ? 'green' : t.status === 'error' ? 'red' : 'default'" class="ledger-status">
                {{ t.status }}
              </a-tag>
              <span class="ledger-id">{{ t.task_id.slice(0, 8) }}...</span>
            </div>
            <a-button size="small" type="link" @click="() => { router.push('/tasks/' + t.task_id); ledgerVisible = false }">
              查看详情 →
            </a-button>
          </div>
        </div>
        <a-empty v-else description="该患者暂无历史分析记录" />
      </a-spin>
    </a-drawer>

  </div>
</template>

<style scoped>
.cv-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background:
      radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
      radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
      linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}

.cv-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 24px 8px;
  background: rgba(255, 255, 255, 0.82);
  border-bottom: 1px solid rgba(109, 145, 186, 0.12);
  backdrop-filter: blur(14px);
  box-shadow: 0 8px 20px rgba(95, 130, 171, 0.06);
  flex-shrink: 0;
}

.back-btn {
  padding: 0;
  font-size: 13px;
  color: #5f7894;
  margin-left: auto;
}

.cv-patient-name {
  font-size: 16px;
  font-weight: 700;
  color: #16324f;
}

.cv-patient-meta {
  font-size: 13px;
  font-weight: 400;
  color: #6c829c;
  margin-left: 4px;
}

.cv-patient-id {
  font-size: 12px;
  color: #8aa0b8;
  margin-left: 10px;
  font-family: monospace;
}

.cv-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.cv-left {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 16px 16px 16px 24px;
  min-width: 0;
}

.cv-tabs {
  background: rgba(255, 255, 255, 0.78);
  border-radius: 18px;
  padding: 16px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
}

:deep(.ant-tabs-nav) {
  margin-bottom: 14px;
}

:deep(.ant-tabs-tab) {
  border-radius: 12px;
  transition: color 0.18s ease, opacity 0.18s ease !important;
}


:deep(.ant-tabs-tab .ant-tabs-tab-btn) {
  color: #5f7894;
  font-weight: 600;
}

:deep(.ant-tabs-tab:hover .ant-tabs-tab-btn) {
  color: #2f6fed;
}

:deep(.ant-tabs-tab-active .ant-tabs-tab-btn) {
  color: #2f6fed !important;
  font-weight: 700;
}

:deep(.ant-tabs-ink-bar) {
  background: linear-gradient(90deg, #2f6fed 0%, #19c6d0 100%) !important;
  height: 3px !important;
  border-radius: 999px;
  transition: none !important;
}



.info-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.info-row {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: #35506f;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(248, 251, 255, 0.72);
  border: 1px solid rgba(116, 152, 193, 0.1);
}

.info-label {
  width: 72px;
  color: #8aa0b8;
  flex-shrink: 0;
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.record-card {
  background: rgba(248, 251, 255, 0.78);
  border-radius: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(116, 152, 193, 0.12);
  box-shadow: 0 8px 20px rgba(95, 130, 171, 0.05);
  transition: all 0.2s ease;
}

.record-card:hover {
  background: rgba(255,255,255,0.92);
  border-color: rgba(47,111,237,0.18);
  box-shadow: 0 14px 28px rgba(95,130,171,0.08);
}

.record-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.record-dept {
  font-size: 13px;
  font-weight: 600;
  color: #18395e;
}

.record-date {
  font-size: 11px;
  color: #8aa0b8;
}

.record-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #35506f;
  margin-top: 4px;
  line-height: 1.5;
}

.rl {
  color: #8aa0b8;
  width: 36px;
  flex-shrink: 0;
}

.val-abnormal {
  color: #dc2626;
  font-weight: 600;
}

.ref-range {
  color: #94a3b8;
  font-size: 11px;
}

.pacs-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pacs-item {
  cursor: pointer;
  border-radius: 14px;
  border: 1.5px solid rgba(116, 152, 193, 0.12);
  background: rgba(248, 251, 255, 0.68);
  padding: 8px;
  transition: all 0.18s ease;
}

.pacs-item:hover {
  border-color: rgba(25, 198, 208, 0.34);
  box-shadow: 0 12px 24px rgba(95, 130, 171, 0.08);
}

.pacs-item-selected {
  border-color: #2f6fed !important;
  box-shadow: 0 0 0 4px rgba(47, 111, 237, 0.08);
  background: rgba(255,255,255,0.9);
}

.pacs-item-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 6px;
  flex-wrap: wrap;
  padding: 0 2px;
}

.pacs-modality {
  font-size: 12px;
  font-weight: 600;
  color: #18395e;
}

.pacs-body {
  font-size: 12px;
  color: #5f7894;
}

.pacs-date {
  font-size: 11px;
  color: #8aa0b8;
}

.pacs-desc {
  font-size: 11px;
  color: #5f7894;
}

.cv-right {
  flex-shrink: 0;
  overflow-y: auto;
  padding: 16px 24px 16px 8px;
  min-width: 0;
}

.ai-panel {
  background: rgba(255, 255, 255, 0.8);
  border-radius: 18px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 120px);
  padding-bottom: 16px;
}

.ai-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid rgba(116, 152, 193, 0.1);
}

.ai-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #18395e;
}

.ai-mode-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 999px;
  letter-spacing: 0.5px;
}

.badge-live {
  background: rgba(25,198,208,0.1);
  color: #0f766e;
}

.badge-snap {
  background: rgba(47,111,237,0.08);
  color: #2f6fed;
}

.incomplete-banner {
  margin: 10px 14px 0;
  background: rgba(255, 248, 225, 0.86);
  border: 1px solid rgba(239, 180, 54, 0.22);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 12px;
  color: #8a6326;
}

.step-card {
  margin: 10px 14px 0;
  background: rgba(248, 251, 255, 0.78);
  border-radius: 14px;
  border-left: 3px solid #e2e8f0;
  border-top: 1px solid rgba(116, 152, 193, 0.08);
  border-right: 1px solid rgba(116, 152, 193, 0.08);
  border-bottom: 1px solid rgba(116, 152, 193, 0.08);
  padding: 10px 12px;
  box-shadow: 0 8px 20px rgba(95,130,171,0.05);
}

.step-card-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  color: #35506f;
  margin-bottom: 6px;
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.step-card-body {
  font-size: 12px;
  color: #5f7894;
  line-height: 1.6;
}

.step-row {
  display: flex;
  gap: 6px;
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.5;
}

.sl {
  color: #8aa0b8;
  width: 52px;
  flex-shrink: 0;
}

.step-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.warn-text {
  color: #c97a12;
}

.step-img-wrap {
  margin-bottom: 6px;
}

.step-heatmap {
  width: 100%;
  border-radius: 10px;
  border: 1px solid rgba(116, 152, 193, 0.12);
}

.result-section {
  margin: 12px 14px 0;
  padding: 12px;
  border-radius: 14px;
  background: rgba(248, 251, 255, 0.78);
  border: 1px solid rgba(116, 152, 193, 0.1);
}

.result-head {
  font-size: 13px;
  font-weight: 700;
  color: #18395e;
  margin-bottom: 8px;
}

.result-risk {
  font-size: 13px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 10px;
  display: inline-block;
  margin-bottom: 10px;
}

.risk-high {
  background: rgba(239, 68, 68, 0.08);
  color: #dc2626;
}

.risk-mid {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
}

.risk-low {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
}

.result-block {
  margin-bottom: 10px;
}

.result-block-title {
  font-size: 11px;
  font-weight: 600;
  color: #8aa0b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 5px;
}

.result-list {
  padding-left: 16px;
  margin: 0;
  font-size: 12px;
  color: #35506f;
  line-height: 1.7;
}

.source-id {
  font-size: 10px;
  color: #8aa0b8;
  margin-left: 4px;
}

.differential-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.diff-tag {
  margin: 0;
  font-size: 11px;
  border-radius: 999px;
}

.disclaimer {
  font-size: 11px;
  color: #8aa0b8;
  margin-top: 8px;
  line-height: 1.6;
  border-top: 1px solid rgba(116, 152, 193, 0.1);
  padding-top: 8px;
}

.view-detail-link {
  text-align: right;
  margin-top: 4px;
}

.ai-empty {
  padding: 32px 16px;
  text-align: center;
}

.ai-empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.ai-empty-text {
  font-size: 14px;
  color: #5f7894;
  font-weight: 600;
}

.ai-empty-sub {
  font-size: 12px;
  color: #8aa0b8;
  margin-top: 4px;
}

.ai-panel-foot {
  padding: 16px 14px 0;
  margin-top: auto;
}

.trigger-btn {
  border-radius: 12px !important;
  border: none !important;
  background: #2f9fe2 !important;
  box-shadow: 0 14px 28px rgba(47, 159, 226, 0.18);
  font-weight: 700;
}

.trigger-btn:hover,
.trigger-btn:focus {
  background: #2f9fe2 !important;
  box-shadow: 0 16px 30px rgba(47, 159, 226, 0.22);
}


.ledger-btn {
  border-radius: 12px !important;
  margin-top: 8px;
  color: #5f7894 !important;
  border: 1px solid rgba(92,128,170,0.18) !important;
  background: rgba(255,255,255,0.78) !important;
  box-shadow: 0 8px 20px rgba(100,130,168,0.08);
}

.ai-connecting {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  font-size: 12px;
  color: #5f7894;
}

.cv-divider {
  width: 6px;
  flex-shrink: 0;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  transition: background 0.15s;
  z-index: 10;
}

.cv-divider:hover {
  background: rgba(47,111,237,0.08);
}

.cv-divider-handle {
  font-size: 14px;
  color: #cbd5e1;
  letter-spacing: -2px;
  user-select: none;
}

.ledger-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ledger-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(248, 251, 255, 0.78);
  border-radius: 12px;
  border: 1px solid rgba(116, 152, 193, 0.1);
}

.ledger-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.ledger-date {
  font-size: 12px;
  color: #5f7894;
}

.ledger-status {
  margin: 0;
  font-size: 11px;
}

.ledger-id {
  font-size: 11px;
  color: #8aa0b8;
  font-family: monospace;
}

:deep(.ant-btn-link) {
  color: #2f6fed;
}

:deep(.ant-btn-link:hover) {
  color: #19c6d0;
}

:deep(.ant-empty-description) {
  color: #8aa0b8;
}

:deep(.ant-spin-dot-item) {
  background-color: #2f6fed;
}

:deep(.ant-tag) {
  border-radius: 999px;
}
</style>
