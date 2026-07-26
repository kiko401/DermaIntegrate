<script setup>
import { ref, onMounted } from 'vue'

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, { credentials: 'include', ...opts })
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await res.json() : null
  return { ok: res.ok, status: res.status, data }
}

// ── 统计 ──────────────────────────────────────────────────────────────
const stats = ref(null)
const statsLoading = ref(false)

async function loadStats() {
  statsLoading.value = true
  try {
    const q = buildStatsQuery()
    const { ok, data } = await apiFetch(`/api/rag/logs/stats${q}`)
    if (ok) stats.value = data
  } finally {
    statsLoading.value = false
  }
}

function buildStatsQuery() {
  const p = new URLSearchParams()
  if (filter.value.start_date) p.set('start_date', filter.value.start_date)
  if (filter.value.end_date) p.set('end_date', filter.value.end_date)
  if (filter.value.kb_id) p.set('kb_id', filter.value.kb_id)
  const s = p.toString()
  return s ? '?' + s : ''
}

// ── 日志列表 ──────────────────────────────────────────────────────────
const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const logsLoading = ref(false)
const logsError = ref('')

const filter = ref({
  log_type: '',
  doctor_id: '',
  kb_id: '',
  start_date: '',
  end_date: '',
  keyword: '',
})

async function loadLogs() {
  logsLoading.value = true
  logsError.value = ''
  try {
    const p = new URLSearchParams()
    p.set('page', page.value)
    p.set('pageSize', pageSize.value)
    if (filter.value.log_type) p.set('log_type', filter.value.log_type)
    if (filter.value.doctor_id) p.set('doctor_id', filter.value.doctor_id)
    if (filter.value.kb_id) p.set('kb_id', filter.value.kb_id)
    if (filter.value.start_date) p.set('start_date', filter.value.start_date)
    if (filter.value.end_date) p.set('end_date', filter.value.end_date)
    if (filter.value.keyword) p.set('keyword', filter.value.keyword)

    const { ok, data } = await apiFetch(`/api/rag/logs?${p.toString()}`)
    if (!ok) { logsError.value = data?.message || '加载失败'; return }
    logs.value = Array.isArray(data?.data) ? data.data : []
    total.value = data?.total || 0
  } catch (e) {
    logsError.value = e.message
  } finally {
    logsLoading.value = false
  }
}

function applyFilter() {
  page.value = 1
  loadLogs()
  loadStats()
}

function resetFilter() {
  filter.value = { log_type: '', doctor_id: '', kb_id: '', start_date: '', end_date: '', keyword: '' }
  applyFilter()
}

function prevPage() { if (page.value > 1) { page.value--; loadLogs() } }
function nextPage() { if (page.value * pageSize.value < total.value) { page.value++; loadLogs() } }
const totalPages = () => Math.max(1, Math.ceil(total.value / pageSize.value))

// ── 导出 ──────────────────────────────────────────────────────────────
const exportLoading = ref(false)
const exportFormat = ref('csv')

async function exportLogs() {
  exportLoading.value = true
  try {
    const body = {
      format: exportFormat.value,
      ...(filter.value.start_date && { start_date: filter.value.start_date }),
      ...(filter.value.end_date && { end_date: filter.value.end_date }),
      ...(filter.value.kb_id && { kb_id: Number(filter.value.kb_id) }),
    }
    const res = await fetch('/api/rag/logs/export', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) { alert('导出失败'); return }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const name = cd.match(/filename="([^"]+)"/)?.[1]
      || `rag_logs.${exportFormat.value === 'excel' ? 'xlsx' : 'csv'}`
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = name; a.click()
    URL.revokeObjectURL(url)
  } finally {
    exportLoading.value = false
  }
}

// ── 反馈导出 ──────────────────────────────────────────────────────────
const fbExportLoading = ref(false)

async function exportFeedback() {
  fbExportLoading.value = true
  try {
    const body = {
      ...(filter.value.start_date && { start_date: filter.value.start_date }),
      ...(filter.value.end_date && { end_date: filter.value.end_date }),
      format: 'jsonl',
    }
    const res = await fetch('/api/rag/feedback/export', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) { alert('反馈导出失败（AI 域可能未启动）'); return }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const name = cd.match(/filename="([^"]+)"/)?.[1] || 'feedback_export.jsonl'
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = name; a.click()
    URL.revokeObjectURL(url)
  } finally {
    fbExportLoading.value = false
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────
const LOG_TYPE_LABELS = {
  chat: '对话', ingest: '入库', api: 'API', tool: '工具',
  agent: 'Agent', guardrail: '安全', etl: 'ETL',
}
function logTypeLabel(t) { return LOG_TYPE_LABELS[t] || t }
const STATUS_CLASS = { success: 'status-success', blocked: 'status-blocked', failed: 'status-failed' }
function statusClass(s) { return STATUS_CLASS[s] || '' }
function fmtTime(v) {
  if (!v) return '—'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}
function fmtKbIds(v) {
  if (!v) return '—'
  const arr = typeof v === 'string' ? JSON.parse(v) : v
  return Array.isArray(arr) ? arr.join(', ') : String(v)
}

onMounted(() => { loadLogs(); loadStats() })
</script>

<template>
  <div class="logs-page">
    <div class="page-header">
      <h2 class="page-title">对话日志</h2>
      <div class="header-actions">
        <select v-model="exportFormat" class="export-fmt-select">
          <option value="csv">CSV</option>
          <option value="excel">Excel</option>
        </select>
        <button class="btn btn-secondary" :disabled="exportLoading" @click="exportLogs">
          {{ exportLoading ? '导出中...' : '导出日志' }}
        </button>
        <button class="btn btn-secondary" :disabled="fbExportLoading" @click="exportFeedback">
          {{ fbExportLoading ? '导出中...' : '导出反馈(JSONL)' }}
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div v-if="stats" class="stats-row">
      <div class="stat-card">
        <div class="stat-label">总问答次数</div>
        <div class="stat-value">{{ stats.total_queries.toLocaleString() }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">成功率</div>
        <div class="stat-value success">{{ (stats.success_rate * 100).toFixed(1) }}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">阻断率</div>
        <div class="stat-value blocked">{{ (stats.blocked_rate * 100).toFixed(1) }}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">平均耗时</div>
        <div class="stat-value">{{ stats.avg_latency_ms }} ms</div>
      </div>
    </div>

    <!-- 热门问题 -->
    <div v-if="stats?.top_questions?.length" class="top-questions">
      <div class="section-title">热门问题 Top 10</div>
      <div class="tq-list">
        <div v-for="(q, i) in stats.top_questions" :key="i" class="tq-item">
          <span class="tq-rank">{{ i + 1 }}</span>
          <span class="tq-text">{{ q.question }}</span>
          <span class="tq-count">{{ q.count }} 次</span>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filter.log_type" class="filter-input filter-select">
        <option value="">全部类型</option>
        <option v-for="(label, key) in LOG_TYPE_LABELS" :key="key" :value="key">{{ label }}</option>
      </select>
      <input v-model="filter.start_date" type="date" class="filter-input" />
      <input v-model="filter.end_date" type="date" class="filter-input" />
      <input v-model="filter.doctor_id" type="number" class="filter-input" placeholder="用户 ID" style="width:100px" />
      <input v-model="filter.kb_id" type="number" class="filter-input" placeholder="知识库 ID" style="width:100px" />
      <input v-model="filter.keyword" type="text" class="filter-input" placeholder="关键词搜索" style="width:160px" />
      <button class="btn btn-primary" @click="applyFilter">查询</button>
      <button class="btn btn-ghost" @click="resetFilter">重置</button>
    </div>

    <div v-if="logsError" class="error-msg">{{ logsError }}</div>

    <!-- 日志表格 -->
    <div class="table-wrap">
      <table class="logs-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>用户</th>
            <th>会话</th>
            <th>知识库</th>
            <th>问题摘要</th>
            <th>回答摘要</th>
            <th>耗时(ms)</th>
            <th>状态</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="logsLoading">
            <td colspan="10" class="td-center">加载中...</td>
          </tr>
          <tr v-else-if="!logs.length">
            <td colspan="10" class="td-center td-empty">暂无日志数据</td>
          </tr>
          <tr v-for="log in logs" :key="log.id">
            <td>{{ log.id }}</td>
            <td><span class="type-tag">{{ logTypeLabel(log.log_type) }}</span></td>
            <td>{{ log.doctor_id || '—' }}</td>
            <td>{{ log.conversation_id || '—' }}</td>
            <td>{{ fmtKbIds(log.kb_ids) }}</td>
            <td class="td-summary" :title="log.request_summary">{{ log.request_summary || '—' }}</td>
            <td class="td-summary" :title="log.response_summary">{{ log.response_summary || '—' }}</td>
            <td>{{ log.latency_ms ?? '—' }}</td>
            <td><span :class="['status-badge', statusClass(log.status)]">{{ log.status }}</span></td>
            <td class="td-time">{{ fmtTime(log.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div class="pagination">
      <span class="page-info">共 {{ total }} 条 / 第 {{ page }} / {{ totalPages() }} 页</span>
      <button class="btn btn-ghost" :disabled="page <= 1" @click="prevPage">上一页</button>
      <button class="btn btn-ghost" :disabled="page * pageSize >= total" @click="nextPage">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.logs-page { padding: 24px; max-width: 1400px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-size: 18px; font-weight: 600; color: #1e293b; margin: 0; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.stats-row { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.stat-card { flex: 1; min-width: 160px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; }
.stat-label { font-size: 12px; color: #64748b; margin-bottom: 6px; }
.stat-value { font-size: 24px; font-weight: 700; color: #1e293b; }
.stat-value.success { color: #16a34a; }
.stat-value.blocked { color: #dc2626; }
.top-questions { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 20px; }
.section-title { font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 10px; }
.tq-list { display: flex; flex-direction: column; gap: 6px; }
.tq-item { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.tq-rank { width: 24px; height: 24px; border-radius: 50%; background: #e2e8f0; color: #475569; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.tq-text { flex: 1; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tq-count { font-size: 12px; color: #64748b; flex-shrink: 0; }
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; align-items: center; }
.filter-input { height: 32px; padding: 0 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; color: #334155; background: #fff; }
.filter-input:focus { outline: none; border-color: #2563eb; }
.filter-select { min-width: 100px; }
.export-fmt-select { height: 32px; padding: 0 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; }
.btn { height: 32px; padding: 0 14px; border-radius: 6px; font-size: 13px; cursor: pointer; border: none; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-secondary { background: #fff; color: #475569; border: 1px solid #cbd5e1; }
.btn-secondary:hover:not(:disabled) { background: #f8fafc; }
.btn-ghost { background: transparent; color: #64748b; border: 1px solid #e2e8f0; }
.btn-ghost:hover:not(:disabled) { background: #f8fafc; }
.table-wrap { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
.logs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.logs-table th { background: #f8fafc; padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.logs-table td { padding: 9px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: top; }
.logs-table tr:last-child td { border-bottom: none; }
.logs-table tr:hover td { background: #f8fafc; }
.td-center { text-align: center; color: #94a3b8; }
.td-empty { padding: 32px !important; }
.td-summary { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td-time { white-space: nowrap; font-size: 12px; color: #64748b; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.status-success { background: #dcfce7; color: #16a34a; }
.status-blocked { background: #fef3c7; color: #d97706; }
.status-failed { background: #fee2e2; color: #dc2626; }
.type-tag { background: #eff6ff; color: #2563eb; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.pagination { display: flex; align-items: center; gap: 8px; margin-top: 16px; }
.page-info { font-size: 13px; color: #64748b; flex: 1; }
.error-msg { background: #fee2e2; color: #dc2626; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; }
</style>
