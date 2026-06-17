<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter, useRoute } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const route = useRoute()

// ── Patient list ──────────────────────────────────────────────
const patients = ref([])
const loadingPatients = ref(false)
const selectedPatient = ref(null)
const searchQuery = ref('')
const filterHasImage = ref(null)
const filterHasPathology = ref(null)

const filteredPatients = computed(() => {
  let list = patients.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(p =>
      p.name?.toLowerCase().includes(q) ||
      p.phone?.includes(q) ||
      p.id_card?.includes(q) ||
      p.empi_id?.toLowerCase().includes(q) ||
      String(p.id).includes(q)
    )
  }
  if (filterHasImage.value === true) list = list.filter(p => p.has_pacs)
  if (filterHasPathology.value === true) list = list.filter(p => p.has_lis)
  return list
})

async function fetchPatients() {
  loadingPatients.value = true
  try {
    const res = await apiFetch('/api/patients')
    patients.value = await res.json()
  } catch {
    message.error('加载患者列表失败')
  } finally {
    loadingPatients.value = false
  }
}

function resetFilters() {
  searchQuery.value = ''
  filterHasImage.value = null
  filterHasPathology.value = null
}

const patientColumns = [
  { title: '患者', key: 'name', width: 130 },
  { title: '性别 / 年龄', key: 'demog', width: 90 },
  { title: 'EMPI 编号', key: 'empi', width: 150 },
  { title: '最近就诊', key: 'last_visit', width: 100 },
  { title: '数据标签', key: 'sources', width: 140 },
  { title: '操作', key: 'action', width: 70, align: 'center' },
]

function genderLabel(g) {
  if (g === 1 || g === '1' || g === '男') return '男'
  if (g === 2 || g === '2' || g === '女') return '女'
  return '-'
}

function calcAge(birthDate) {
  if (!birthDate) return null
  const birth = new Date(birthDate)
  const now = new Date()
  const age = now.getFullYear() - birth.getFullYear()
  return age > 0 ? age : null
}

function formatDate(v) {
  if (!v) return '-'
  return String(v).slice(0, 10)
}

// ── Clinical view ────────────────────────────────────────────
const clinicalView = ref(null)
const cvLoading = ref(false)

async function selectPatient(p) {
  if (selectedPatient.value?.id === p.id) return
  selectedPatient.value = p
  clinicalView.value = null
  cvLoading.value = true
  cvExpanded.value = false
  try {
    const res = await apiFetch(`/api/patients/${p.id}/clinical-view`)
    if (res.ok) clinicalView.value = await res.json()
  } catch {
  } finally {
    cvLoading.value = false
  }
}

const cvHis = computed(() => clinicalView.value?.his || [])
const cvLis = computed(() => clinicalView.value?.lis || [])
const cvPacs = computed(() => clinicalView.value?.pacs || [])
const cvTasks = computed(() => clinicalView.value?.ai_tasks || [])

function hasSource(src) {
  if (src === 'HIS') return cvHis.value.length > 0
  if (src === 'LIS') return cvLis.value.length > 0
  if (src === 'PACS') return cvPacs.value.length > 0
  return false
}

const latestHis = computed(() => cvHis.value[0] || null)
const recentPacs = computed(() => cvPacs.value.slice(0, 3))

// ── Complete clinical view (fold/unfold) ──────────────────────
const cvExpanded = ref(false)
const cvActiveTab = ref('overview')

function toggleClinicalView() {
  cvExpanded.value = !cvExpanded.value
  if (cvExpanded.value) cvActiveTab.value = 'overview'
}

// ── AI analysis confirm dialog ────────────────────────────────
const showConfirmDialog = ref(false)
const launching = ref(false)

function openAnalysisDialog() {
  if (!selectedPatient.value) return
  showConfirmDialog.value = true
}

async function confirmLaunch() {
  if (!selectedPatient.value) return
  const pacsRecords = cvPacs.value
  if (!pacsRecords.length) {
    message.warning('该患者暂无 PACS 影像记录，无法从归一化数据发起分析')
    return
  }
  const firstPacs = pacsRecords[0]
  launching.value = true
  try {
    const res = await apiFetch('/api/tasks/from-pacs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pacs_record_id: firstPacs.record_id,
        patient_id: selectedPatient.value.id,
      }),
    })
    if (res.ok) {
      const { task_id } = await res.json()
      showConfirmDialog.value = false
      router.push(`/tasks/${task_id}`)
    } else {
      const err = await res.json().catch(() => ({}))
      message.error('发起失败：' + (err.error || res.status))
    }
  } catch (e) {
    message.error('请求失败：' + e.message)
  } finally {
    launching.value = false
  }
}

function taskStatusColor(s) {
  if (s === 'complete' || s === 'done') return 'success'
  if (s === 'error' || s === 'failed') return 'error'
  return 'processing'
}

function taskStatusLabel(s) {
  if (s === 'complete' || s === 'done') return '已完成'
  if (s === 'error' || s === 'failed') return '失败'
  if (s === 'pending') return '等待中'
  return '分析中'
}

function goTasks() {
  if (!selectedPatient.value) return
  router.push({ path: '/tasks', query: { patient_id: selectedPatient.value.id } })
}

// ── Mounted ───────────────────────────────────────────────────
onMounted(async () => {
  await fetchPatients()
  const pid = route.query.patient_id
  if (pid) {
    const target = patients.value.find(p => String(p.id) === String(pid))
    if (target) await selectPatient(target)
  }
  const q = route.query.q
  if (q) searchQuery.value = q
})
</script>

<template>
  <div class="page">

    <!-- 区块1：顶部检索筛选栏 -->
    <div class="page-header">
      <div class="page-title">患者管理</div>
      <div class="page-sub">检索患者 · 查看 AI 诊断报告 · 深查完整临床视图</div>
    </div>

    <div class="search-bar-card">
      <div class="search-main">
        <a-input
          v-model:value="searchQuery"
          placeholder="姓名 / 手机 / 身份证 / 病历号 / EMPI"
          allow-clear
          size="large"
          class="search-input"
        >
          <template #prefix>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="color:#94a3b8"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </template>
        </a-input>
      </div>
      <div class="filter-group">
        <div class="filter-item">
          <span class="filter-label">影像</span>
          <a-select v-model:value="filterHasImage" size="small" style="width:88px" allow-clear placeholder="全部">
            <a-select-option :value="true">有影像</a-select-option>
            <a-select-option :value="false">无影像</a-select-option>
          </a-select>
        </div>
        <div class="filter-item">
          <span class="filter-label">病理</span>
          <a-select v-model:value="filterHasPathology" size="small" style="width:88px" allow-clear placeholder="全部">
            <a-select-option :value="true">有病理</a-select-option>
            <a-select-option :value="false">无病理</a-select-option>
          </a-select>
        </div>
        <a-button size="small" @click="resetFilters" style="color:#64748b">重置</a-button>
      </div>
    </div>

    <!-- 区块2：患者列表（固定高度，最多 3 条） -->
    <div class="card table-card">
      <div class="card-head">
        <div class="card-title">患者列表</div>
        <span class="card-sub">{{ filteredPatients.length }} 位患者</span>
      </div>
      <a-table
        :columns="patientColumns"
        :data-source="filteredPatients"
        :loading="loadingPatients"
        row-key="id"
        size="middle"
        :pagination="{ pageSize: 3, showSizeChanger: false, size: 'small' }"
        :scroll="{ y: 168 }"
        :row-class-name="record => record.id === selectedPatient?.id ? 'row-selected' : ''"
        :custom-row="record => ({ onClick: () => selectPatient(record) })"
        :locale="{ emptyText: searchQuery ? '无匹配患者' : '暂无患者数据' }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="patient-name-cell">
              <div class="p-avatar" :class="{ 'p-avatar-selected': record.id === selectedPatient?.id }">
                {{ record.name?.[0] || '?' }}
              </div>
              <div>
                <div class="p-name">{{ record.name }}</div>
                <div v-if="record.phone" class="p-phone">{{ record.phone }}</div>
              </div>
            </div>
          </template>
          <template v-else-if="column.key === 'demog'">
            <span class="demog-text">
              {{ genderLabel(record.gender) }}
              <template v-if="calcAge(record.birth_date)"> · {{ calcAge(record.birth_date) }} 岁</template>
            </span>
          </template>
          <template v-else-if="column.key === 'empi'">
            <div class="empi-cell">
              <span v-if="record.empi_id" class="empi-tag">{{ record.empi_id }}</span>
              <span v-else class="empi-none">未归一</span>
              <span class="id-text">病历号 {{ record.id }}</span>
            </div>
          </template>
          <template v-else-if="column.key === 'last_visit'">
            <span class="date-text">{{ formatDate(record.last_visit_at || record.created_at) }}</span>
          </template>
          <template v-else-if="column.key === 'sources'">
            <a-space :size="4" wrap>
              <a-tag v-if="record.has_his" color="green" class="data-tag">HIS</a-tag>
              <a-tag v-if="record.has_lis" color="gold" class="data-tag">病理</a-tag>
              <a-tag v-if="record.has_pacs" color="blue" class="data-tag">影像</a-tag>
              <span v-if="!record.has_his && !record.has_lis && !record.has_pacs" class="no-data">—</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" size="small" @click.stop="selectPatient(record)">
              {{ record.id === selectedPatient?.id ? '已选' : '选择' }}
            </a-button>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 空状态 -->
    <div v-if="!selectedPatient" class="empty-workspace">
      <div class="empty-icon-wrap">
        <svg width="38" height="38" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="8" r="4" stroke="#cbd5e1" stroke-width="1.5"/><path d="M4 20c0-3.314 3.582-6 8-6s8 2.686 8 6" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round"/></svg>
      </div>
      <div class="empty-hint">从上方列表点击一位患者，查看 AI 诊断报告与完整临床数据</div>
    </div>

    <!-- 区块3 + 后续：选中患者工作区 -->
    <template v-else>

      <!-- 区块3：患者摘要头 -->
      <div class="patient-workspace-head">
        <div class="pwh-left">
          <div class="pwh-avatar">{{ selectedPatient.name?.[0] || '?' }}</div>
          <div class="pwh-info">
            <div class="pwh-name">{{ selectedPatient.name }}</div>
            <div class="pwh-meta">
              <span v-if="selectedPatient.gender"><span class="meta-dim">性别</span>{{ genderLabel(selectedPatient.gender) }}</span>
              <span v-if="calcAge(selectedPatient.birth_date)"><span class="meta-dim">年龄</span>{{ calcAge(selectedPatient.birth_date) }} 岁</span>
              <span v-if="selectedPatient.phone"><span class="meta-dim">手机</span>{{ selectedPatient.phone }}</span>
              <span v-if="selectedPatient.id_card"><span class="meta-dim">身份证</span>{{ selectedPatient.id_card }}</span>
              <span v-if="selectedPatient.empi_id"><span class="meta-dim">EMPI</span>{{ selectedPatient.empi_id }}</span>
              <span><span class="meta-dim">病历号</span>{{ selectedPatient.id }}</span>
            </div>
            <!-- 数据覆盖条 -->
            <div class="pwh-coverage">
              <div v-if="cvLoading" class="coverage-loading">
                <a-spin size="small"/>
                <span>加载临床数据…</span>
              </div>
              <template v-else-if="clinicalView">
                <div class="cov-item" :class="{ 'cov-on': hasSource('HIS') }">
                  <span class="cov-dot"></span><span class="cov-label">HIS</span><span class="cov-count">{{ cvHis.length }}</span>
                </div>
                <div class="cov-item" :class="{ 'cov-on': hasSource('LIS') }">
                  <span class="cov-dot"></span><span class="cov-label">LIS / 病理</span><span class="cov-count">{{ cvLis.length }}</span>
                </div>
                <div class="cov-item" :class="{ 'cov-on': hasSource('PACS') }">
                  <span class="cov-dot"></span><span class="cov-label">PACS</span><span class="cov-count">{{ cvPacs.length }}</span>
                </div>
                <div class="cov-item" :class="{ 'cov-on': cvTasks.length > 0 }">
                  <span class="cov-dot"></span><span class="cov-label">AI 诊断</span><span class="cov-count">{{ cvTasks.length }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="pwh-actions">
          <a-button type="primary" size="large" @click="goTasks" class="btn-primary-action">
            查看历史 AI 报告
          </a-button>
          <a-button size="default" @click="openAnalysisDialog" class="btn-secondary-action">
            重新生成 AI 分析
          </a-button>
          <a-button
            size="default"
            :class="['btn-secondary-action', cvExpanded ? 'btn-active' : '']"
            @click="toggleClinicalView"
          >
            {{ cvExpanded ? '收起临床视图' : '展开完整临床视图' }}
          </a-button>
        </div>
      </div>

      <!-- 区块4：三栏轻量摘要 -->
      <div v-if="cvLoading" class="cards-loading">
        <a-spin size="small"/><span>加载临床数据…</span>
      </div>

      <div v-else-if="clinicalView" class="summary-cards">
        <!-- 卡片1：最近就诊 -->
        <div class="summary-card">
          <div class="sc-head">
            <span class="sc-title">最近就诊</span>
            <a-tag v-if="latestHis" color="green" class="sc-tag">HIS</a-tag>
          </div>
          <div v-if="latestHis" class="sc-body">
            <div class="sc-row"><span class="sc-label">就诊日期</span><span class="sc-val">{{ formatDate(latestHis.visit_date) }}</span></div>
            <div class="sc-row"><span class="sc-label">科室</span><span class="sc-val">{{ latestHis.department || '-' }}</span></div>
            <div class="sc-row"><span class="sc-label">主诉</span><span class="sc-val sc-val-wrap">{{ latestHis.chief_complaint || '-' }}</span></div>
            <div class="sc-row"><span class="sc-label">诊断</span><span class="sc-val">{{ latestHis.diagnosis_name || latestHis.diagnosis_code || '-' }}</span></div>
            <div v-if="cvHis.length > 1" class="sc-more">共 {{ cvHis.length }} 条就诊记录</div>
          </div>
          <div v-else class="sc-empty">暂无 HIS 就诊记录</div>
        </div>

        <!-- 卡片2：数据覆盖 -->
        <div class="summary-card">
          <div class="sc-head"><span class="sc-title">数据覆盖</span></div>
          <div class="sc-body">
            <div class="stat-grid">
              <div class="stat-cell stat-his"><div class="stat-num">{{ cvHis.length }}</div><div class="stat-lbl">HIS 就诊</div></div>
              <div class="stat-cell stat-lis"><div class="stat-num">{{ cvLis.length }}</div><div class="stat-lbl">LIS / 病理</div></div>
              <div class="stat-cell stat-pacs"><div class="stat-num">{{ cvPacs.length }}</div><div class="stat-lbl">PACS 影像</div></div>
              <div class="stat-cell stat-ai"><div class="stat-num">{{ cvTasks.length }}</div><div class="stat-lbl">AI 任务</div></div>
            </div>
            <div v-if="cvLis.length > 0" class="lis-summary">
              <div class="sc-row" style="margin-top:8px"><span class="sc-label">最近检验</span><span class="sc-val">{{ cvLis[0]?.test_name || '-' }}</span></div>
              <div class="sc-row">
                <span class="sc-label">结果</span>
                <span class="sc-val" :class="{ 'val-abnormal': cvLis[0]?.abnormal_flag }">
                  {{ cvLis[0]?.value ?? '-' }} {{ cvLis[0]?.unit || '' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 卡片3：影像记录 -->
        <div class="summary-card">
          <div class="sc-head">
            <span class="sc-title">影像记录</span>
            <a-tag v-if="cvPacs.length" color="blue" class="sc-tag">PACS {{ cvPacs.length }}</a-tag>
          </div>
          <div v-if="recentPacs.length" class="pacs-thumb-row">
            <div v-for="r in recentPacs" :key="r.id" class="pacs-item">
              <img v-if="r.thumbnail_url || r.image_url" :src="r.thumbnail_url || r.image_url" :alt="r.description || 'PACS'" class="pacs-thumb"/>
              <div v-else class="pacs-thumb pacs-thumb-empty">无图</div>
              <div class="pacs-item-meta">
                <span class="pacs-modality">{{ r.modality || '-' }}</span>
                <span class="pacs-date">{{ formatDate(r.recorded_at) }}</span>
              </div>
            </div>
          </div>
          <div v-else class="sc-empty">暂无 PACS 影像记录</div>
          <div v-if="cvPacs.length > 3" class="sc-more">共 {{ cvPacs.length }} 条影像记录</div>
        </div>
      </div>

      <!-- 区块5：历史 AI 诊断报告 -->
      <div v-if="clinicalView" class="card ai-report-card">
        <div class="card-head">
          <div class="card-title">历史 AI 诊断报告</div>
          <span class="card-sub">{{ cvTasks.length ? `共 ${cvTasks.length} 条` : '暂无' }}</span>
          <a-button type="link" size="small" @click="goTasks" style="margin-left:auto;padding:0">全部记录</a-button>
        </div>
        <div v-if="!cvTasks.length" class="ai-empty">
          <div class="ai-empty-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="5" width="18" height="14" rx="2" stroke="#cbd5e1" stroke-width="1.5"/><path d="M7 9h10M7 13h6" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round"/></svg>
          </div>
          <div class="ai-empty-text">该患者暂无 AI 诊断记录</div>
          <div class="ai-empty-hint">系统将在患者数据更新后自动生成诊断报告；也可点击「重新生成 AI 分析」手动触发</div>
        </div>
        <div v-else class="ai-task-list">
          <div
            v-for="t in cvTasks"
            :key="t.task_id"
            class="ai-task-row"
            @click="router.push('/tasks/' + t.task_id)"
          >
            <a-tag :color="taskStatusColor(t.status)" class="task-status-tag">{{ taskStatusLabel(t.status) }}</a-tag>
            <div class="ai-task-info">
              <span class="ai-task-id">任务 #{{ String(t.task_id).slice(0, 8) }}</span>
              <span class="ai-task-date">{{ formatDate(t.created_at) }}</span>
            </div>
            <div v-if="t.risk_level" class="ai-risk-badge" :class="'risk-' + t.risk_level">
              风险：{{ t.risk_level }}
            </div>
            <a-button type="link" size="small" class="task-link">查看详情</a-button>
          </div>
        </div>
      </div>

      <!-- 区块6：完整临床视图折叠展开区 -->
      <div v-if="clinicalView" class="cv-fold-wrap">
        <div class="cv-fold-header" @click="toggleClinicalView">
          <div class="cv-fold-title">
            <svg v-if="!cvExpanded" width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M5 3l4 4-4 4" stroke="#64748b" stroke-width="1.5" stroke-linecap="round"/></svg>
            <svg v-else width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 5l4 4 4-4" stroke="#14b8a6" stroke-width="1.5" stroke-linecap="round"/></svg>
            <span :class="cvExpanded ? 'cv-fold-label-active' : 'cv-fold-label'">完整临床视图</span>
            <span class="cv-fold-sub">HIS · LIS · PACS · AI 任务</span>
          </div>
          <span class="cv-fold-toggle">{{ cvExpanded ? '收起' : '展开' }}</span>
        </div>

        <div v-if="cvExpanded" class="cv-panel">
          <a-tabs v-model:activeKey="cvActiveTab" size="small" class="cv-tabs">

            <!-- Tab：概览 -->
            <a-tab-pane key="overview" tab="概览">
              <div class="cv-overview-grid">
                <div class="cvo-card">
                  <div class="cvo-label">HIS 就诊</div>
                  <div class="cvo-num his">{{ cvHis.length }}</div>
                </div>
                <div class="cvo-card">
                  <div class="cvo-label">LIS / 病理</div>
                  <div class="cvo-num lis">{{ cvLis.length }}</div>
                </div>
                <div class="cvo-card">
                  <div class="cvo-label">PACS 影像</div>
                  <div class="cvo-num pacs">{{ cvPacs.length }}</div>
                </div>
                <div class="cvo-card">
                  <div class="cvo-label">AI 诊断</div>
                  <div class="cvo-num ai">{{ cvTasks.length }}</div>
                </div>
              </div>
              <div class="cvo-empi" v-if="selectedPatient?.empi_id">
                <span class="cvo-field">EMPI 归一编号</span>
                <span class="cvo-mono">{{ selectedPatient.empi_id }}</span>
              </div>
              <div class="cvo-coverage-list">
                <div class="cvo-cov-row" :class="{ on: hasSource('HIS') }">
                  <span class="cvo-dot"></span><span>HIS 病历</span><span class="cvo-cov-badge">{{ hasSource('HIS') ? '已覆盖' : '缺失' }}</span>
                </div>
                <div class="cvo-cov-row" :class="{ on: hasSource('LIS') }">
                  <span class="cvo-dot"></span><span>LIS / 病理</span><span class="cvo-cov-badge">{{ hasSource('LIS') ? '已覆盖' : '缺失' }}</span>
                </div>
                <div class="cvo-cov-row" :class="{ on: hasSource('PACS') }">
                  <span class="cvo-dot"></span><span>PACS 影像</span><span class="cvo-cov-badge">{{ hasSource('PACS') ? '已覆盖' : '缺失' }}</span>
                </div>
              </div>
            </a-tab-pane>

            <!-- Tab：HIS -->
            <a-tab-pane key="his" tab="HIS 门诊">
              <div v-if="!cvHis.length" class="cv-empty">暂无 HIS 就诊记录</div>
              <div v-else class="cv-record-list">
                <div v-for="(h, i) in cvHis" :key="i" class="cv-record-row">
                  <div class="cv-rec-date">{{ formatDate(h.visit_date) }}</div>
                  <div class="cv-rec-body">
                    <div class="cv-rec-row"><span class="cv-rec-lbl">科室</span><span>{{ h.department || '-' }}</span></div>
                    <div class="cv-rec-row"><span class="cv-rec-lbl">主诉</span><span>{{ h.chief_complaint || '-' }}</span></div>
                    <div class="cv-rec-row"><span class="cv-rec-lbl">诊断</span><span>{{ h.diagnosis_name || h.diagnosis_code || '-' }}</span></div>
                    <div v-if="h.doctor_name" class="cv-rec-row"><span class="cv-rec-lbl">医生</span><span>{{ h.doctor_name }}</span></div>
                  </div>
                </div>
              </div>
            </a-tab-pane>

            <!-- Tab：LIS -->
            <a-tab-pane key="lis" tab="LIS / 病理">
              <div v-if="!cvLis.length" class="cv-empty">暂无 LIS / 病理记录</div>
              <div v-else class="cv-record-list">
                <div v-for="(l, i) in cvLis" :key="i" class="cv-record-row">
                  <div class="cv-rec-date">{{ formatDate(l.collected_at || l.reported_at) }}</div>
                  <div class="cv-rec-body">
                    <div class="cv-rec-row"><span class="cv-rec-lbl">项目</span><span>{{ l.test_name || '-' }}</span></div>
                    <div class="cv-rec-row">
                      <span class="cv-rec-lbl">结果</span>
                      <span :class="{ 'val-abnormal': l.abnormal_flag }">{{ l.value ?? '-' }} {{ l.unit || '' }}</span>
                    </div>
                    <div v-if="l.reference_range" class="cv-rec-row"><span class="cv-rec-lbl">参考值</span><span>{{ l.reference_range }}</span></div>
                    <div v-if="l.breslow_thickness" class="cv-rec-row"><span class="cv-rec-lbl">Breslow</span><span>{{ l.breslow_thickness }} mm</span></div>
                    <div v-if="l.braf_mutation" class="cv-rec-row"><span class="cv-rec-lbl">BRAF</span><span>{{ l.braf_mutation }}</span></div>
                  </div>
                </div>
              </div>
            </a-tab-pane>

            <!-- Tab：PACS -->
            <a-tab-pane key="pacs" tab="PACS 影像">
              <div v-if="!cvPacs.length" class="cv-empty">暂无 PACS 影像记录</div>
              <div v-else class="pacs-full-grid">
                <div v-for="r in cvPacs" :key="r.id" class="pacs-full-item">
                  <img v-if="r.thumbnail_url || r.image_url" :src="r.thumbnail_url || r.image_url" :alt="r.description || 'PACS'" class="pacs-full-thumb"/>
                  <div v-else class="pacs-full-thumb pacs-thumb-empty">无图</div>
                  <div class="pacs-full-meta">
                    <span class="pacs-modality">{{ r.modality || '-' }}</span>
                    <span class="pacs-date">{{ formatDate(r.recorded_at) }}</span>
                    <span v-if="r.description" class="pacs-desc">{{ r.description }}</span>
                  </div>
                </div>
              </div>
            </a-tab-pane>

            <!-- Tab：AI 任务 -->
            <a-tab-pane key="tasks" tab="AI 任务">
              <div v-if="!cvTasks.length" class="cv-empty">暂无 AI 任务记录</div>
              <div v-else class="cv-record-list">
                <div
                  v-for="t in cvTasks"
                  :key="t.task_id"
                  class="cv-task-row"
                  @click="router.push('/tasks/' + t.task_id)"
                >
                  <a-tag :color="taskStatusColor(t.status)" class="task-status-tag">{{ taskStatusLabel(t.status) }}</a-tag>
                  <span class="cv-task-id">任务 #{{ String(t.task_id).slice(0, 8) }}</span>
                  <span class="cv-task-date">{{ formatDate(t.created_at) }}</span>
                  <a-button type="link" size="small" class="task-link">查看报告</a-button>
                </div>
              </div>
            </a-tab-pane>

          </a-tabs>
        </div>
      </div>

    </template>
  </div>

  <!-- 确认重新生成 AI 分析弹窗 -->
  <a-modal
    v-model:open="showConfirmDialog"
    title="重新生成 AI 分析"
    ok-text="确认发起"
    cancel-text="取消"
    :confirm-loading="launching"
    :ok-button-props="{ disabled: !hasSource('PACS') }"
    @ok="confirmLaunch"
    width="460px"
  >
    <div v-if="selectedPatient" class="confirm-body">
      <div class="confirm-patient-row">
        <div class="cp-avatar">{{ selectedPatient.name?.[0] }}</div>
        <div>
          <div class="cp-name">{{ selectedPatient.name }}</div>
          <div class="cp-sub">
            {{ genderLabel(selectedPatient.gender) }}
            <template v-if="calcAge(selectedPatient.birth_date)"> · {{ calcAge(selectedPatient.birth_date) }} 岁</template>
            · 病历号 {{ selectedPatient.id }}
          </div>
        </div>
      </div>
      <div class="confirm-section-title">当前可用数据</div>
      <div class="confirm-data-list">
        <div class="cdl-item" :class="{ available: hasSource('PACS') }">
          <span class="cdl-dot"></span><span class="cdl-name">PACS 影像</span>
          <span class="cdl-count">{{ cvPacs.length }} 条</span>
          <span v-if="!hasSource('PACS')" class="cdl-missing">缺失</span>
        </div>
        <div class="cdl-item" :class="{ available: hasSource('HIS') }">
          <span class="cdl-dot"></span><span class="cdl-name">HIS 病历</span>
          <span class="cdl-count">{{ cvHis.length }} 条</span>
          <span v-if="!hasSource('HIS')" class="cdl-missing">缺失</span>
        </div>
        <div class="cdl-item" :class="{ available: hasSource('LIS') }">
          <span class="cdl-dot"></span><span class="cdl-name">LIS / 病理</span>
          <span class="cdl-count">{{ cvLis.length }} 条</span>
          <span v-if="!hasSource('LIS')" class="cdl-missing">缺失</span>
        </div>
      </div>
      <a-alert
        v-if="!hasSource('PACS')"
        type="warning"
        show-icon
        message="该患者暂无 PACS 影像记录"
        description="影像是发起 AI 分析的必要输入。请先确认 PACS 影像已归入该患者。"
        style="margin-top:14px"
      />
      <div v-else class="confirm-note">
        系统将以最近一条 PACS 影像为主图，自动聚合 HIS 病历与 LIS 化验数据，一并提交 AI 推理。无需手工填写任何信息。
      </div>
    </div>
  </a-modal>
</template>

<style scoped>
.page {
  padding: 26px 32px 40px;
  background: #f5f7fa;
  min-height: 100%;
}

.page-header { margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 700; color: #1e293b; border-left: 3px solid #14B8A6; padding-left: 12px; line-height: 1.3; }
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 5px; padding-left: 15px; }

.search-bar-card {
  background: #fff;
  border-radius: 12px;
  padding: 14px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}
.search-main { flex: 1; min-width: 200px; max-width: 500px; }
.search-input { width: 100%; }
.filter-group { display: flex; align-items: center; gap: 12px; flex-shrink: 0; flex-wrap: wrap; }
.filter-item { display: flex; align-items: center; gap: 6px; }
.filter-label { font-size: 12px; color: #64748b; white-space: nowrap; }

.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  padding: 18px 20px;
  margin-bottom: 14px;
}

.table-card {
  padding: 16px 16px 10px;
  min-height: 260px;
  display: flex;
  flex-direction: column;
}
.table-card :deep(.ant-table-wrapper) { flex: 1; }
.table-card :deep(.ant-spin-nested-loading) { height: 100%; }
.table-card :deep(.ant-spin-container) { height: 100%; display: flex; flex-direction: column; }
.table-card :deep(.ant-table) { flex: 1; }
.table-card :deep(.ant-pagination) { margin-top: auto; padding-top: 8px; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.card-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.card-sub { font-size: 11px; color: #94a3b8; }

:deep(.row-selected td) { background: #eff6ff !important; }
:deep(.row-selected:hover td) { background: #dbeafe !important; }
:deep(.ant-table-row) { cursor: pointer; }

.patient-name-cell { display: flex; align-items: center; gap: 9px; }
.p-avatar { width: 30px; height: 30px; border-radius: 50%; background: #e2e8f0; color: #475569; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background 0.15s, color 0.15s; }
.p-avatar-selected { background: #dbeafe; color: #2563eb; }
.p-name { font-size: 13px; font-weight: 600; color: #1e293b; line-height: 1.3; }
.p-phone { font-size: 11px; color: #94a3b8; }
.demog-text { font-size: 12px; color: #64748b; }
.empi-cell { display: flex; flex-direction: column; gap: 2px; }
.empi-tag { font-size: 11px; color: #059669; font-weight: 600; font-family: monospace; }
.empi-none { font-size: 11px; color: #cbd5e1; }
.id-text { font-size: 11px; color: #94a3b8; }
.date-text { font-size: 12px; color: #64748b; }
.data-tag { margin: 0; font-size: 11px; }
.no-data { font-size: 11px; color: #cbd5e1; }

.empty-workspace { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 52px 0 24px; gap: 12px; }
.empty-icon-wrap { color: #cbd5e1; }
.empty-hint { font-size: 13px; color: #94a3b8; }

.patient-workspace-head {
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04);
  padding: 22px 26px 20px;
  margin-bottom: 14px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.pwh-left { display: flex; align-items: flex-start; gap: 16px; flex: 1; min-width: 0; }
.pwh-avatar { width: 54px; height: 54px; border-radius: 50%; background: linear-gradient(135deg, #e0f2fe 0%, #dbeafe 100%); color: #2563eb; font-size: 22px; font-weight: 800; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 2px solid #bfdbfe; }
.pwh-info { flex: 1; min-width: 0; }
.pwh-name { font-size: 22px; font-weight: 800; color: #0f172a; margin-bottom: 8px; line-height: 1.2; }
.pwh-meta { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 13px; color: #475569; margin-bottom: 14px; }
.meta-dim { color: #94a3b8; margin-right: 4px; font-size: 12px; }
.pwh-coverage { display: flex; align-items: center; gap: 20px; padding-top: 12px; border-top: 1px solid #f1f5f9; flex-wrap: wrap; }
.coverage-loading { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #94a3b8; }
.cov-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #94a3b8; }
.cov-dot { width: 7px; height: 7px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0; }
.cov-on .cov-dot { background: #10b981; }
.cov-on .cov-label { color: #1e293b; }
.cov-label { font-weight: 500; }
.cov-count { color: #94a3b8; }
.pwh-actions { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; align-items: flex-end; }
.btn-primary-action { min-width: 140px; }
.btn-secondary-action { min-width: 140px; }
.btn-active { color: #14b8a6 !important; border-color: #14b8a6 !important; }

.cards-loading { display: flex; align-items: center; gap: 10px; padding: 24px 0; font-size: 12px; color: #94a3b8; }
.summary-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 14px; }
.summary-card { background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.03); padding: 16px 18px; }
.sc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.sc-title { font-size: 13px; font-weight: 700; color: #1e293b; flex: 1; }
.sc-tag { margin: 0; font-size: 11px; }
.sc-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: #475569; margin-bottom: 7px; }
.sc-label { color: #94a3b8; white-space: nowrap; flex-shrink: 0; min-width: 48px; }
.sc-val { color: #334155; line-height: 1.4; }
.sc-val-wrap { word-break: break-all; }
.sc-more { font-size: 11px; color: #94a3b8; margin-top: 6px; }
.sc-empty { font-size: 12px; color: #94a3b8; padding: 8px 0; line-height: 1.6; }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.stat-cell { border-radius: 10px; padding: 10px 10px 8px; text-align: center; }
.stat-his { background: #f0fdf4; }
.stat-lis { background: #fffbeb; }
.stat-pacs { background: #eff6ff; }
.stat-ai { background: #faf5ff; }
.stat-num { font-size: 22px; font-weight: 800; line-height: 1; margin-bottom: 4px; }
.stat-his .stat-num { color: #10b981; }
.stat-lis .stat-num { color: #f59e0b; }
.stat-pacs .stat-num { color: #2563eb; }
.stat-ai .stat-num { color: #7c3aed; }
.stat-lbl { font-size: 11px; color: #64748b; }
.lis-summary { border-top: 1px solid #f1f5f9; padding-top: 4px; }
.val-abnormal { color: #f59e0b; font-weight: 600; }
.pacs-thumb-row { display: flex; gap: 8px; flex-wrap: wrap; }
.pacs-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.pacs-thumb { width: 68px; height: 68px; object-fit: cover; border-radius: 8px; border: 1px solid #e2e8f0; }
.pacs-thumb-empty { width: 68px; height: 68px; border-radius: 8px; border: 1px dashed #dbe2ea; background: #f8fafc; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #94a3b8; }
.pacs-item-meta { display: flex; flex-direction: column; align-items: center; gap: 1px; }
.pacs-modality { font-size: 11px; font-weight: 600; color: #2563eb; }
.pacs-date { font-size: 10px; color: #94a3b8; }

.ai-report-card { padding: 16px 20px; }
.ai-empty { display: flex; flex-direction: column; align-items: center; padding: 28px 0 16px; gap: 8px; }
.ai-empty-icon { color: #cbd5e1; }
.ai-empty-text { font-size: 13px; color: #64748b; font-weight: 500; }
.ai-empty-hint { font-size: 12px; color: #94a3b8; text-align: center; max-width: 380px; line-height: 1.6; }
.ai-task-list { display: flex; flex-direction: column; gap: 6px; }
.ai-task-row { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 10px; background: #f8fafc; cursor: pointer; transition: background 0.12s; }
.ai-task-row:hover { background: #f1f5f9; }
.task-status-tag { margin: 0; font-size: 11px; flex-shrink: 0; }
.ai-task-info { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.ai-task-id { font-size: 12px; color: #475569; font-family: monospace; }
.ai-task-date { font-size: 11px; color: #94a3b8; }
.ai-risk-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; background: #f1f5f9; color: #64748b; }
.risk-high { background: #fef2f2; color: #dc2626; }
.risk-medium { background: #fffbeb; color: #d97706; }
.risk-low { background: #f0fdf4; color: #16a34a; }
.task-link { padding: 0; font-size: 12px; flex-shrink: 0; }

.cv-fold-wrap {
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  margin-bottom: 14px;
  overflow: hidden;
}
.cv-fold-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; cursor: pointer; user-select: none; transition: background 0.12s; }
.cv-fold-header:hover { background: #f8fafc; }
.cv-fold-title { display: flex; align-items: center; gap: 8px; }
.cv-fold-label { font-size: 14px; font-weight: 600; color: #374151; }
.cv-fold-label-active { font-size: 14px; font-weight: 600; color: #14b8a6; }
.cv-fold-sub { font-size: 12px; color: #94a3b8; }
.cv-fold-toggle { font-size: 12px; color: #64748b; }
.cv-panel { border-top: 1px solid #f1f5f9; padding: 16px 20px 20px; }
.cv-tabs :deep(.ant-tabs-nav) { margin-bottom: 14px; }

.cv-overview-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
.cvo-card { background: #f8fafc; border-radius: 10px; padding: 12px; text-align: center; }
.cvo-label { font-size: 11px; color: #64748b; margin-bottom: 4px; }
.cvo-num { font-size: 24px; font-weight: 800; line-height: 1; }
.cvo-num.his { color: #10b981; }
.cvo-num.lis { color: #f59e0b; }
.cvo-num.pacs { color: #2563eb; }
.cvo-num.ai { color: #7c3aed; }
.cvo-empi { display: flex; align-items: center; gap: 10px; font-size: 12px; margin-bottom: 12px; padding: 8px 12px; background: #f0fdf4; border-radius: 8px; }
.cvo-field { color: #94a3b8; flex-shrink: 0; }
.cvo-mono { font-family: monospace; font-size: 12px; color: #059669; font-weight: 600; }
.cvo-coverage-list { display: flex; flex-direction: column; gap: 6px; }
.cvo-cov-row { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: #f8fafc; border-radius: 7px; font-size: 12px; color: #94a3b8; }
.cvo-cov-row.on { color: #374151; }
.cvo-dot { width: 7px; height: 7px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0; }
.cvo-cov-row.on .cvo-dot { background: #10b981; }
.cvo-cov-badge { margin-left: auto; font-size: 11px; font-weight: 600; }
.cvo-cov-row.on .cvo-cov-badge { color: #10b981; }
.cvo-cov-row:not(.on) .cvo-cov-badge { color: #f59e0b; }

.cv-empty { font-size: 12px; color: #94a3b8; padding: 20px 0; text-align: center; }
.cv-record-list { display: flex; flex-direction: column; gap: 10px; max-height: 360px; overflow-y: auto; }
.cv-record-row { display: flex; gap: 14px; padding: 12px 14px; background: #f8fafc; border-radius: 10px; }
.cv-rec-date { font-size: 11px; color: #94a3b8; white-space: nowrap; min-width: 76px; margin-top: 2px; }
.cv-rec-body { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.cv-rec-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: #475569; }
.cv-rec-lbl { color: #94a3b8; white-space: nowrap; flex-shrink: 0; min-width: 42px; }

.pacs-full-grid { display: flex; flex-wrap: wrap; gap: 12px; max-height: 360px; overflow-y: auto; }
.pacs-full-item { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.pacs-full-thumb { width: 90px; height: 90px; object-fit: cover; border-radius: 10px; border: 1px solid #e2e8f0; }
.pacs-full-meta { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.pacs-desc { font-size: 10px; color: #94a3b8; max-width: 90px; text-align: center; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }

.cv-task-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 9px; background: #f8fafc; cursor: pointer; transition: background 0.12s; }
.cv-task-row:hover { background: #f1f5f9; }
.cv-task-id { font-size: 12px; color: #475569; font-family: monospace; flex: 1; }
.cv-task-date { font-size: 12px; color: #94a3b8; white-space: nowrap; }

.confirm-body { padding-top: 4px; }
.confirm-patient-row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; background: #f8fafc; border-radius: 10px; margin-bottom: 18px; }
.cp-avatar { width: 40px; height: 40px; border-radius: 50%; background: #eff6ff; color: #2563eb; font-size: 17px; font-weight: 800; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.cp-name { font-size: 15px; font-weight: 700; color: #1e293b; }
.cp-sub { font-size: 12px; color: #64748b; margin-top: 3px; }
.confirm-section-title { font-size: 11px; font-weight: 700; color: #94a3b8; letter-spacing: 0.6px; text-transform: uppercase; margin-bottom: 10px; }
.confirm-data-list { display: flex; flex-direction: column; gap: 7px; }
.cdl-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #94a3b8; padding: 9px 12px; background: #f8fafc; border-radius: 8px; }
.cdl-item.available { color: #374151; }
.cdl-dot { width: 7px; height: 7px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0; }
.cdl-item.available .cdl-dot { background: #10b981; }
.cdl-name { flex: 1; }
.cdl-count { font-size: 12px; color: #94a3b8; }
.cdl-missing { font-size: 11px; color: #f59e0b; }
.confirm-note { font-size: 12px; color: #64748b; line-height: 1.7; margin-top: 14px; padding: 10px 12px; background: #f0fdf4; border-radius: 8px; }
</style>
