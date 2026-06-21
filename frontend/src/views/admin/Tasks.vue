<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const route  = useRoute()

const tasks       = ref([])
const loading     = ref(false)
const currentPage = ref(1)
const PAGE_SIZE   = 15

// ── 筛选状态 ─────────────────────────────────────────────────
const keyword      = ref('')
const filterStatus = ref('')
const filterRisk   = ref('')
const dateRange    = ref([])
const selectedKeys = ref([])
const patientIdFilter = ref(null)  // 来自 PatientList.vue 的精确 patient_id 筛选

// 从 query 参数自动初始化筛选（首页 / 患者管理页跳转带参）
function initFromQuery() {
  if (route.query.status)     filterStatus.value   = route.query.status
  if (route.query.risk)       filterRisk.value     = route.query.risk
  if (route.query.keyword)    keyword.value        = route.query.keyword
  if (route.query.patient)    keyword.value        = route.query.patient
  if (route.query.patient_id) patientIdFilter.value = String(route.query.patient_id)
}

// ── 轮询 ─────────────────────────────────────────────────────
const hasPending = computed(() =>
  tasks.value.some(t => ['pending', 'processing', 'analyzing'].includes(t.status))
)
let pollTimer = null

async function fetchTasks() {
  loading.value = true
  try {
    const res = await apiFetch('/api/tasks')
    if (res.ok) tasks.value = await res.json()
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

async function silentRefresh() {
  try {
    const res = await apiFetch('/api/tasks')
    if (res.ok) tasks.value = await res.json()
  } catch {}
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await silentRefresh()
    if (!hasPending.value) stopPolling()
  }, 5000)
}

// ── 风险等级解析（与首页逻辑一致） ───────────────────────────
function riskLevel(task) {
  try {
    const evts = typeof task.result_snapshot === 'string'
      ? JSON.parse(task.result_snapshot)
      : task.result_snapshot
    return evts?.find(e => e.type === 'result')?.data?.risk_level || ''
  } catch { return '' }
}

function riskLabel(task) {
  const lv = riskLevel(task)
  if (!lv) return '无分析'
  return lv
}

function riskTagColor(task) {
  const lv = riskLevel(task)
  if (!lv) return 'default'
  if (lv.includes('极高') || lv.toLowerCase().includes('very_high')) return 'error'
  if (lv.includes('高') || lv.toLowerCase().includes('high')) return 'error'
  if (lv.includes('中') || lv.toLowerCase().includes('med')) return 'warning'
  if (lv.includes('低') || lv.toLowerCase().includes('low')) return 'success'
  return 'default'
}

function isHighRisk(task) {
  const lv = riskLevel(task)
  return lv.includes('高') || lv.toLowerCase().includes('high')
}

// ── 状态映射 ──────────────────────────────────────────────────
function statusLabel(s) {
  if (s === 'complete')  return '完成'
  if (s === 'error' || s === 'failed') return '失败'
  if (s === 'pending')   return '等待中'
  return '分析中'
}

function statusTagColor(s) {
  if (s === 'complete') return 'success'
  if (s === 'error' || s === 'failed') return 'error'
  if (s === 'pending') return 'default'
  return 'processing'
}

// ── 触发类型推断 ──────────────────────────────────────────────
function triggerType(task) {
  return task.pacs_record_id ? 'PACS' : '手动'
}

// ── 数据来源图标推断 ──────────────────────────────────────────
function dataTags(task) {
  const tags = []
  if (task.pacs_record_id) tags.push({ label: '影像', color: '#6366f1' })
  if (task.chief_complaint) tags.push({ label: '病历', color: '#0ea5e9' })
  try {
    const evts = typeof task.result_snapshot === 'string'
      ? JSON.parse(task.result_snapshot)
      : task.result_snapshot
    if (Array.isArray(evts) && evts.some(e => e.type === 'pathology_done')) {
      tags.push({ label: '病理', color: '#10b981' })
    }
  } catch {}
  return tags
}

// ── 筛选逻辑 ──────────────────────────────────────────────────
const filteredTasks = computed(() => {
  let list = tasks.value

  if (patientIdFilter.value) {
    list = list.filter(t => String(t.patient_id) === patientIdFilter.value)
  }

  const q = keyword.value.trim().toLowerCase()
  if (q) {
    list = list.filter(t =>
      (t.patient_name || '').toLowerCase().includes(q) ||
      String(t.patient_id || '').includes(q) ||
      (t.task_id || '').toLowerCase().includes(q)
    )
  }
  if (filterStatus.value) {
    if (filterStatus.value === 'failed') {
      list = list.filter(t => t.status === 'error' || t.status === 'failed')
    } else if (filterStatus.value === 'processing') {
      list = list.filter(t => ['pending', 'processing', 'analyzing'].includes(t.status))
    } else {
      list = list.filter(t => t.status === filterStatus.value)
    }
  }
  if (filterRisk.value) {
    if (filterRisk.value === 'none') {
      list = list.filter(t => !riskLevel(t))
    } else if (filterRisk.value === 'high') {
      list = list.filter(t => {
        const lv = riskLevel(t)
        return lv.includes('高') || lv.toLowerCase().includes('high')
      })
    } else if (filterRisk.value === 'mid') {
      list = list.filter(t => {
        const lv = riskLevel(t)
        return lv.includes('中') || lv.toLowerCase().includes('med')
      })
    } else if (filterRisk.value === 'low') {
      list = list.filter(t => {
        const lv = riskLevel(t)
        return lv.includes('低') || lv.toLowerCase().includes('low')
      })
    } else if (filterRisk.value === 'mid_and_above') {
      list = list.filter(t => {
        const lv = riskLevel(t)
        return lv.includes('高') || lv.includes('中') ||
          lv.toLowerCase().includes('high') || lv.toLowerCase().includes('med')
      })
    }
  }
  if (dateRange.value && dateRange.value.length === 2 && dateRange.value[0]) {
    const start = new Date(dateRange.value[0]).getTime()
    const end   = new Date(dateRange.value[1]).getTime() + 86400000
    list = list.filter(t => {
      const ts = new Date(t.created_at).getTime()
      return ts >= start && ts <= end
    })
  }
  return list
})

function resetFilters() {
  keyword.value         = ''
  filterStatus.value    = ''
  filterRisk.value      = ''
  dateRange.value       = []
  selectedKeys.value    = []
  patientIdFilter.value = null
  currentPage.value     = 1
}

// ── 当前页数据 ────────────────────────────────────────────────
const currentPageTasks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return filteredTasks.value.slice(start, start + PAGE_SIZE)
})

const pageAllSelected = computed(() =>
  currentPageTasks.value.length > 0 &&
  currentPageTasks.value.every(t => selectedKeys.value.includes(t.task_id))
)

const pageIndeterminate = computed(() =>
  !pageAllSelected.value &&
  currentPageTasks.value.some(t => selectedKeys.value.includes(t.task_id))
)

function toggleRowSelect(e, taskId) {
  if (e.target.checked) {
    if (!selectedKeys.value.includes(taskId)) selectedKeys.value.push(taskId)
  } else {
    const i = selectedKeys.value.indexOf(taskId)
    if (i !== -1) selectedKeys.value.splice(i, 1)
  }
}

function togglePageSelect(e) {
  const ids = currentPageTasks.value.map(t => t.task_id)
  if (e.target.checked) {
    ids.forEach(id => { if (!selectedKeys.value.includes(id)) selectedKeys.value.push(id) })
  } else {
    selectedKeys.value = selectedKeys.value.filter(id => !ids.includes(id))
  }
}

function exportSelected() {
  const selected = tasks.value.filter(t => selectedKeys.value.includes(t.task_id))
  const rows = selected.map(t => {
    let snapshot = t.result_snapshot
    try {
      if (typeof snapshot === 'string') snapshot = JSON.parse(snapshot)
    } catch {}
    return {
      task_id:        t.task_id,
      patient_name:   t.patient_name || null,
      patient_id:     t.patient_id   || null,
      created_at:     t.created_at   || null,
      status:         t.status,
      risk_level:     riskLevel(t) || null,
      result_snapshot: snapshot ?? null,
    }
  })
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `derma_tasks_export_${new Date().toISOString().slice(0,10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 跳转 ──────────────────────────────────────────────────────
function goPatient(task) {
  if (task.patient_id) {
    router.push('/clinical/' + task.patient_id)
  } else {
    router.push('/patients')
  }
}

// ── 行样式 ────────────────────────────────────────────────────
function rowClass(record) {
  const s = record.status
  if (s === 'error' || s === 'failed') return 'row-failed'
  if (isHighRisk(record)) return 'row-highrisk'
  return ''
}

const columns = [
  { title: '',            key: 'select',     width: 40,  fixed: 'left' },
  { title: 'Task ID',    key: 'task_id',    width: 180 },
  { title: '患者姓名',   key: 'patient',    width: 110 },
  { title: '患者 ID',    key: 'patient_id', width: 80  },
  { title: '任务创建时间', key: 'created_at', width: 155 },
  { title: '任务状态',   key: 'status',     width: 90  },
  { title: '触发类型',   key: 'trigger',    width: 90  },
  { title: 'AI 风险等级', key: 'risk',      width: 110 },
  { title: '涉及数据',   key: 'data_tags',  width: 130 },
  { title: '操作',       key: 'action',     width: 140, align: 'center' },
]

// ── query 参数变化时重新筛选（如首页切换跳转） ────────────────
watch(() => route.query, initFromQuery, { immediate: false })

watch([keyword, filterStatus, filterRisk, dateRange, patientIdFilter], () => {
  currentPage.value = 1
})

onMounted(async () => {
  initFromQuery()
  await fetchTasks()
  if (hasPending.value) startPolling()
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="page">

    <!-- 页面标题 -->
    <div class="page-header">
      <div class="section-title">AI 诊断记录</div>
      <div class="page-sub">全平台 AI 任务统一归档 · 回溯历史分析 · 跟踪风险病例</div>
    </div>

    <!-- 区块 1：筛选操作栏 -->
    <div class="filter-bar">
      <div class="filter-left">
        <a-input
          v-model:value="keyword"
          placeholder="患者姓名 / 患者 ID / 任务 ID"
          allow-clear
          class="filter-input"
        />
        <a-select
          v-model:value="filterStatus"
          placeholder="任务状态"
          allow-clear
          class="filter-select"
        >
          <a-select-option value="processing">分析中</a-select-option>
          <a-select-option value="complete">已完成</a-select-option>
          <a-select-option value="failed">推理失败</a-select-option>
          <a-select-option value="pending">等待中</a-select-option>
        </a-select>
        <a-select
          v-model:value="filterRisk"
          placeholder="AI 风险等级"
          allow-clear
          class="filter-select"
        >
          <a-select-option value="none">无分析</a-select-option>
          <a-select-option value="low">低危</a-select-option>
          <a-select-option value="mid">中危</a-select-option>
          <a-select-option value="high">高危 / 极高危</a-select-option>
          <a-select-option value="mid_and_above">中危及以上</a-select-option>
        </a-select>
        <a-range-picker
          v-model:value="dateRange"
          :placeholder="['开始日期', '结束日期']"
          size="middle"
          class="filter-datepicker"
        />
        <a-tooltip title="病种筛选：当前任务数据中暂无病种字段，待后端支持后启用">
          <a-select placeholder="病种筛选" disabled class="filter-select filter-disabled" />
        </a-tooltip>
      </div>
      <div class="filter-right">
        <a-button @click="resetFilters">重置筛选</a-button>
        <a-button :loading="loading" @click="fetchTasks">刷新列表</a-button>
        <a-button
          :disabled="selectedKeys.length === 0"
          @click="exportSelected"
        >批量导出选中报告{{ selectedKeys.length ? `（${selectedKeys.length}）` : '' }}</a-button>
      </div>
    </div>

    <!-- 区块 2：任务表格 -->
    <div class="table-card">
      <div class="table-meta">
        <span class="meta-count">
          共 {{ filteredTasks.length }} 条记录
          <span v-if="selectedKeys.length" class="meta-selected">
            （已选 {{ selectedKeys.length }} 条）
          </span>
        </span>
        <span v-if="hasPending" class="meta-polling">
          <span class="pulse-dot"></span>有进行中任务，自动刷新中
        </span>
      </div>

      <a-table
        :columns="columns"
        :data-source="filteredTasks"
        :loading="loading"
        row-key="task_id"
        :pagination="{
          pageSize: PAGE_SIZE,
          current: currentPage,
          showSizeChanger: false,
          showTotal: total => `共 ${total} 条`,
          onChange: p => { currentPage.value = p }
        }"
        size="small"
        :row-class-name="rowClass"
        class="tasks-table"
      >
        <template #headerCell="{ column }">
          <template v-if="column.key === 'select'">
            <a-checkbox
              :checked="pageAllSelected"
              :indeterminate="pageIndeterminate"
              @change="togglePageSelect"
            />
          </template>
        </template>

        <template #bodyCell="{ column, record }">

          <!-- 多选 -->
          <template v-if="column.key === 'select'">
            <a-checkbox
              :checked="selectedKeys.includes(record.task_id)"
              @change="e => toggleRowSelect(e, record.task_id)"
            />
          </template>

          <!-- Task ID -->
          <template v-else-if="column.key === 'task_id'">
            <span class="id-text">{{ record.task_id }}</span>
          </template>

          <!-- 患者姓名 -->
          <template v-else-if="column.key === 'patient'">
            <div class="patient-cell">
              <span class="patient-name">{{ record.patient_name || '—' }}</span>
              <span v-if="isHighRisk(record)" class="risk-badge">高危</span>
            </div>
          </template>

          <!-- 患者 ID（暂无 EMPI，显示内部 patient_id） -->
          <template v-else-if="column.key === 'patient_id'">
            <span class="id-text">{{ record.patient_id || '—' }}</span>
          </template>

          <!-- 创建时间 -->
          <template v-else-if="column.key === 'created_at'">
            <span class="time-text">
              {{ record.created_at ? String(record.created_at).replace('T', ' ').slice(0, 16) : '—' }}
            </span>
          </template>

          <!-- 任务状态 -->
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusTagColor(record.status)" style="margin:0">
              {{ statusLabel(record.status) }}
            </a-tag>
          </template>

          <!-- 触发类型 -->
          <template v-else-if="column.key === 'trigger'">
            <span class="trigger-tag" :class="{ 'trigger-pacs': record.pacs_record_id }">
              {{ triggerType(record) }}
            </span>
          </template>

          <!-- AI 风险等级 -->
          <template v-else-if="column.key === 'risk'">
            <a-tag v-if="riskLabel(record) !== '无分析'"
              :color="riskTagColor(record)"
              style="margin:0">
              {{ riskLabel(record) }}
            </a-tag>
            <span v-else class="no-analysis">—</span>
          </template>

          <!-- 涉及数据 -->
          <template v-else-if="column.key === 'data_tags'">
            <div class="data-tags">
              <span
                v-for="tag in dataTags(record)"
                :key="tag.label"
                class="data-tag"
                :style="{ borderColor: tag.color, color: tag.color }"
              >{{ tag.label }}</span>
              <span v-if="dataTags(record).length === 0" class="no-analysis">—</span>
            </div>
          </template>

          <!-- 操作 -->
          <template v-else-if="column.key === 'action'">
            <div class="action-btns">
              <a-button
                type="link"
                size="small"
                class="action-link"
                @click="router.push('/tasks/' + record.task_id)"
              >查阅快照</a-button>
            </div>
          </template>

        </template>
      </a-table>
    </div>

  </div>
</template>

<style scoped>
.page {
  padding: 24px 28px 20px;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
  background:
      radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
      radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
      linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}

.page-header {
  flex-shrink: 0;
}

.section-title {
  font-size: 20px;
  font-weight: 800;
  color: #16324f;
  border-left: 3px solid #19c6d0;
  padding-left: 12px;
}

.page-sub {
  font-size: 12px;
  color: #8aa0b8;
  margin-top: 5px;
  padding-left: 15px;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 18px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
  padding: 12px 16px;
  flex-wrap: wrap;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.filter-input {
  width: 210px;
}

.filter-select {
  width: 130px;
}

.filter-datepicker {
  width: 220px;
}

.filter-disabled {
  opacity: 0.55;
}

/* 表格卡片 */
.table-card {
  background: rgba(255, 255, 255, 0.82);
  border-radius: 18px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
  padding: 16px 18px;
  flex: 1;
}

.table-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 10px;
}

.meta-count {
  font-size: 13px;
  color: #5f7894;
}

.meta-selected {
  color: #19c6d0;
  font-weight: 700;
}

.meta-polling {
  font-size: 12px;
  color: #8aa0b8;
  display: flex;
  align-items: center;
  gap: 5px;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #19c6d0;
  display: inline-block;
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

/* 行样式 */
:deep(.row-failed td) {
  background: rgba(255, 247, 240, 0.92) !important;
}

:deep(.row-highrisk td) {
  background: rgba(255, 245, 245, 0.92) !important;
}

:deep(.row-failed:hover td) {
  background: rgba(254, 240, 230, 0.96) !important;
}

:deep(.row-highrisk:hover td) {
  background: rgba(254, 236, 236, 0.96) !important;
}

:deep(.ant-table-row:hover td) {
  background: rgba(237,245,255,0.88) !important;
}

/* 患者名 */
.patient-cell {
  display: flex;
  align-items: center;
  gap: 5px;
}

.patient-name {
  font-size: 13px;
  font-weight: 600;
  color: #16324f;
}

.risk-badge {
  font-size: 10px;
  background: rgba(239,68,68,0.08);
  color: #dc2626;
  border: 1px solid rgba(239,68,68,0.14);
  border-radius: 999px;
  padding: 1px 6px;
  font-weight: 700;
  flex-shrink: 0;
}

.id-text {
  font-size: 12px;
  color: #5f7894;
  font-family: monospace;
}

.time-text {
  font-size: 12px;
  color: #475569;
}

.no-analysis {
  font-size: 12px;
  color: #cbd5e1;
}

/* 数据源标签 */
.data-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
}

.data-tag {
  font-size: 11px;
  border: 1px solid;
  border-radius: 999px;
  padding: 1px 7px;
  background: rgba(255,255,255,0.9);
  font-weight: 600;
}

/* 操作按钮 */
.action-btns {
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-link {
  font-size: 12px;
  padding: 0 4px;
  color: #2f6fed;
}

.action-link:hover {
  color: #19c6d0;
}

.action-link-weak {
  font-size: 12px;
  padding: 0 4px;
  color: #8aa0b8;
}

.action-link-weak:hover:not(:disabled) {
  color: #5f7894;
}

.trigger-tag {
  font-size: 12px;
  color: #8aa0b8;
}

.trigger-pacs {
  color: #4f46e5;
  font-weight: 700;
}

:deep(.ant-btn) {
  border-radius: 12px;
}

:deep(.ant-btn-primary) {
  border: none !important;
  background: #2f9fe2 !important;
  box-shadow: 0 14px 28px rgba(47, 159, 226, 0.18);
  font-weight: 700;
}

:deep(.ant-btn-primary:hover),
:deep(.ant-btn-primary:focus) {
  background: #2f9fe2 !important;
}

:deep(.ant-btn-default:not(:disabled)) {
  border-color: rgba(92,128,170,0.18) !important;
  color: #52708e !important;
  background: rgba(255,255,255,0.82) !important;
}

:deep(.ant-input),
:deep(.ant-select-selector),
:deep(.ant-picker) {
  border-radius: 12px !important;
  border-color: rgba(116,152,193,0.14) !important;
  background: rgba(248,251,255,0.8) !important;
}

:deep(.ant-input:focus),
:deep(.ant-input-focused),
:deep(.ant-select-focused .ant-select-selector),
:deep(.ant-picker-focused) {
  border-color: rgba(47,111,237,0.24) !important;
  box-shadow: 0 0 0 4px rgba(47,111,237,0.08) !important;
}

:deep(.ant-table) {
  background: transparent;
}

:deep(.ant-table-container) {
  border-radius: 14px;
  overflow: hidden;
}

:deep(.ant-table-thead > tr > th) {
  background: rgba(244, 249, 255, 0.94) !important;
  color: #5c7692 !important;
  font-weight: 700;
  border-bottom: 1px solid rgba(116, 152, 193, 0.12) !important;
}

:deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid rgba(116, 152, 193, 0.08) !important;
  background: rgba(255,255,255,0.32);
}

:deep(.ant-tag) {
  border-radius: 999px;
  font-weight: 600;
}

:deep(.ant-pagination .ant-pagination-item) {
  border-radius: 10px;
}

:deep(.ant-pagination .ant-pagination-item-active) {
  border-color: #2f6fed;
}

:deep(.ant-pagination .ant-pagination-item-active a) {
  color: #2f6fed;
}

:deep(.ant-checkbox-inner) {
  border-radius: 6px;
}

:deep(.ant-spin-dot-item) {
  background-color: #2f6fed;
}
</style>
