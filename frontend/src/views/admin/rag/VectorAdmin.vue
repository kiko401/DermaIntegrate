<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts }).then(r => r.json())

const tasks   = ref([])
const kbs     = ref([])
const loading = ref(false)

const filterType   = ref('')
const filterStatus = ref('')
const filterKb     = ref('')

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

onMounted(async () => {
  await Promise.all([fetchTasks(), fetchKbs()])
})

onUnmounted(() => {
  Object.values(liveMap.value).forEach(v => v.es?.close())
})

async function fetchTasks() {
  loading.value = true
  const params = new URLSearchParams()
  if (filterType.value)   params.set('task_type', filterType.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  if (filterKb.value)     params.set('kb_id', filterKb.value)
  const data = await API(`/api/rag/tasks?${params}`)
  tasks.value = Array.isArray(data) ? data : []
  loading.value = false
}

async function fetchKbs() {
  const data = await API('/api/rag/kbs')
  kbs.value = Array.isArray(data) ? data : []
}

// 订阅单个任务的 SSE 进度流（再次点击则取消）
function subscribeTask(task) {
  const id = task.id
  if (liveMap.value[id]) {
    liveMap.value[id].es.close()
    delete liveMap.value[id]
    return
  }

  const es = new EventSource(`/api/rag/tasks/${id}/stream`)
  liveMap.value[id] = { es, stage: '', progress: 0, message: '', chunkCount: null, error: '' }

  es.addEventListener('progress', e => {
    const d = JSON.parse(e.data)
    liveMap.value[id].stage    = d.stage    || ''
    liveMap.value[id].progress = d.progress || 0
    liveMap.value[id].message  = d.message  || ''
  })

  es.addEventListener('done', e => {
    const d = JSON.parse(e.data)
    liveMap.value[id].chunkCount = d.chunk_count ?? 0
    liveMap.value[id].stage      = 'done'
    es.close()
    const t = tasks.value.find(t => t.id === id)
    if (t) {
      t.status = 'succeeded'
      t.result_json = { chunk_count: d.chunk_count ?? 0 }
    }
  })

  es.addEventListener('error', e => {
    // e.data 为 undefined 时是 EventSource 网络层重试事件，不是业务错误，忽略
    if (!e.data) return
    try {
      const d = JSON.parse(e.data)
      liveMap.value[id].error = d.message || '任务失败'
    } catch (_) {}
    liveMap.value[id].stage = 'error'
    es.close()
    const t = tasks.value.find(t => t.id === id)
    if (t) t.status = 'failed'
  })
}

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

// 计算显示状态：live 覆盖列表状态
function displayStatus(task) {
  const live = liveMap.value[task.id]
  if (!live) return task.status
  if (live.stage === 'done')  return 'succeeded'
  if (live.stage === 'error') return 'failed'
  return task.status
}

const filteredTasks = computed(() => tasks.value)

function fmtDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN', { hour12: false })
}

const stageCN = { parsing: '解析', splitting: '切分', embedding: '向量化', indexing: '写入索引' }
function stageLabel(s) { return stageCN[s] || s }
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">向量与任务管理</h2>
      <button class="btn-primary" :disabled="loading" @click="fetchTasks">
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <div class="filter-bar">
      <select v-model="filterType" class="field-input field-input-sm" @change="fetchTasks">
        <option value="">全部类型</option>
        <option v-for="(label, val) in taskTypeLabels" :key="val" :value="val">{{ label }}</option>
      </select>
      <select v-model="filterStatus" class="field-input field-input-sm" @change="fetchTasks">
        <option value="">全部状态</option>
        <option v-for="(label, val) in statusLabels" :key="val" :value="val">{{ label }}</option>
      </select>
      <select v-model="filterKb" class="field-input field-input-sm" @change="fetchTasks">
        <option value="">全部知识库</option>
        <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <div v-else-if="!filteredTasks.length" class="empty-tip">暂无任务</div>

    <table v-else class="task-table">
      <thead>
        <tr>
          <th>Task Code</th>
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
        <tr v-for="task in filteredTasks" :key="task.id">
          <td class="code-cell" :title="task.task_code">{{ task.task_code }}</td>
          <td>
            <span class="type-badge">{{ taskTypeLabels[task.task_type] || task.task_type }}</span>
          </td>
          <td>{{ kbName(task.kb_id) }}</td>
          <td>
            <div class="status-wrap">
              <span class="status-badge" :class="displayStatus(task)">
                {{ statusLabels[displayStatus(task)] || displayStatus(task) }}
              </span>
              <template v-if="liveMap[task.id]?.stage && !['done','error',''].includes(liveMap[task.id].stage)">
                <div class="progress-bar-wrap">
                  <div class="progress-bar" :style="{ width: liveMap[task.id].progress + '%' }"></div>
                </div>
                <span class="progress-label">
                  {{ stageLabel(liveMap[task.id].stage) }} {{ liveMap[task.id].progress }}%
                </span>
              </template>
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
  </div>
</template>

<style scoped>
.page { padding: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }
.filter-bar .field-input { width: auto; min-width: 150px; }

.empty-tip { text-align: center; padding: 60px; color: #94a3b8; font-size: 14px; }

.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 12px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
.task-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.task-table tr:hover td { background: #f8fafc; }

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

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; }
.btn-sm:hover { background: #f8fafc; }
.btn-active { border-color: #2563eb; color: #2563eb; background: #eff6ff; }

.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.field-input-sm { padding: 6px 10px; font-size: 13px; }
</style>
