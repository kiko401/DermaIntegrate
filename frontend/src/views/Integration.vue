<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '@/utils/api'

const sources = ref([])
const loading = ref(false)
const router = useRouter()

const selectedPatientId = ref(null)
const clinicalView = ref(null)
const cvLoading = ref(false)
const activeTab = ref('overview')
const keyword = ref('')
const launchingPacs = ref(null)

const systemColors = {
  HIS: '#10B981',
  LIS: '#F59E0B',
  PACS: '#2563EB',
}

async function fetchSources() {
  loading.value = true
  try {
    const res = await apiFetch('/api/empi/sources')
    if (res.ok) {
      sources.value = await res.json()
    } else {
      sources.value = []
    }
  } catch {
    sources.value = []
  } finally {
    loading.value = false
  }
}

async function selectPatient(patientId) {
  if (!patientId) return
  if (selectedPatientId.value === patientId) return

  selectedPatientId.value = patientId
  activeTab.value = 'overview'
  cvLoading.value = true
  clinicalView.value = null

  try {
    const res = await apiFetch(`/api/patients/${patientId}/clinical-view`)
    if (res.ok) {
      clinicalView.value = await res.json()
    } else {
      clinicalView.value = null
    }
  } catch {
    clinicalView.value = null
  } finally {
    cvLoading.value = false
  }
}

onMounted(fetchSources)

async function launchFromPacs(pacsRecord) {
  if (!selectedPatientId.value) return
  launchingPacs.value = pacsRecord.record_id
  try {
    const res = await apiFetch('/api/tasks/from-pacs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pacs_record_id: pacsRecord.record_id,
        patient_id: selectedPatientId.value,
      }),
    })
    if (res.ok) {
      const { task_id } = await res.json()
      router.push(`/tasks/${task_id}`)
    } else {
      const err = await res.json().catch(() => ({}))
      alert('发起分析失败：' + (err.error || res.status))
    }
  } catch (e) {
    alert('发起分析失败：' + e.message)
  } finally {
    launchingPacs.value = null
  }
}

const totalMatched = computed(() => sources.value.filter(r => r.patient_id).length)

const sourceStats = computed(() => ({
  HIS: sources.value.filter(r => r.source_system === 'HIS').length,
  LIS: sources.value.filter(r => r.source_system === 'LIS').length,
  PACS: sources.value.filter(r => r.source_system === 'PACS').length,
}))

const filteredSources = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return sources.value

  return sources.value.filter((r) => {
    return [
      r.source_system,
      r.source_id,
      r.name,
      r.internal_name,
      r.id_card,
      r.phone,
    ]
        .filter(Boolean)
        .some(v => String(v).toLowerCase().includes(q))
  })
})

const columns = [
  {title: '来源', dataIndex: 'source_system', key: 'sys', width: 88},
  {title: '外部 ID', dataIndex: 'source_id', key: 'sid', width: 170},
  {title: '姓名', dataIndex: 'name', key: 'name', width: 82},
  {title: '内部患者', key: 'internal', width: 140},
]

function tagColor(sys) {
  return sys === 'HIS' ? 'green' : sys === 'LIS' ? 'gold' : 'blue'
}

function formatDate(value) {
  if (!value) return '-'
  if (typeof value === 'string') return value.slice(0, 10)
  try {
    return new Date(value).toISOString().slice(0, 10)
  } catch {
    return '-'
  }
}

function formatGender(value) {
  if (value === 1 || value === '1') return '男'
  if (value === 2 || value === '2') return '女'
  return '-'
}

function yesNoFlag(value) {
  if (value === 1 || value === '1' || value === true) return '异常'
  if (value === 0 || value === '0' || value === false) return '正常'
  return '-'
}

const cvPatient = computed(() => clinicalView.value?.patient || {})
const cvSources = computed(() => clinicalView.value?.empi_sources || [])
const cvHis = computed(() => clinicalView.value?.his || [])
const cvLis = computed(() => clinicalView.value?.lis || [])
const cvPacs = computed(() => clinicalView.value?.pacs || [])
const cvTasks = computed(() => clinicalView.value?.ai_tasks || [])
</script>

<template>
  <div class="integration-page">
    <!-- 顶部标题 -->
    <div class="page-header">
      <div class="page-title-wrap">
        <div class="page-title">数据集成</div>
        <div class="page-subtitle">EMPI 主索引映射 · 多源患者身份归一</div>
      </div>
    </div>

    <!-- 顶部汇总 -->
    <div class="top-summary-card">
      <div class="summary-left">
        <div class="summary-item">
          <span class="summary-dot" :style="{ background: systemColors.HIS }"></span>
          <a-tag :color="tagColor('HIS')" class="summary-tag">HIS</a-tag>
          <span class="summary-count">{{ sourceStats.HIS }} 条</span>
        </div>
        <div class="summary-item">
          <span class="summary-dot" :style="{ background: systemColors.LIS }"></span>
          <a-tag :color="tagColor('LIS')" class="summary-tag">LIS</a-tag>
          <span class="summary-count">{{ sourceStats.LIS }} 条</span>
        </div>
        <div class="summary-item">
          <span class="summary-dot" :style="{ background: systemColors.PACS }"></span>
          <a-tag :color="tagColor('PACS')" class="summary-tag">PACS</a-tag>
          <span class="summary-count">{{ sourceStats.PACS }} 条</span>
        </div>
      </div>
      <div class="summary-right">已归一 {{ totalMatched }} / {{ sources.length }} 条</div>
    </div>

    <!-- 下方工作台 -->
    <div class="workspace">
      <!-- 左栏 -->
      <div class="left-panel">
        <div class="panel-card panel-fill">
          <div class="panel-header">
            <div class="panel-title">外部数据源明细</div>
            <a-button size="small" :loading="loading" @click="fetchSources">刷新</a-button>
          </div>

          <div class="search-wrap">
            <a-input
                v-model:value="keyword"
                allow-clear
                placeholder="搜索来源 / 外部ID / 姓名 / 内部患者"
            />
          </div>

          <div class="table-wrap">
            <a-table
                :columns="columns"
                :data-source="filteredSources"
                :loading="loading"
                row-key="id"
                :pagination="false"
                size="small"
                :scroll="{ y: 500 }"
                :row-class-name="record => record.patient_id && record.patient_id === selectedPatientId ? 'selected-row' : ''"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'sys'">
                  <a-tag :color="tagColor(record.source_system)" style="margin: 0; font-size: 11px">
                    {{ record.source_system }}
                  </a-tag>
                </template>

                <template v-else-if="column.key === 'sid'">
                  <span class="source-id-cell">{{ record.source_id }}</span>
                </template>

                <template v-else-if="column.key === 'internal'">
                  <div v-if="record.patient_id" class="internal-cell">
                    <span class="internal-name">{{ record.internal_name }}</span>
                    <a-button
                        size="small"
                        :type="selectedPatientId === record.patient_id ? 'primary' : 'default'"
                        class="view-btn"
                        @click="selectPatient(record.patient_id)"
                    >
                      {{ selectedPatientId === record.patient_id ? '当前' : '查看' }}
                    </a-button>
                  </div>
                  <span v-else class="unmatched-text">未归一</span>
                </template>
              </template>
            </a-table>
          </div>
        </div>
      </div>

      <!-- 右栏 -->
      <div class="right-panel">
        <div v-if="!selectedPatientId" class="panel-card panel-fill empty-state">
          <div class="empty-icon">🩺</div>
          <div class="empty-title">请选择左侧一条已归一患者记录</div>
          <div class="empty-desc">右侧将展示该患者的统一临床视图，包括 HIS / LIS / PACS / AI 任务</div>
        </div>

        <div v-else-if="cvLoading" class="panel-card panel-fill loading-state">
          <a-spin size="large"/>
        </div>

        <div v-else-if="selectedPatientId && !clinicalView" class="panel-card panel-fill error-state">
          加载失败，请重试
        </div>

        <div v-else class="right-content">
          <!-- 患者摘要 -->
          <div class="panel-card patient-summary-card">
            <div class="summary-top">
              <div class="summary-main">
                <div class="patient-name-line">
                  <span class="patient-name">{{ cvPatient.name || '-' }}</span>
                  <span class="patient-id">ID: {{ cvPatient.id || '-' }}</span>
                </div>
                <div class="patient-meta">
                  <span><span class="meta-label">性别</span>{{ formatGender(cvPatient.gender) }}</span>
                  <span><span class="meta-label">出生日期</span>{{ formatDate(cvPatient.birth_date) }}</span>
                  <span><span class="meta-label">EMPI 来源</span>{{ cvSources.length }} 条</span>
                </div>
              </div>

            </div>
          </div>

          <!-- 详情 -->
          <div class="panel-card detail-card">
            <a-tabs v-model:activeKey="activeTab" class="detail-tabs">
              <a-tab-pane key="overview" tab="概览">
                <div class="tab-body">
                  <div class="overview-grid">
                    <div class="overview-stat stat-his">
                      <div class="stat-number">{{ cvHis.length }}</div>
                      <div class="stat-label">HIS 就诊</div>
                    </div>
                    <div class="overview-stat stat-lis">
                      <div class="stat-number">{{ cvLis.length }}</div>
                      <div class="stat-label">LIS 检验</div>
                    </div>
                    <div class="overview-stat stat-pacs">
                      <div class="stat-number">{{ cvPacs.length }}</div>
                      <div class="stat-label">PACS 影像</div>
                    </div>
                    <div class="overview-stat stat-ai">
                      <div class="stat-number">{{ cvTasks.length }}</div>
                      <div class="stat-label">AI 任务</div>
                    </div>
                  </div>

                  <div class="section-title">EMPI 来源映射</div>
                  <div
                      v-for="src in cvSources"
                      :key="src.id"
                      class="mapping-row"
                  >
                    <div class="mapping-left">
                      <a-tag :color="tagColor(src.source_system)" style="margin: 0">{{ src.source_system }}</a-tag>
                      <span class="mapping-id">{{ src.source_id }}</span>
                      <span class="mapping-sep">·</span>
                      <span class="mapping-name">{{ src.ext_name || '-' }}</span>
                    </div>
                    <span class="mapping-time">映射于 {{ formatDate(src.linked_at) }}</span>
                  </div>
                </div>
              </a-tab-pane>

              <a-tab-pane key="his" :tab="`HIS (${cvHis.length})`">
                <div class="tab-body">
                  <div v-if="!cvHis.length" class="empty-inline">暂无 HIS 就诊记录</div>
                  <div v-for="r in cvHis" :key="r.id" class="detail-item-card">
                    <div class="item-head">
                      <span class="item-title">{{ formatDate(r.visit_date) }}</span>
                      <a-tag color="green" style="margin: 0">{{ r.department || '未知科室' }}</a-tag>
                    </div>
                    <div class="item-grid">
                      <div><span class="item-label">就诊类型</span>{{ r.visit_type || '-' }}</div>
                      <div><span class="item-label">诊断编码</span>{{ r.diagnosis_code || '-' }}</div>
                      <div><span class="item-label">诊断名称</span>{{ r.diagnosis_name || '-' }}</div>
                      <div><span class="item-label">主诉</span>{{ r.chief_complaint || '-' }}</div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <a-tab-pane key="lis" :tab="`LIS (${cvLis.length})`">
                <div class="tab-body">
                  <div v-if="!cvLis.length" class="empty-inline">暂无 LIS 检验结果</div>
                  <div v-for="r in cvLis" :key="r.id" class="detail-item-card">
                    <div class="item-head">
                      <span class="item-title">{{ r.test_name || '-' }}</span>
                      <span class="item-time">{{ formatDate(r.reported_at) }}</span>
                    </div>
                    <div class="item-grid">
                      <div><span class="item-label">结果</span>{{ r.value ?? '-' }}</div>
                      <div><span class="item-label">单位</span>{{ r.unit || '-' }}</div>
                      <div><span class="item-label">参考范围</span>{{ r.ref_range || '-' }}</div>
                      <div><span class="item-label">异常标记</span>{{ yesNoFlag(r.abnormal_flag) }}</div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <a-tab-pane key="pacs" :tab="`PACS (${cvPacs.length})`">
                <div class="tab-body">
                  <div v-if="!cvPacs.length" class="empty-inline">暂无 PACS 影像记录</div>
                  <div v-for="r in cvPacs" :key="r.id" class="pacs-card">
                    <div class="pacs-thumb-wrap">
                      <img
                          v-if="r.thumbnail_url || r.image_url"
                          :src="r.thumbnail_url || r.image_url"
                          :alt="r.description || 'thumbnail'"
                          class="pacs-thumb"
                      />
                      <div v-else class="pacs-thumb-empty">无缩略图</div>
                    </div>

                    <div class="pacs-main">
                      <div class="item-head">
                        <span class="item-title">{{ r.modality || '-' }}</span>
                        <a-tag color="blue" style="margin: 0">{{ r.body_part || '-' }}</a-tag>
                        <span class="item-time">{{ formatDate(r.recorded_at) }}</span>
                      </div>

                      <div class="pacs-desc">{{ r.description || '-' }}</div>

                      <div class="link-block">
                        <div><span class="item-label">原图地址</span>{{ r.image_url || '-' }}</div>
                        <div><span class="item-label">缩略图地址</span>{{ r.thumbnail_url || '-' }}</div>
                      </div>

                      <div style="margin-top:10px">
                        <a-button
                          size="small"
                          type="primary"
                          :loading="launchingPacs === r.record_id"
                          @click="launchFromPacs(r)"
                        >发起 AI 分析</a-button>
                      </div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>

              <a-tab-pane key="ai" :tab="`AI任务 (${cvTasks.length})`">
                <div class="tab-body">
                  <div v-if="!cvTasks.length" class="empty-inline">暂无 AI 分析任务</div>
                  <div v-for="r in cvTasks" :key="r.id" class="detail-item-card">
                    <div class="item-head">
                      <span class="item-title">任务 #{{ r.id }}</span>
                      <a-tag
                          :color="r.status === 'done' ? 'green' : r.status === 'failed' ? 'red' : 'orange'"
                          style="margin: 0"
                      >
                        {{ r.status || '-' }}
                      </a-tag>
                    </div>
                    <div class="item-grid single-col">
                      <div><span class="item-label">创建时间</span>{{ formatDate(r.created_at) }}</div>
                    </div>
                  </div>
                </div>
              </a-tab-pane>
            </a-tabs>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.integration-page {
  height: calc(100vh - 64px);
  padding: 20px 20px 16px;
  background: #f5f7fb;
  overflow: hidden;
  box-sizing: border-box;
}

.page-header {
  margin-bottom: 16px;
}

.page-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  border-left: 3px solid #14b8a6;
  padding-left: 10px;
  line-height: 1.3;
}

.page-subtitle {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  padding-left: 13px;
}

.top-summary-card {
  background: #fff;
  border-radius: 14px;
  padding: 14px 18px;
  margin-bottom: 18px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.summary-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.summary-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.summary-tag {
  margin: 0;
  font-size: 11px;
}

.summary-count {
  font-size: 13px;
  color: #475569;
}

.summary-right {
  font-size: 14px;
  font-weight: 600;
  color: #059669;
  white-space: nowrap;
}

.workspace {
  height: calc(100% - 94px);
  display: flex;
  gap: 18px;
  min-height: 0;
}

.left-panel {
  width: 58%;
  min-width: 560px;
  display: flex;
  min-height: 0;
}

.right-panel {
  width: 42%;
  min-width: 420px;
  display: flex;
  min-height: 0;
}

.panel-card {
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
}

.panel-fill {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.panel-header {
  padding: 16px 18px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.search-wrap {
  padding: 0 18px 12px;
}

.table-wrap {
  padding: 0 14px 14px;
}

.source-id-cell {
  display: inline-block;
  max-width: 160px;
  word-break: break-word;
  line-height: 1.4;
}

.internal-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.internal-name {
  color: #059669;
  font-size: 12px;
  font-weight: 600;
}

.view-btn {
  font-size: 11px;
  height: 24px;
  padding: 0 8px;
  line-height: 24px;
}

.unmatched-text {
  color: #94a3b8;
  font-size: 11px;
}

.right-content {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.patient-summary-card {
  padding: 16px 18px 12px;
}

.summary-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}

.summary-main {
  flex: 1;
  min-width: 0;
}

.patient-name-line {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.patient-name {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.patient-id {
  font-size: 13px;
  color: #64748b;
}

.patient-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
  color: #475569;
}

.meta-label {
  color: #94a3b8;
  margin-right: 6px;
}

.source-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 280px;
}

.source-map-tag {
  margin: 0;
}

.detail-card {
  flex: 1;
  min-height: 0;
  padding: 0 16px 14px;
  overflow: hidden;
}

.detail-tabs {
  height: 100%;
}

.detail-tabs :deep(.ant-tabs-content-holder) {
  height: calc(100% - 48px);
  overflow: hidden;
}

.detail-tabs :deep(.ant-tabs-content) {
  height: 100%;
}

.detail-tabs :deep(.ant-tabs-tabpane) {
  height: 100%;
}

.tab-body {
  height: 100%;
  overflow-y: auto;
  padding-top: 8px;
  padding-right: 4px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.overview-stat {
  border-radius: 12px;
  padding: 14px 12px;
  text-align: center;
}

.stat-his {
  background: #f0fdf4;
}

.stat-lis {
  background: #fffbeb;
}

.stat-pacs {
  background: #eff6ff;
}

.stat-ai {
  background: #faf5ff;
}

.stat-number {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 6px;
}

.stat-his .stat-number {
  color: #10b981;
}

.stat-lis .stat-number {
  color: #f59e0b;
}

.stat-pacs .stat-number {
  color: #2563eb;
}

.stat-ai .stat-number {
  color: #7c3aed;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
  margin: 16px 0 10px;
}

.mapping-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 10px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #475569;
}

.mapping-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.mapping-id {
  font-weight: 500;
}

.mapping-sep {
  color: #94a3b8;
}

.mapping-name {
  color: #64748b;
}

.mapping-time {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
}

.detail-item-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
}

.item-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.item-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.item-time {
  font-size: 12px;
  color: #94a3b8;
}

.item-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: 13px;
  color: #475569;
}

.item-grid.single-col {
  grid-template-columns: 1fr;
}

.item-label {
  color: #94a3b8;
  margin-right: 6px;
}

.pacs-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.pacs-thumb-wrap {
  flex-shrink: 0;
}

.pacs-thumb {
  width: 80px;
  height: 80px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.pacs-thumb-empty {
  width: 80px;
  height: 80px;
  border-radius: 10px;
  border: 1px dashed #dbe2ea;
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 11px;
}

.pacs-main {
  flex: 1;
  min-width: 0;
}

.pacs-desc {
  font-size: 13px;
  color: #475569;
  margin-bottom: 10px;
  line-height: 1.5;
}

.link-block {
  font-size: 12px;
  color: #64748b;
  word-break: break-all;
  display: grid;
  gap: 6px;
}

.empty-state,
.loading-state,
.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state {
  flex-direction: column;
  text-align: center;
  color: #94a3b8;
  padding: 24px;
}

.empty-icon {
  font-size: 34px;
  margin-bottom: 10px;
}

.empty-title {
  font-size: 15px;
  color: #64748b;
  font-weight: 600;
  margin-bottom: 6px;
}

.empty-desc {
  font-size: 13px;
  color: #94a3b8;
  max-width: 320px;
  line-height: 1.6;
}

.error-state {
  color: #ef4444;
  font-size: 13px;
}

.empty-inline {
  color: #94a3b8;
  font-size: 13px;
  padding: 12px 0;
}

:deep(.selected-row) {
  background: #f0fdf4 !important;
}

:deep(.ant-table-tbody > .selected-row:hover > td) {
  background: #dcfce7 !important;
}

:deep(.ant-table-small .ant-table-thead > tr > th) {
  font-weight: 700;
}

:deep(.ant-table-cell) {
  vertical-align: middle;
}

@media (max-width: 1440px) {
  .left-panel {
    width: 56%;
    min-width: 520px;
  }

  .right-panel {
    width: 44%;
    min-width: 400px;
  }
}
</style>
