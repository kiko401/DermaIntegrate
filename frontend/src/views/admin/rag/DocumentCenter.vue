<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts })

const docs = ref([])
const kbs = ref([])
const loading = ref(false)
const uploading = ref(false)
const uploadErr = ref('')
const deleteErr = ref('')

const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filterKb = ref('')
const filterStatus = ref('')
const filterSearch = ref('')
const filterExt = ref('')

const fileInput = ref(null)
const uploadKbId = ref('')

const preview = ref(null)
const previewDoc = ref(null)
const previewLoading = ref(false)
const previewTab = ref('raw')
const previewErr = ref('')

// { [docId]: { stage, progress, message, status, chunkCount, hideTimer, refreshTimer } }
const taskProgress = reactive({})
const taskSubs = {}

const versionsOpen = ref(false)
const versionsDoc = ref(null)
const versionsList = ref([])
const versionsActiveId = ref(null)
const versionsLoading = ref(false)
const versionsErr = ref('')

const editDocId = ref(null)
const editTitle = ref('')
const editSaving = ref(false)
const editErr = ref('')

const statusLabels = {
  uploaded: '已上传',
  parsing: '解析中',
  indexed: '已索引',
  failed: '失败',
  deleted: '已删除',
}

const stageLabels = {
  queued: '队列中',
  parsing: '解析文档',
  splitting: '切分文本',
  dense_embedding: '向量嵌入',
  bm25_fitting: '构建 BM25',
  preparing_payload: '准备索引数据',
  indexing: '写入向量库',
  done: '完成',
  completed: '完成',
  failed: '失败',
}

const stageProgressFloor = {
  queued: 8,
  parsing: 20,
  splitting: 35,
  dense_embedding: 55,
  bm25_fitting: 72,
  preparing_payload: 88,
  indexing: 96,
  done: 100,
  completed: 100,
}

const versionStatusLabels = {
  draft: '草稿',
  active: '当前版本',
  archived: '已归档',
  failed: '失败',
}

const extOptions = ['.pdf', '.docx', '.txt', '.md', '.csv', '.xlsx', '.xls']

function getStageLabel(stage) {
  return stageLabels[stage] || stage || '处理中'
}

function createDoneMessage(chunkCount) {
  return `完成（${chunkCount ?? 0} chunks）`
}

function clearProgressTimers(docId) {
  const state = taskProgress[docId]
  if (!state) return
  if (state.hideTimer) clearTimeout(state.hideTimer)
  if (state.refreshTimer) clearTimeout(state.refreshTimer)
  state.hideTimer = null
  state.refreshTimer = null
}

function cleanupProgress(docId) {
  clearProgressTimers(docId)
  delete taskProgress[docId]
}

function closeTaskSubscription(docId) {
  if (taskSubs[docId]) {
    taskSubs[docId].close()
    delete taskSubs[docId]
  }
}

function patchDoc(docId, patch = {}) {
  const idx = docs.value.findIndex(d => d.id === docId)
  if (idx >= 0) {
    docs.value[idx] = { ...docs.value[idx], ...patch }
  }
  if (previewDoc.value?.id === docId) {
    previewDoc.value = { ...previewDoc.value, ...patch }
  }
}

function scheduleProgressDismiss(docId, { fetchDelay = 300, hideDelay = 3000 } = {}) {
  const state = taskProgress[docId]
  if (!state) return
  clearProgressTimers(docId)
  state.refreshTimer = setTimeout(async () => {
    await fetchDocs()
  }, fetchDelay)
  state.hideTimer = setTimeout(() => {
    cleanupProgress(docId)
  }, hideDelay)
}

function buildTaskProgressState(input = {}, prev = null) {
  const stage = input.stage || prev?.stage || 'queued'
  const floor = stageProgressFloor[stage] ?? 0
  const prevProgress = Number(prev?.progress ?? 0) || 0
  const rawProgress = Number(input.progress ?? prev?.progress ?? 0) || 0
  const nextProgress = Math.max(floor, rawProgress, prevProgress)

  return {
    stage,
    progress: Math.min(100, nextProgress),
    message: input.message || getStageLabel(stage),
    status: input.status || prev?.status || 'running',
    chunkCount: input.chunkCount ?? prev?.chunkCount ?? null,
    hideTimer: prev?.hideTimer || null,
    refreshTimer: prev?.refreshTimer || null,
  }
}

function displayChunkCount(doc) {
  const liveChunkCount = taskProgress[doc.id]?.chunkCount
  if (liveChunkCount != null) return liveChunkCount
  return doc.chunk_count ?? 0
}

function shouldShowProgressMessage(docId) {
  const state = taskProgress[docId]
  if (!state?.message) return false
  return state.message !== getStageLabel(state.stage)
}

onMounted(async () => {
  await Promise.all([fetchDocs(), fetchKbs()])
})

onUnmounted(() => {
  Object.keys(taskSubs).forEach((docId) => closeTaskSubscription(docId))
  Object.keys(taskProgress).forEach((docId) => cleanupProgress(docId))
})

async function fetchDocs() {
  loading.value = true
  deleteErr.value = ''
  const params = new URLSearchParams()
  if (filterKb.value) params.set('kb_id', filterKb.value)
  else params.set('all_kbs', 'true')
  if (filterStatus.value) params.set('status', filterStatus.value)
  if (filterSearch.value) params.set('search', filterSearch.value)
  if (filterExt.value) params.set('file_ext', filterExt.value)
  params.set('page', String(page.value))
  params.set('pageSize', String(pageSize.value))
  const res = await API(`/api/rag/documents?${params}`)
  const data = await res.json()
  docs.value = data.data || []
  total.value = data.total || 0
  loading.value = false
}

async function fetchKbs() {
  const res = await API('/api/rag/kbs')
  const data = await res.json()
  kbs.value = Array.isArray(data) ? data : (data.data || [])
  if (!uploadKbId.value && kbs.value.length) uploadKbId.value = String(kbs.value[0].id)
}

function onFilterChange() {
  page.value = 1
  fetchDocs()
}

function triggerUpload() {
  uploadErr.value = ''
  fileInput.value?.click()
}

async function handleFiles(e) {
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  if (!uploadKbId.value) {
    uploadErr.value = '请先选择目标知识库'
    return
  }

  uploading.value = true
  uploadErr.value = ''
  const fd = new FormData()
  fd.append('kb_id', uploadKbId.value)
  fd.append('source_type', files.length > 1 ? 'import_local' : 'upload')
  files.forEach(f => fd.append('files', f))

  try {
    const res = await fetch('/api/rag/documents/upload', {
      method: 'POST',
      credentials: 'include',
      body: fd,
    })
    const data = await res.json()
    if (!res.ok) {
      uploadErr.value = data.message || data.error || '上传失败'
      return
    }

    page.value = 1
    await fetchDocs()

    const items = data.data || []
    items.forEach(item => {
      if (item.doc_id && item.task_id) subscribeTask(item.doc_id, item.task_id)
    })
  } catch (err) {
    uploadErr.value = err.message || '上传失败'
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

function subscribeTask(docId, taskId) {
  closeTaskSubscription(docId)
  cleanupProgress(docId)

  patchDoc(docId, { status: 'parsing' })
  taskProgress[docId] = buildTaskProgressState({
    stage: 'queued',
    progress: stageProgressFloor.queued,
    message: getStageLabel('queued'),
    status: 'running',
  })

  const es = new EventSource(`/api/rag/tasks/${taskId}/stream`)
  taskSubs[docId] = es

  es.addEventListener('progress', (ev) => {
    const d = JSON.parse(ev.data)
    taskProgress[docId] = buildTaskProgressState({
      stage: d.stage,
      progress: d.progress,
      message: d.message || getStageLabel(d.stage),
      status: 'running',
    }, taskProgress[docId])
    patchDoc(docId, { status: 'parsing' })
  })

  es.addEventListener('done', (ev) => {
    const d = JSON.parse(ev.data)
    taskProgress[docId] = buildTaskProgressState({
      stage: 'done',
      progress: 100,
      message: createDoneMessage(d.chunk_count),
      status: 'succeeded',
      chunkCount: d.chunk_count ?? 0,
    }, taskProgress[docId])

    patchDoc(docId, {
      status: 'indexed',
      chunk_count: d.chunk_count ?? 0,
    })

    if (preview.value && previewDoc.value?.id === docId) {
      preview.value = {
        ...preview.value,
        chunk_count: d.chunk_count ?? 0,
      }
    }

    closeTaskSubscription(docId)
    scheduleProgressDismiss(docId, { fetchDelay: 300, hideDelay: 3000 })
  })

  es.addEventListener('error', (ev) => {
    if (!ev.data) return

    let message = getStageLabel('failed')
    try {
      const d = JSON.parse(ev.data)
      message = d.message || message
    } catch {
      // ignore parse errors
    }

    taskProgress[docId] = buildTaskProgressState({
      stage: 'failed',
      progress: taskProgress[docId]?.progress || 100,
      message,
      status: 'failed',
    }, taskProgress[docId])

    patchDoc(docId, { status: 'failed' })
    closeTaskSubscription(docId)
    scheduleProgressDismiss(docId, { fetchDelay: 300, hideDelay: 5000 })
  })

  es.onerror = () => {
    // 业务事件由 addEventListener('error') 处理；这里只处理真正断连后的清理
    if (taskSubs[docId] !== es) return
    if (es.readyState === EventSource.CLOSED) {
      delete taskSubs[docId]
    }
  }
}

async function openVersions(doc) {
  versionsDoc.value = doc
  versionsActiveId.value = doc.active_version_id
  versionsList.value = []
  versionsErr.value = ''
  versionsLoading.value = true
  versionsOpen.value = true
  try {
    const res = await API(`/api/rag/documents/${doc.id}/versions`)
    const data = await res.json()
    versionsList.value = data.data || []
    versionsActiveId.value = data.active_version_id
  } catch (err) {
    versionsErr.value = err.message
  } finally {
    versionsLoading.value = false
  }
}

function closeVersions() {
  versionsOpen.value = false
  versionsDoc.value = null
}

async function doReindex(doc) {
  if (!confirm(`确认重建索引「${doc.title}」？将重新切分并向量化当前版本。`)) return
  versionsErr.value = ''
  const res = await API(`/api/rag/documents/${doc.id}/reindex`, { method: 'POST' })
  const data = await res.json()
  if (!res.ok) {
    versionsErr.value = data.message || data.error || '重建索引失败'
    return
  }
  closeVersions()
  subscribeTask(doc.id, data.task_id)
  await fetchDocs()
}

async function doRollback(docId, versionId) {
  if (!confirm('确认回滚到此版本？将重新建立向量索引。')) return
  versionsErr.value = ''
  const res = await API(`/api/rag/documents/${docId}/rollback/${versionId}`, { method: 'POST' })
  const data = await res.json()
  if (!res.ok) {
    versionsErr.value = data.message || data.error || '回滚失败'
    return
  }
  closeVersions()
  subscribeTask(docId, data.task_id)
  await fetchDocs()
}

function chunkCount(v) {
  const m = typeof v.chunk_meta === 'string' ? JSON.parse(v.chunk_meta || '{}') : (v.chunk_meta || {})
  return m.chunk_count ?? 0
}

function startEditTitle(doc) {
  editDocId.value = doc.id
  editTitle.value = doc.title
  editErr.value = ''
}

function cancelEdit() {
  editDocId.value = null
  editTitle.value = ''
}

async function saveTitle() {
  if (!editTitle.value.trim()) {
    editErr.value = '标题不能为空'
    return
  }
  editSaving.value = true
  editErr.value = ''
  try {
    const res = await API(`/api/rag/documents/${editDocId.value}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: editTitle.value.trim() }),
    })
    const data = await res.json()
    if (!res.ok) {
      editErr.value = data.message || data.error || '保存失败'
      return
    }
    const idx = docs.value.findIndex(d => d.id === editDocId.value)
    if (idx >= 0) docs.value[idx] = { ...docs.value[idx], title: data.title || editTitle.value.trim() }
    cancelEdit()
  } catch (err) {
    editErr.value = err.message
  } finally {
    editSaving.value = false
  }
}

async function removeDoc(doc) {
  if (!confirm(`确认删除文档「${doc.title}」？此操作将同步删除向量索引。`)) return
  deleteErr.value = ''
  const res = await API(`/api/rag/documents/${doc.id}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    deleteErr.value = data.message || data.error || '删除失败'
    return
  }
  if (previewDoc.value?.id === doc.id) closePreview()
  cleanupProgress(doc.id)
  closeTaskSubscription(doc.id)
  await fetchDocs()
}

function downloadDoc(doc) {
  const a = document.createElement('a')
  a.href = `/api/rag/documents/${doc.id}/download`
  a.download = doc.file_name
  a.click()
}

async function openPreview(doc) {
  previewDoc.value = doc
  preview.value = null
  previewErr.value = ''
  previewLoading.value = true
  previewTab.value = 'raw'
  try {
    const res = await API(`/api/rag/documents/${doc.id}/preview`)
    const data = await res.json()
    if (!res.ok) {
      previewErr.value = data.message || data.error || '加载预览失败'
      return
    }
    preview.value = data
  } catch (err) {
    previewErr.value = err.message || '加载预览失败'
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewDoc.value = null
  preview.value = null
  previewErr.value = ''
}

const totalPages = () => Math.ceil(total.value / pageSize.value) || 1

function goPage(p) {
  const max = totalPages()
  if (p < 1 || p > max) return
  page.value = p
  fetchDocs()
}

function kbName(kbId) {
  return kbs.value.find(k => k.id === kbId)?.name || `KB#${kbId}`
}

function fmtDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleDateString('zh-CN')
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">文档管理</h2>
      <div class="upload-bar">
        <span class="upload-label">上传至：</span>
        <select v-model="uploadKbId" class="field-input field-input-sm">
          <option value="" disabled>选择知识库</option>
          <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
        </select>
        <button class="btn-primary" :disabled="uploading" @click="triggerUpload">
          {{ uploading ? '上传中...' : '+ 上传文档' }}
        </button>
        <input
          ref="fileInput"
          type="file"
          multiple
          style="display:none"
          accept=".txt,.md,.pdf,.docx,.csv,.xlsx,.xls"
          @change="handleFiles"
        />
      </div>
    </div>

    <div v-if="uploadErr" class="notice notice-err">{{ uploadErr }}</div>
    <div v-if="deleteErr" class="notice notice-err">{{ deleteErr }}</div>

    <div class="filter-bar">
      <input
        v-model="filterSearch"
        class="field-input field-input-sm"
        placeholder="按标题搜索"
        @keyup.enter="onFilterChange"
        @blur="onFilterChange"
      />
      <select v-model="filterExt" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部格式</option>
        <option v-for="ext in extOptions" :key="ext" :value="ext">{{ ext }}</option>
      </select>
      <select v-model="filterKb" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部知识库</option>
        <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
      </select>
      <select v-model="filterStatus" class="field-input field-input-sm" @change="onFilterChange">
        <option value="">全部状态</option>
        <option value="uploaded">已上传</option>
        <option value="parsing">解析中</option>
        <option value="indexed">已索引</option>
        <option value="failed">失败</option>
      </select>
    </div>

    <div class="content-wrap" :class="{ 'has-preview': !!previewDoc }">
      <div class="list-panel">
        <div v-if="loading" class="empty-tip">加载中...</div>
        <div v-else-if="!docs.length" class="empty-tip">暂无文档</div>

        <table v-else class="doc-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>所属知识库</th>
              <th>格式</th>
              <th>Chunks</th>
              <th class="status-col">状态</th>
              <th>上传时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="doc in docs"
              :key="doc.id"
              :class="{ 'row-active': previewDoc?.id === doc.id }"
            >
              <td class="doc-title" :title="doc.title">{{ doc.title }}</td>
              <td>{{ kbName(doc.kb_id) }}</td>
              <td class="ext-cell">{{ doc.file_ext }}</td>
              <td class="num-cell">{{ displayChunkCount(doc) || '-' }}</td>
              <td class="status-cell">
                <div v-if="taskProgress[doc.id]" class="tp-wrap">
                  <div class="tp-head">
                    <span
                      class="tp-stage"
                      :class="taskProgress[doc.id].status === 'failed' ? 'tp-stage-fail' : 'tp-stage-run'"
                    >
                      {{ getStageLabel(taskProgress[doc.id].stage) }}
                    </span>
                    <span class="tp-percent">{{ taskProgress[doc.id].progress }}%</span>
                  </div>
                  <div
                    class="tp-bar"
                    :class="taskProgress[doc.id].status === 'failed' ? 'tp-bar-fail' : 'tp-bar-run'"
                  >
                    <div
                      class="tp-fill"
                      :style="{ width: taskProgress[doc.id].progress + '%' }"
                    ></div>
                  </div>
                  <span v-if="shouldShowProgressMessage(doc.id)" class="tp-msg">{{ taskProgress[doc.id].message }}</span>
                </div>
                <span v-else class="status-badge" :class="doc.status">
                  {{ statusLabels[doc.status] || doc.status }}
                </span>
              </td>
              <td class="date-cell">{{ fmtDate(doc.created_at) }}</td>
              <td class="actions-cell">
                <button class="btn-sm" @click="openPreview(doc)">预览</button>
                <button class="btn-sm" @click="downloadDoc(doc)">下载</button>
                <button class="btn-sm" @click="openVersions(doc)">版本</button>
                <button class="btn-sm" @click="startEditTitle(doc)">编辑</button>
                <button class="btn-sm btn-danger" @click="removeDoc(doc)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="total > pageSize" class="pagination">
          <button class="btn-sm" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span class="page-info">{{ page }} / {{ totalPages() }}（共 {{ total }} 条）</span>
          <button class="btn-sm" :disabled="page >= totalPages()" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>

      <div v-if="previewDoc" class="preview-panel">
        <div class="preview-header">
          <span class="preview-title" :title="previewDoc.title">{{ previewDoc.title }}</span>
          <button class="close-btn" @click="closePreview">✕</button>
        </div>

        <div v-if="previewLoading" class="preview-loading">加载预览中...</div>
        <div v-else-if="previewErr" class="empty-tip-sm">{{ previewErr }}</div>

        <template v-else-if="preview">
          <div class="preview-meta">
            <span>版本 v{{ preview.version_no }}</span>
            <span>模型 {{ preview.embedding_model }}</span>
            <span>{{ preview.chunk_count }} chunks</span>
          </div>

          <div class="preview-tabs">
            <button class="tab-btn" :class="{ active: previewTab === 'raw' }" @click="previewTab = 'raw'">原始文本</button>
            <button class="tab-btn" :class="{ active: previewTab === 'clean' }" @click="previewTab = 'clean'">清洗文本</button>
            <button class="tab-btn" :class="{ active: previewTab === 'chunks' }" @click="previewTab = 'chunks'">Chunks（{{ preview.chunk_count }}）</button>
          </div>

          <div v-show="previewTab === 'raw'" class="preview-body">
            <div v-if="preview.raw_text_preview" class="text-block">
              <pre>{{ preview.raw_text_preview }}</pre>
              <p v-if="preview.chunk_count > 0" class="truncate-hint">仅展示前 2000 字符</p>
            </div>
            <div v-else class="empty-tip-sm">暂无原始文本（ingest 完成后可见）</div>
          </div>

          <div v-show="previewTab === 'clean'" class="preview-body">
            <div v-if="preview.cleaned_text_preview" class="text-block">
              <pre>{{ preview.cleaned_text_preview }}</pre>
              <p v-if="preview.chunk_count > 0" class="truncate-hint">仅展示前 2000 字符</p>
            </div>
            <div v-else class="empty-tip-sm">暂无清洗文本（ingest 完成后可见）</div>
          </div>

          <div v-show="previewTab === 'chunks'" class="preview-body">
            <div v-if="preview.chunks_preview && preview.chunks_preview.length">
              <div
                v-for="chunk in preview.chunks_preview"
                :key="chunk.chunk_index"
                class="chunk-item"
              >
                <div class="chunk-header">
                  <span class="chunk-id">{{ chunk.chunk_id }}</span>
                  <span class="chunk-len">{{ chunk.length }} 字</span>
                </div>
                <p class="chunk-text">{{ chunk.text }}</p>
              </div>
            </div>
            <div v-else-if="preview.chunks_status === 'failed'" class="empty-tip-sm">
              Chunk 加载失败：{{ preview.chunks_error || '请稍后重试' }}
            </div>
            <div v-else class="empty-tip-sm">
              {{ preview.chunk_count > 0 ? '暂无 Chunk 预览数据' : '暂无 Chunk 数据（ingest 完成后可见）' }}
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>

  <div v-if="versionsOpen" class="modal-backdrop" @click.self="closeVersions">
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">版本历史 - {{ versionsDoc?.title }}</span>
        <div class="modal-header-actions">
          <button class="btn-sm" :disabled="versionsLoading || !versionsDoc" @click="doReindex(versionsDoc)">重建索引</button>
          <button class="close-btn" @click="closeVersions">✕</button>
        </div>
      </div>

      <div v-if="versionsErr" class="notice notice-err" style="margin:12px 16px 0">{{ versionsErr }}</div>
      <div v-if="versionsLoading" class="modal-loading">加载版本列表中...</div>
      <div v-else-if="!versionsList.length" class="empty-tip-sm">暂无版本记录</div>

      <table v-else class="ver-table">
        <thead>
          <tr>
            <th>版本号</th>
            <th>状态</th>
            <th>Chunks</th>
            <th>嵌入模型</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="v in versionsList"
            :key="v.id"
            :class="{ 'ver-active': v.id === versionsActiveId }"
          >
            <td class="num-cell">v{{ v.version_no }}</td>
            <td>
              <span class="ver-badge" :class="v.status">
                {{ versionStatusLabels[v.status] || v.status }}
              </span>
            </td>
            <td class="num-cell">{{ chunkCount(v) || '-' }}</td>
            <td class="ext-cell">{{ v.embedding_model }}</td>
            <td class="date-cell">{{ fmtDate(v.created_at) }}</td>
            <td>
              <button
                v-if="v.id !== versionsActiveId"
                class="btn-sm"
                @click="doRollback(versionsDoc.id, v.id)"
              >回滚到此版本</button>
              <span v-else class="cur-label">当前版本</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="editDocId !== null" class="modal-backdrop" @click.self="cancelEdit">
    <div class="modal modal-sm">
      <div class="modal-header">
        <span class="modal-title">编辑标题</span>
        <button class="close-btn" @click="cancelEdit">✕</button>
      </div>
      <div class="modal-body">
        <input
          v-model="editTitle"
          class="field-input"
          placeholder="文档标题"
          @keyup.enter="saveTitle"
        />
        <div v-if="editErr" class="notice notice-err" style="margin-top:8px">{{ editErr }}</div>
      </div>
      <div class="modal-footer">
        <button class="btn-sm" @click="cancelEdit">取消</button>
        <button class="btn-primary" :disabled="editSaving" @click="saveTitle">
          {{ editSaving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }

.upload-bar { display: flex; align-items: center; gap: 10px; }
.upload-label { font-size: 13px; color: #64748b; white-space: nowrap; }

.notice { font-size: 13px; margin-bottom: 12px; padding: 8px 12px; border-radius: 6px; }
.notice-err { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }
.filter-bar .field-input { width: auto; min-width: 140px; }

.content-wrap { display: flex; gap: 16px; align-items: flex-start; }
.list-panel { flex: 1; min-width: 0; }
.preview-panel {
  width: 420px; flex-shrink: 0;
  border: 1px solid #e2e8f0; border-radius: 8px;
  background: #fff; display: flex; flex-direction: column;
  max-height: calc(100vh - 200px); overflow: hidden;
}

.empty-tip { text-align: center; padding: 60px; color: #94a3b8; font-size: 14px; }
.empty-tip-sm { text-align: center; padding: 32px; color: #94a3b8; font-size: 13px; }

.doc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.doc-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 12px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
.doc-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.doc-table tr:hover td { background: #f8fafc; }
.row-active td { background: #eff6ff !important; }

.doc-title { font-weight: 500; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ext-cell { color: #64748b; font-size: 12px; }
.num-cell { text-align: right; font-variant-numeric: tabular-nums; }
.date-cell { white-space: nowrap; color: #64748b; font-size: 12px; }
.actions-cell { white-space: nowrap; }

.pagination { display: flex; align-items: center; gap: 10px; margin-top: 16px; justify-content: flex-end; }
.page-info { font-size: 13px; color: #64748b; }

.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; display: inline-flex; align-items: center; }
.status-badge.uploaded { background: #e0f2fe; color: #0369a1; }
.status-badge.parsing { background: #fef3c7; color: #92400e; }
.status-badge.indexed { background: #f0fdf4; color: #166534; }
.status-badge.failed { background: #fef2f2; color: #dc2626; }
.status-badge.deleted { background: #f1f5f9; color: #94a3b8; }

.status-col { min-width: 240px; }
.status-cell { min-width: 240px; }
.tp-wrap {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 220px;
  padding: 2px 0;
}
.tp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.tp-stage {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.tp-stage-run {
  color: #2b5fb8;
  background: #e8f1ff;
}
.tp-stage-fail {
  color: #c24141;
  background: #fdecec;
}
.tp-percent {
  font-size: 11px;
  color: #7b8aa0;
  font-variant-numeric: tabular-nums;
}
.tp-bar {
  height: 4px;
  border-radius: 999px;
  overflow: hidden;
}
.tp-bar-run { background: #d6e5ff; }
.tp-bar-fail { background: #f7d4d4; }
.tp-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #5c9cff 0%, #4d7ff3 100%);
  transition: width 0.28s ease;
}
.tp-bar-fail .tp-fill { background: linear-gradient(90deg, #ef7b7b 0%, #de5a5a 100%); }
.tp-msg {
  font-size: 11px;
  color: #7b8aa0;
  line-height: 1.35;
}

.preview-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #e2e8f0; background: #f8fafc;
}
.preview-title {
  font-size: 13px; font-weight: 600; color: #1e293b;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px;
}
.close-btn { background: none; border: none; font-size: 14px; color: #94a3b8; cursor: pointer; padding: 2px 4px; }
.close-btn:hover { color: #475569; }
.preview-loading { text-align: center; padding: 32px; color: #94a3b8; font-size: 13px; }
.preview-meta {
  display: flex; gap: 12px; padding: 8px 16px;
  font-size: 11px; color: #64748b; border-bottom: 1px solid #f1f5f9; flex-wrap: wrap;
}
.preview-tabs { display: flex; border-bottom: 1px solid #e2e8f0; }
.tab-btn {
  flex: 1; padding: 8px 4px; font-size: 12px; border: none; background: none;
  color: #64748b; cursor: pointer; border-bottom: 2px solid transparent;
}
.tab-btn:hover { color: #334155; }
.tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }
.preview-body { flex: 1; overflow-y: auto; padding: 12px 16px; }
.text-block pre {
  white-space: pre-wrap; word-break: break-all;
  font-size: 12px; line-height: 1.6; color: #334155;
  margin: 0; font-family: 'Courier New', monospace;
}
.truncate-hint { font-size: 11px; color: #94a3b8; margin: 8px 0 0; text-align: right; }
.chunk-item { margin-bottom: 12px; border: 1px solid #f1f5f9; border-radius: 6px; overflow: hidden; }
.chunk-header { display: flex; justify-content: space-between; align-items: center; padding: 5px 10px; background: #f8fafc; border-bottom: 1px solid #f1f5f9; }
.chunk-id { font-size: 11px; font-family: monospace; color: #2563eb; }
.chunk-len { font-size: 11px; color: #94a3b8; }
.chunk-text { margin: 0; padding: 8px 10px; font-size: 12px; line-height: 1.6; color: #334155; white-space: pre-wrap; word-break: break-all; }

.modal-backdrop {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal {
  background: #fff; border-radius: 10px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  min-width: 640px; max-width: 900px; width: 90%; max-height: 80vh;
  display: flex; flex-direction: column; overflow: hidden;
}
.modal-sm { min-width: 360px; max-width: 420px; }
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-bottom: 1px solid #e2e8f0; background: #f8fafc;
  flex-shrink: 0;
}
.modal-header-actions { display: flex; align-items: center; gap: 8px; }
.modal-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.modal-loading { text-align: center; padding: 40px; color: #94a3b8; font-size: 13px; }
.modal-body { padding: 20px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #f1f5f9; }

.ver-table { width: 100%; border-collapse: collapse; font-size: 13px; overflow-y: auto; }
.ver-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 16px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
.ver-table td { padding: 10px 16px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.ver-table tr:hover td { background: #f8fafc; }
.ver-active td { background: #f0fdf4 !important; }

.ver-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.ver-badge.active { background: #f0fdf4; color: #166534; }
.ver-badge.draft { background: #fef3c7; color: #92400e; }
.ver-badge.archived { background: #f1f5f9; color: #64748b; }
.ver-badge.failed { background: #fef2f2; color: #dc2626; }

.cur-label { font-size: 11px; color: #64748b; font-style: italic; }

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; margin-right: 4px; }
.btn-sm:hover:not(:disabled) { background: #f8fafc; }
.btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-danger { border-color: #fecaca; color: #dc2626; }
.btn-danger:hover { background: #fef2f2; }

.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.field-input-sm { padding: 6px 10px; font-size: 13px; }
</style>
