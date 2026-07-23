<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts }).then(r => r.json())

// ── 任务列表状态 ─────────────────────────────────────────────
const tasks    = ref([])
const kbs      = ref([])
const loading  = ref(false)
const total    = ref(0)
const page     = ref(1)
const pageSize = ref(20)

const filterType   = ref('')
const filterStatus = ref('')
const filterKb     = ref('')
const filterDocId  = ref('')

// SSE 订阅状态：taskId -> { es, stage, progress, message, chunkCount, error }
const liveMap = ref({})

const taskTypeLabels = {
  ingest:        'Ingest',
  reindex:       'Reindex',
  delete_index:  '删除索引',
  clone_kb:      '克隆知识库',
  etl_ingest:    'ETL Ingest',
  agent_prepare: 'Agent 准备',
}
const statusLabels = {
  pending:   '等待中',
  running:   '运行中',
  succeeded: '已完成',
  failed:    '失败',
  cancelled: '已取消',
}

// ── 向量优化面板状态 ─────────────────────────────────────────
const optimizePanel    = ref(false)
const optimizeKbId     = ref('')
const optimizeOpts     = ref({ remove_duplicates: true, rebuild_bm25_idf: false, compact_collection: false })
const optimizeLoading  = ref(false)
const optimizeResult   = ref(null)
const optimizeError    = ref('')

// ── 手动触发重建状态 ─────────────────────────────────────────
const rebuildPanel     = ref(false)
const rebuildKbId      = ref('')
const rebuildDocId     = ref('')
const rebuildLoading   = ref(false)
const rebuildResult    = ref(null)
const rebuildError     = ref('')

// ── 生命周期 ─────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([fetchTasks(), fetchKbs()])
})
onUnmounted(() => {
  Object.values(liveMap.value).forEach(v => v.es?.close())
})

// ── 任务列表 ─────────────────────────────────────────────────
async function fetchTasks(targetPage = page.value) {
  loading.value = true
  const params = new URLSearchParams()
  if (filterType.value)   params.set('task_type', filterType.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  if (filterKb.value)     params.set('kb_id', filterKb.value)
  if (filterDocId.value && /^\d+$/.test(filterDocId.value.trim()))
    params.set('doc_id', filterDocId.value.trim())
  params.set('page', String(targetPage))
  params.set('pageSize', String(pageSize.value))
  const data = await API(`/api/rag/tasks?${params}`)
  tasks.value = Array.isArray(data?.data) ? data.data : []
  total.value = data?.total ?? 0
  page.value  = data?.page  ?? targetPage
  loading.value = false
}

async function fetchKbs() {
  const data = await API('/api/rag/kbs')
  kbs.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
}

function onFilterChange() {
  page.value = 1
  fetchTasks(1)
}

const totalPages = computed(() => Math.ceil(total.value / pageSize.value) || 1)

// ── SSE 订阅 ─────────────────────────────────────────────────
function subscribeTask(task) {
  const id = task.id
  if (liveMap.value[id]) {
    liveMap.value[id].es.close()
    delete liveMap.value[id]
    return
  }
  const es = new EventSource(`/api/rag/tasks/${id}/stream`)
  liveMap.value[id] = {
    es,
    stage: task.status === 'pending' ? 'queued' : '',
    progress: Number(task.progress_percent) || 0,
    message: '',
    chunkCount: null,
    error: '',
  }

  es.addEventListener('progress', e => {
    const d = JSON.parse(e.data)
    liveMap.value[id].stage    = d.stage    || ''
    liveMap.value[id].progress = d.progress || 0
    liveMap.value[id].message  = d.message  || ''
  })
  es.addEventListener('done', e => {
    const d = JSON.parse(e.data)
    const live = liveMap.value[id]
    if (live) {
      live.chunkCount = d.chunk_count ?? 0
      live.stage = 'done'
      live.progress = 100
    }
    es.close()
    const t = tasks.value.find(t => t.id === id)
    if (t) { t.status = 'succeeded'; t.result_json = { chunk_count: d.chunk_count ?? 0 } }
    delete liveMap.value[id]
  })
  es.addEventListener('error', e => {
    if (!e.data) return
    try {
      const d = JSON.parse(e.data)
      if (liveMap.value[id]) liveMap.value[id].error = d.message || '任务失败'
    } catch (_) {}
    if (liveMap.value[id]) liveMap.value[id].stage = 'error'
    es.close()
    const t = tasks.value.find(t => t.id === id)
    if (t) t.status = 'failed'
    delete liveMap.value[id]
  })
}

// ── 辅助展示 ─────────────────────────────────────────────────
function kbName(kbId) {
  return kbs.value.find(k => k.id === kbId)?.name || (kbId ? `KB#${kbId}` : '-')
}
function chunkCount(task) {
  const live = liveMap.value[task.id]
  if (live?.chunkCount != null) return live.chunkCount
  const rj = typeof task.result_json === 'string'
    ? (() => { try { return JSON.parse(task.result_json) } catch { return null } })()
    : task.result_json
  return rj?.chunk_count ?? '-'
}
function displayStatus(task) {
  const live = liveMap.value[task.id]
  if (!live) return task.status
  if (live.stage === 'done')  return 'succeeded'
  if (live.stage === 'error') return 'failed'
  return task.status
}
function fmtDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN', { hour12: false })
}
const stageCN = {
  parsing: '解析', splitting: '切分', embedding: '向量化',
  indexing: '写入索引', dense_embedding: '向量化',
  bm25_fitting: '关键词索引', preparing_payload: '准备写入',
}
function stageLabel(s) { return stageCN[s] || s }

// ── 向量优化 ─────────────────────────────────────────────────
async function runOptimize() {
  if (!optimizeKbId.value) { optimizeError.value = '请选择知识库'; return }
  optimizeLoading.value = true
  optimizeResult.value  = null
  optimizeError.value   = ''
  try {
    const res = await fetch('/api/rag/admin/vector-optimize', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kb_id: Number(optimizeKbId.value),
        remove_duplicates:  optimizeOpts.value.remove_duplicates,
        rebuild_bm25_idf:   optimizeOpts.value.rebuild_bm25_idf,
        compact_collection: optimizeOpts.value.compact_collection,
      }),
    })
    const data = await res.json()
    if (!res.ok) { optimizeError.value = data?.detail || data?.error || `请求失败 ${res.status}`; return }
    optimizeResult.value = data
  } catch (e) {
    optimizeError.value = e.message
  } finally {
    optimizeLoading.value = false
  }
}

// ── 手动重建索引 ──────────────────────────────────────────────
async function runRebuild() {
  const docId = rebuildDocId.value.trim()
  if (!rebuildKbId.value) { rebuildError.value = '请选择知识库'; return }
  if (!docId || !/^\d+$/.test(docId)) { rebuildError.value = '请输入有效的文档 ID（整数）'; return }
  rebuildLoading.value = true
  rebuildResult.value  = null
  rebuildError.value   = ''
  try {
    const res = await fetch(`/api/rag/documents/${docId}/reindex`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kb_id: Number(rebuildKbId.value) }),
    })
    const data = await res.json()
    if (!res.ok) { rebuildError.value = data?.error || data?.message || `请求失败 ${res.status}`; return }
    rebuildResult.value = data
    await fetchTasks(1)
  } catch (e) {
    rebuildError.value = e.message
  } finally {
    rebuildLoading.value = false
  }
}
</script>

<template>
  <div class="page">
    <!-- ── 页头 ── -->
    <div class="page-header">
      <h2 class="page-title">向量与任务管理</h2>
      <div class="header-actions">
        <button class="btn-outline" @click="rebuildPanel = !rebuildPanel">
          {{ rebuildPanel ? '收起重建' : '手动重建索引' }}
        </button>
        <button class="btn-outline" @click="optimizePanel = !optimizePanel">
          {{ optimizePanel ? '收起优化' : '向量优化' }}
        </button>
        <button class="btn-primary" :disabled="loading" @click="fetchTasks()">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- ── 手动重建面板 ── -->
    <div v-if="rebuildPanel" class="action-panel">
      <div class="panel-title">手动触发重建索引</div>
      <div class="panel-row">
        <select v-model="rebuildKbId" class="field-input field-input-sm">
          <option value="">选择知识库</option>
          <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
        </select>
        <input
          v-model="rebuildDocId"
          class="field-input field-input-sm"
          placeholder="文档 ID（整数）"
          style="width:160px"
        />
        <button class="btn-primary" :disabled="rebuildLoading" @click="runRebuild">
          {{ rebuildLoading ? '提交中...' : '触发重建' }}
        </button>
      </div>
      <div v-if="rebuildError" class="panel-error">{{ rebuildError }}</div>
      <div v-if="rebuildResult" class="panel-result">
        已创建任务：{{ rebuildResult.task_code || rebuildResult.id || JSON.stringify(rebuildResult) }}
      </div>
    </div>

    <!-- ── 向量优化面板 ── -->
    <div v-if="optimizePanel" class="action-panel">
      <div class="panel-title">向量优化</div>
      <div class="panel-row">
        <select v-model="optimizeKbId" class="field-input field-input-sm">
          <option value="">选择知识库</option>
          <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
        </select>
        <label class="opt-check"><input type="checkbox" v-model="optimizeOpts.remove_duplicates" /> 去重 chunk</label>
        <label class="opt-check"><input type="checkbox" v-model="optimizeOpts.rebuild_bm25_idf" /> 重建 BM25 IDF</label>
        <label class="opt-check"><input type="checkbox" v-model="optimizeOpts.compact_collection" /> Qdrant 整理</label>
        <button class="btn-primary" :disabled="optimizeLoading" @click="runOptimize">
          {{ optimizeLoading ? '执行中...' : '执行优化' }}
        </button>
      </div>
      <div v-if="optimizeError" class="panel-error">{{ optimizeError }}</div>
      <div v-if="optimizeResult" class="panel-result optimize-result">
        <span>总 chunks：{{ optimizeResult.total_chunks }}</span>
        <span>检测重复：{{ optimizeResult.duplicate_chunks }}</span>
        <span>已删除：{{ optimizeResult.removed_duplicates }}</span>
        <span>IDF terms 更新：{{ optimizeResult.idf_terms_updated }}</span>
        <span>Qdrant 整理：{{ optimizeResult.optimizer_applied ? '已触发' : '未触发' }}</span>
      </div>
    </div>

    <!-- ── 筛选栏 ── -->
    <div class="filter-bar">
      <select v-model="filterType" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部类型</option>
        <option v-for="(label, val) in taskTypeLabels" :key="val" :value="val">{{ label }}</option>
      </select>
      <select v-model="filterStatus" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部状态</option>
        <option v-for="(label, val) in statusLabels" :key="val" :value="val">{{ label }}</option>
      </select>
      <select v-model="filterKb" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部知识库</option>
        <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
      </select>
      <input
        v-model="filterDocId"
        class="field-input field-input-sm"
        placeholder="Doc ID"
        style="width:100px"
        @keydown.enter="onFilterChange"
        @blur="onFilterChange"
      />
      <span class="total-tip" v-if="!loading">共 {{ total }} 条</span>
    </div>

    <!-- ── 列表 ── -->
    <div v-if="loading" class="empty-tip">加载中...</div>
    <div v-else-if="!tasks.length" class="empty-tip">暂无任务</div>

    <table v-else class="task-table">
      <thead>
        <tr>
          <th>Task ID</th>
          <th>Task Code</th>
          <th>Doc ID</th>
          <th>Version ID</th>
          <th>类型</th>
          <th>知识库</th>
          <th>状态</th>
          <th>Chunks</th>
          <th>错误信息</th>
          <th>创建时间</th>
          <th>实时进度</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.id">
          <td class="id-cell">#{{ task.id }}</td>
          <td class="code-cell" :title="task.task_code">{{ task.task_code }}</td>
          <td class="id-cell">{{ task.doc_id ? `#${task.doc_id}` : '-' }}</td>
          <td class="id-cell">{{ task.doc_version_id ? `#${task.doc_version_id}` : '-' }}</td>
          <td><span class="type-badge">{{ taskTypeLabels[task.task_type] || task.task_type }}</span></td>
          <td>{{ kbName(task.kb_id) }}</td>
          <td>
            <div class="status-wrap">
              <template v-if="liveMap[task.id]">
                <div class="progress-bar-wrap">
                  <div class="progress-bar" :style="{ width: liveMap[task.id].progress + '%' }"></div>
                </div>
                <span class="progress-label">
                  {{ stageLabel(liveMap[task.id].stage || task.status) }} {{ liveMap[task.id].progress }}%
                </span>
                <span v-if="liveMap[task.id].message" class="progress-message">
                  {{ liveMap[task.id].message }}
                </span>
              </template>
              <span v-else class="status-badge" :class="displayStatus(task)">
                {{ statusLabels[displayStatus(task)] || displayStatus(task) }}
              </span>
            </div>
          </td>
          <td class="num-cell">{{ chunkCount(task) }}</td>
          <td class="err-cell" :title="liveMap[task.id]?.error || task.error_message">
            {{ liveMap[task.id]?.error || task.error_message || '-' }}
          </td>
          <td class="date-cell">{{ fmtDate(task.created_at) }}</td>
          <td>
            <button
              v-if="task.status === 'pending' || task.status === 'running'"
              class="btn-sm"
              :class="{ 'btn-active': !!liveMap[task.id] }"
              @click="subscribeTask(task)"
            >
              {{ liveMap[task.id] ? '取消订阅' : '订阅进度' }}
            </button>
            <span v-else class="na-text">-</span>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- ── 分页 ── -->
    <div v-if="totalPages > 1" class="pagination">
      <button class="btn-sm" :disabled="page <= 1" @click="fetchTasks(page - 1)">上一页</button>
      <span class="page-info">{{ page }} / {{ totalPages }}</span>
      <button class="btn-sm" :disabled="page >= totalPages" @click="fetchTasks(page + 1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }
.header-actions { display: flex; gap: 8px; }

/* 操作面板 */
.action-panel { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.panel-title { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 10px; }
.panel-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.panel-error { margin-top: 8px; font-size: 13px; color: #dc2626; }
.panel-result { margin-top: 8px; font-size: 13px; color: #166534; }
.optimize-result { display: flex; gap: 16px; flex-wrap: wrap; }
.opt-check { display: flex; align-items: center; gap: 4px; font-size: 13px; color: #475569; cursor: pointer; white-space: nowrap; }
.opt-check input { cursor: pointer; }

/* 筛选栏 */
.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; align-items: center; }
.filter-bar .field-input { width: auto; min-width: 130px; }
.total-tip { font-size: 13px; color: #94a3b8; }

.empty-tip { text-align: center; padding: 60px; color: #94a3b8; font-size: 14px; }

.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 12px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
.task-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.task-table tr:hover td { background: #f8fafc; }

.id-cell { white-space: nowrap; color: #64748b; font-size: 12px; font-variant-numeric: tabular-nums; }
.code-cell { font-family: monospace; font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #64748b; }
.num-cell  { text-align: right; font-variant-numeric: tabular-nums; }
.date-cell { white-space: nowrap; color: #64748b; font-size: 12px; }
.err-cell  { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #dc2626; font-size: 12px; }
.na-text   { color: #cbd5e1; font-size: 12px; }

.type-badge { font-size: 11px; padding: 2px 7px; border-radius: 10px; background: #f1f5f9; color: #475569; }

.status-wrap { display: flex; flex-direction: column; gap: 3px; min-width: 90px; }
.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; display: inline-block; width: fit-content; }
.status-badge.pending   { background: #f1f5f9; color: #64748b; }
.status-badge.running   { background: #fef3c7; color: #92400e; }
.status-badge.succeeded { background: #f0fdf4; color: #166534; }
.status-badge.failed    { background: #fef2f2; color: #dc2626; }
.status-badge.cancelled { background: #f8fafc; color: #94a3b8; }

.progress-bar-wrap { width: 100%; max-width: 120px; height: 4px; background: #e2e8f0; border-radius: 2px; overflow: hidden; }
.progress-bar { height: 100%; background: #2563eb; transition: width 0.3s; }
.progress-label { font-size: 11px; color: #64748b; }
.progress-message { font-size: 11px; color: #94a3b8; line-height: 1.35; }

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; white-space: nowrap; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-outline { padding: 6px 14px; background: #fff; color: #475569; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; cursor: pointer; white-space: nowrap; }
.btn-outline:hover { background: #f8fafc; border-color: #cbd5e1; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; }
.btn-sm:hover:not(:disabled) { background: #f8fafc; }
.btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-active { border-color: #2563eb; color: #2563eb; background: #eff6ff; }

.pagination { display: flex; align-items: center; gap: 10px; justify-content: center; margin-top: 20px; }
.page-info { font-size: 13px; color: #64748b; }

.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.field-input-sm { padding: 6px 10px; font-size: 13px; }
</style>
