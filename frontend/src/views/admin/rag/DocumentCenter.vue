<script setup>
import { ref, computed, onMounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts }).then(r => r.json())

const docs       = ref([])
const kbs        = ref([])
const loading    = ref(false)
const uploading  = ref(false)
const uploadErr  = ref('')

const filterKb     = ref('')
const filterStatus = ref('')
const filterName   = ref('')

const fileInput  = ref(null)
const uploadKbId = ref('')

const statusLabels = {
  uploaded: '已上传',
  processing: '处理中',
  indexed: '已索引',
  failed: '失败',
  deleted: '已删除',
}

onMounted(async () => {
  await Promise.all([fetchDocs(), fetchKbs()])
})

async function fetchDocs() {
  loading.value = true
  const params = new URLSearchParams()
  if (filterKb.value)     params.set('kb_id', filterKb.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  const data = await API(`/api/rag/documents?${params}`)
  docs.value = Array.isArray(data) ? data : []
  loading.value = false
}

async function fetchKbs() {
  const data = await API('/api/rag/kbs')
  kbs.value = Array.isArray(data) ? data : []
  if (!uploadKbId.value && kbs.value.length) uploadKbId.value = String(kbs.value[0].id)
}

function triggerUpload() {
  uploadErr.value = ''
  fileInput.value.click()
}

async function handleFiles(e) {
  const files = Array.from(e.target.files)
  if (!files.length) return
  if (!uploadKbId.value) { uploadErr.value = '请先选择目标知识库'; return }

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
    if (!res.ok) { uploadErr.value = data.error || '上传失败'; return }
    await fetchDocs()
  } catch (err) {
    uploadErr.value = err.message
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

async function removeDoc(doc) {
  if (!confirm(`确认删除文档「${doc.title}」？此操作将同步删除向量索引。`)) return
  await API(`/api/rag/documents/${doc.id}`, { method: 'DELETE' })
  await fetchDocs()
}

function downloadDoc(doc) {
  const a = document.createElement('a')
  a.href = `/api/rag/documents/${doc.id}/download`
  a.download = doc.file_name
  a.click()
}

const filteredDocs = computed(() => {
  return docs.value.filter(d => {
    if (filterName.value && !d.title.includes(filterName.value)) return false
    return true
  })
})

function kbName(kbId) {
  return kbs.value.find(k => k.id === kbId)?.name || `KB#${kbId}`
}

function fmtSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
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
        <select v-model="uploadKbId" class="field-input field-input-sm">
          <option value="" disabled>选择知识库</option>
          <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
        </select>
        <button class="btn-primary" :disabled="uploading" @click="triggerUpload">
          {{ uploading ? '上传中...' : '+ 上传文档' }}
        </button>
        <input ref="fileInput" type="file" multiple style="display:none"
          accept=".txt,.md,.pdf,.docx,.csv,.xlsx,.xls"
          @change="handleFiles" />
      </div>
    </div>

    <div v-if="uploadErr" class="upload-err">{{ uploadErr }}</div>

    <div class="filter-bar">
      <input v-model="filterName" class="field-input field-input-sm" placeholder="按标题搜索" @input="" />
      <select v-model="filterKb" class="field-input field-input-sm" @change="fetchDocs">
        <option value="">全部知识库</option>
        <option v-for="kb in kbs" :key="kb.id" :value="String(kb.id)">{{ kb.name }}</option>
      </select>
      <select v-model="filterStatus" class="field-input field-input-sm" @change="fetchDocs">
        <option value="">全部状态</option>
        <option value="uploaded">已上传</option>
        <option value="processing">处理中</option>
        <option value="indexed">已索引</option>
        <option value="failed">失败</option>
      </select>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <div v-else-if="!filteredDocs.length" class="empty-tip">暂无文档</div>

    <table v-else class="doc-table">
      <thead>
        <tr>
          <th>标题</th>
          <th>所属知识库</th>
          <th>文件类型</th>
          <th>大小</th>
          <th>状态</th>
          <th>上传时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="doc in filteredDocs" :key="doc.id">
          <td class="doc-title">{{ doc.title }}</td>
          <td>{{ kbName(doc.kb_id) }}</td>
          <td class="ext-cell">{{ doc.file_ext }}</td>
          <td>{{ fmtSize(doc.file_size) }}</td>
          <td>
            <span class="status-badge" :class="doc.status">
              {{ statusLabels[doc.status] || doc.status }}
            </span>
          </td>
          <td>{{ fmtDate(doc.created_at) }}</td>
          <td class="actions-cell">
            <button class="btn-sm" @click="downloadDoc(doc)">下载</button>
            <button class="btn-sm btn-danger" @click="removeDoc(doc)">删除</button>
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

.upload-bar { display: flex; align-items: center; gap: 10px; }
.upload-err { color: #dc2626; font-size: 13px; margin-bottom: 12px; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; }
.filter-bar .field-input { width: auto; min-width: 160px; }

.empty-tip { text-align: center; padding: 60px; color: #94a3b8; font-size: 14px; }

.doc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.doc-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 12px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
.doc-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.doc-table tr:hover td { background: #f8fafc; }

.doc-title { font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ext-cell { color: #64748b; font-size: 12px; }
.actions-cell { white-space: nowrap; }

.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-badge.uploaded  { background: #e0f2fe; color: #0369a1; }
.status-badge.processing { background: #fef3c7; color: #92400e; }
.status-badge.indexed   { background: #f0fdf4; color: #166534; }
.status-badge.failed    { background: #fef2f2; color: #dc2626; }
.status-badge.deleted   { background: #f1f5f9; color: #94a3b8; }

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; margin-right: 4px; }
.btn-sm:hover { background: #f8fafc; }
.btn-danger { border-color: #fecaca; color: #dc2626; }
.btn-danger:hover { background: #fef2f2; }

.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.field-input-sm { padding: 6px 10px; font-size: 13px; }
</style>
