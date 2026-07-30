<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { marked } from 'marked'

marked.setOptions({ breaks: true })

function renderMd(text) {
  if (!text) return ''
  return marked.parse(text)
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, { credentials: 'include', ...opts })
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await res.json() : null
  return { ok: res.ok, status: res.status, data }
}

function readDoctorInfo() {
  try { return JSON.parse(localStorage.getItem('doctor_info') || '{}') } catch { return {} }
}

const doctorInfo = ref(readDoctorInfo())
const activeView = ref('chat')
const hoverConvId = ref(null)
const sidebarCollapsed = ref(false)

const conversations = ref([])
const activeConvId = ref(null)
const messages = ref([])
const conversationActionId = ref(null)
const editingConvId = ref(null)
const editingConvTitle = ref('')
const knowledgeBases = ref([])
const selectedKbIds = ref([])
const inputText = ref('')
const loading = ref(false)
const kbLoading = ref(false)
const msgContainer = ref(null)
const quickTemplates = ref([])
const kbRequiredHint = ref(false)
const kbSelectOpen = ref(false)
const kbSearchText = ref('')

const kbDrawerOpen = ref(false)
const fileDrawerOpen = ref(false)
const docPreviewOpen = ref(false)
const docPreviewLoading = ref(false)
const docPreviewErr = ref('')
const docPreviewData = ref(null)
const docPreviewTitle = ref('')
const docPreviewChunkId = ref(null)
const docPreviewTab = ref('chunks')

const kbForm = ref({ name: '', description: '' })
const kbFormLoading = ref(false)
const kbFormError = ref('')

const showUpgradeApplyDialog = ref(false)
const upgradeApplyTarget = ref(null)
const upgradeApplyDocs = ref([])
const upgradeApplyDocsLoading = ref(false)
const upgradeApplyForm = ref({ target_kb_id: '', selected_doc_ids: [], reason: '' })
const upgradeApplyError = ref('')
const upgradeApplyLoading = ref(false)
const showUpgradeHistoryDialog = ref(false)
const upgradeHistory = ref([])
const upgradeHistoryLoading = ref(false)

const fileInput = ref(null)
const uploadTargetKbId = ref(null)
const uploadLoadingKbId = ref(null)
const uploadError = ref('')
const uploadErrorKbId = ref(null)

const docSearch = ref('')
const docsLoading = ref(false)
const docs = ref([])
const docsPage = ref(1)
const docsPageSize = ref(20)
const docsTotal = ref(0)
const manageSelectedKbId = ref(null)
const selectedDocIds = ref([])

const activeConv = computed(() => conversations.value.find(c => c.id === activeConvId.value) || null)
const personalKbs = computed(() => knowledgeBases.value.filter(kb => kb.scope_type === 'personal' && kb.scope_owner_id === doctorInfo.value.id))
const departmentKbs = computed(() => knowledgeBases.value.filter(kb => kb.scope_type === 'department'))
const publicKbs = computed(() => knowledgeBases.value.filter(kb => kb.scope_type === 'public'))
const selectedKnowledgeBases = computed(() => knowledgeBases.value.filter(kb => selectedKbIds.value.includes(kb.id)))
const selectedKbSummary = computed(() => {
  if (!selectedKnowledgeBases.value.length) return '未选择知识库'
  if (selectedKnowledgeBases.value.length === 1) return selectedKnowledgeBases.value[0].name
  return `已选择 ${selectedKnowledgeBases.value.length} 个知识库`
})
const filteredKnowledgeBases = computed(() => {
  const keyword = kbSearchText.value.trim().toLowerCase()
  if (!keyword) return knowledgeBases.value
  return knowledgeBases.value.filter(kb => {
    const scope = formatKbScope(kb)
    return [kb.name, kb.description, scope].some(item => String(item || '').toLowerCase().includes(keyword))
  })
})
const manageSelectedKb = computed(() => knowledgeBases.value.find(kb => String(kb.id) === String(manageSelectedKbId.value)) || null)
const totalDocPages = computed(() => Math.max(1, Math.ceil(docsTotal.value / docsPageSize.value)))
const canUploadToManageKb = computed(() => {
  const kb = manageSelectedKb.value
  return !!kb && kb.scope_type === 'personal' && kb.scope_owner_id === doctorInfo.value.id
})
const upgradeApplyAllSelected = computed(() =>
  upgradeApplyDocs.value.length > 0 &&
  upgradeApplyDocs.value.every(d => upgradeApplyForm.value.selected_doc_ids.includes(d.id))
)
const upgradeTargetKbs = computed(() => [...departmentKbs.value, ...publicKbs.value])

onMounted(async () => {
  await Promise.all([refreshConversations(), refreshKnowledgeBases(), loadTemplates()])
  if (conversations.value.length) await selectConversation(conversations.value[0].id)
})

async function loadTemplates() {
  try {
    const { ok, data } = await apiFetch('/api/rag/tools/templates')
    if (ok && Array.isArray(data?.templates)) quickTemplates.value = data.templates
  } catch {
    // ignore
  }
}

function applyTemplate(tpl) {
  inputText.value = tpl.question_template
}

async function refreshConversations() {
  const { data } = await apiFetch('/api/rag/conversations')
  const raw = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  conversations.value = raw.filter(item => !item.scene_type || item.scene_type === 'general')
  if (activeConvId.value && !conversations.value.some(item => item.id === activeConvId.value)) {
    activeConvId.value = conversations.value[0]?.id || null
  }
}

async function refreshKnowledgeBases() {
  kbLoading.value = true
  try {
    const { data } = await apiFetch('/api/rag/kbs')
    knowledgeBases.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
    if (!manageSelectedKbId.value) {
      manageSelectedKbId.value = selectedKbIds.value[0] || knowledgeBases.value[0]?.id || null
    }
  } finally {
    kbLoading.value = false
  }
}

async function newConversation() {
  const { ok, data } = await apiFetch('/api/rag/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: '新会话', scene_type: 'general', kb_ids: selectedKbIds.value }),
  })
  if (!ok) throw new Error(data?.message || '创建会话失败')
  conversations.value.unshift(data)
  activeView.value = 'chat'
  await selectConversation(data.id)
}

async function selectConversation(id) {
  if (editingConvId.value != null && editingConvId.value !== id) {
    cancelConversationRename()
  }
  activeView.value = 'chat'
  activeConvId.value = id
  messages.value = []
  const { data } = await apiFetch(`/api/rag/conversations/${id}/messages`)
  messages.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  scrollToBottom()
}

function startConversationRename(conv) {
  if (conversationActionId.value === conv.id) return
  editingConvId.value = conv.id
  editingConvTitle.value = String(conv?.title || '').trim() || '未命名会话'
  nextTick(() => {
    const input = document.querySelector(`[data-conv-rename-input="${conv.id}"]`)
    input?.focus()
    input?.select?.()
  })
}

function cancelConversationRename() {
  editingConvId.value = null
  editingConvTitle.value = ''
}

async function submitConversationRename(conv) {
  const currentTitle = String(conv?.title || '').trim() || '未命名会话'
  const title = editingConvTitle.value.trim()
  if (!title) {
    window.alert('会话名称不能为空')
    return
  }
  if (title === currentTitle) {
    cancelConversationRename()
    return
  }

  conversationActionId.value = conv.id
  try {
    const { ok, data } = await apiFetch(`/api/rag/conversations/${conv.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    if (!ok) throw new Error(data?.message || data?.error || '重命名失败')

    const index = conversations.value.findIndex(item => item.id === conv.id)
    if (index >= 0) conversations.value[index] = data
    cancelConversationRename()
  } catch (error) {
    window.alert(error.message || '重命名失败')
  } finally {
    conversationActionId.value = null
  }
}

async function deleteConversation(conv) {
  if (!window.confirm(`确认删除会话「${conv.title || '未命名会话'}」？`)) return

  conversationActionId.value = conv.id
  try {
    const { ok, data } = await apiFetch(`/api/rag/conversations/${conv.id}`, {
      method: 'DELETE',
    })
    if (!ok) throw new Error(data?.message || data?.error || '删除失败')

    const remaining = conversations.value.filter(item => item.id !== conv.id)
    conversations.value = remaining

    if (activeConvId.value === conv.id) {
      const nextConv = remaining[0] || null
      if (nextConv) {
        await selectConversation(nextConv.id)
      } else {
        activeConvId.value = null
        messages.value = []
      }
    }
    if (editingConvId.value === conv.id) cancelConversationRename()
  } catch (error) {
    window.alert(error.message || '删除失败')
  } finally {
    conversationActionId.value = null
  }
}

async function sendMessage() {
  const question = inputText.value.trim()
  if (!question || loading.value) return
  if (!selectedKbIds.value.length) {
    kbRequiredHint.value = true
    kbDrawerOpen.value = true
    return
  }
  kbRequiredHint.value = false
  if (!activeConvId.value) await newConversation()

  messages.value.push({ role: 'user', content_markdown: question, created_at: new Date().toISOString() })
  inputText.value = ''
  loading.value = true
  scrollToBottom()

  const assistantIdx = messages.value.length
  messages.value.push({
    role: 'assistant',
    content_markdown: '',
    sources: [],
    risk_highlights: [],
    disclaimer: null,
    _streaming: true,
    created_at: new Date().toISOString(),
  })

  try {
    const qs = new URLSearchParams({ question })
    selectedKbIds.value.forEach(id => qs.append('kb_ids', String(id)))
    const url = `/api/rag/conversations/${activeConvId.value}/stream?${qs.toString()}`

    const res = await fetch(url, { credentials: 'include' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.message || err.error || `请求失败 ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let sseBuffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      sseBuffer += decoder.decode(value, { stream: true })
      const blocks = sseBuffer.split(/\n\n/)
      sseBuffer = blocks.pop()

      for (const block of blocks) {
        if (!block.trim()) continue
        let eventType = 'message'
        let dataStr = ''
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim()
          else if (line.startsWith('data:')) dataStr = line.slice(5).trim()
        }
        if (!dataStr) continue

        let payload
        try { payload = JSON.parse(dataStr) } catch { continue }

        const msg = messages.value[assistantIdx]
        if (eventType === 'result') {
          msg.content_markdown = payload.answer || msg.content_markdown
          msg.sources = payload.sources || []
          msg.risk_highlights = payload.risk_highlights || []
          if (payload.disclaimer) msg.disclaimer = payload.disclaimer
          msg.confidence = payload.confidence
          msg._streaming = false
        } else if (eventType === 'saved') {
          msg.id = payload.message_id
        } else if (eventType === 'disclaimer') {
          msg.disclaimer = payload.disclaimer
        } else if (eventType === 'progress') {
          // 节点进度事件：展示当前执行阶段文字提示
          if (!msg.content_markdown) msg._status = payload.message || payload.step || msg._status
        } else if (eventType === 'thinking') {
          // 节点开始事件：AI 域推送节点启动提示，比 progress 更细粒度
          if (!msg.content_markdown) msg._status = payload.message || msg._status
        } else if (eventType === 'chunks') {
          // 检索完成事件：检索结果可提前展示，不等 result 事件
          if (Array.isArray(payload.chunks) && payload.chunks.length) {
            msg._status = `已检索到 ${payload.chunks.length} 条参考，正在生成回答...`
          }
        } else if (eventType === 'error') {
          msg.content_markdown = `请求失败：${payload.message || payload.code}`
          msg._streaming = false
        }
        scrollToBottom()
      }
    }

    if (messages.value[assistantIdx]._streaming) messages.value[assistantIdx]._streaming = false
  } catch (error) {
    messages.value[assistantIdx].content_markdown = `请求失败：${error.message}`
    messages.value[assistantIdx]._streaming = false
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

const feedbackState = ref({})

async function submitFeedback(msg, rating) {
  if (!msg.id) return
  const key = msg.id
  if (feedbackState.value[key] === 'sending') return
  feedbackState.value[key] = 'sending'
  try {
    await apiFetch('/api/rag/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: msg.id, rating }),
    })
    feedbackState.value[key] = rating
  } catch {
    delete feedbackState.value[key]
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  })
}

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function toggleKb(id) {
  const i = selectedKbIds.value.indexOf(id)
  if (i >= 0) selectedKbIds.value.splice(i, 1)
  else selectedKbIds.value.push(id)
  if (selectedKbIds.value.length) {
    kbRequiredHint.value = false
    kbDrawerOpen.value = false
  }
  if (!manageSelectedKbId.value) manageSelectedKbId.value = id
}

function focusKbSelect() {
  kbSelectOpen.value = true
  kbSearchText.value = ''
}

function chooseKbFromSelect(id) {
  toggleKb(id)
  kbSelectOpen.value = false
  kbSearchText.value = ''
}

function openKbDrawer() {
  kbDrawerOpen.value = true
}

function openFileDrawer(kbId = null) {
  if (kbId) manageSelectedKbId.value = kbId
  else if (!manageSelectedKbId.value) manageSelectedKbId.value = selectedKbIds.value[0] || knowledgeBases.value[0]?.id || null
  fileDrawerOpen.value = true
  fetchDocs()
}

function openManageView(kbId = null) {
  activeView.value = 'manage'
  if (kbId) manageSelectedKbId.value = kbId
  else if (!manageSelectedKbId.value) manageSelectedKbId.value = selectedKbIds.value[0] || knowledgeBases.value[0]?.id || null
  refreshKnowledgeBases()
  fetchDocs()
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

async function createPersonalKb() {
  if (!kbForm.value.name.trim()) {
    kbFormError.value = '请输入知识库名称'
    return
  }
  kbFormLoading.value = true
  kbFormError.value = ''
  try {
    const { ok, status, data } = await apiFetch('/api/rag/kbs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: kbForm.value.name.trim(),
        description: kbForm.value.description.trim(),
        scope_type: 'personal',
      }),
    })
    if (!ok) {
      if (status === 409) throw new Error('知识库名称已存在')
      throw new Error(data?.message || data?.error || '创建失败')
    }
    kbForm.value = { name: '', description: '' }
    await refreshKnowledgeBases()
    manageSelectedKbId.value = data?.id || manageSelectedKbId.value
  } catch (error) {
    kbFormError.value = error.message
  } finally {
    kbFormLoading.value = false
  }
}

function triggerUpload(kbId) {
  uploadTargetKbId.value = kbId
  uploadError.value = ''
  uploadErrorKbId.value = null
  fileInput.value?.click()
}

async function handleUpload(event) {
  const files = Array.from(event.target.files || [])
  if (!files.length || !uploadTargetKbId.value) return

  const targetId = uploadTargetKbId.value
  uploadLoadingKbId.value = targetId
  uploadError.value = ''
  try {
    const form = new FormData()
    form.append('kb_id', String(targetId))
    form.append('source_type', files.length > 1 ? 'import_local' : 'upload')
    files.forEach(file => form.append('files', file))

    const res = await fetch('/api/rag/documents/upload', { method: 'POST', credentials: 'include', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data?.message || data?.error || '上传失败')
    await refreshKnowledgeBases()
    await fetchDocs()
  } catch (error) {
    uploadError.value = error.message
    uploadErrorKbId.value = targetId
  } finally {
    uploadLoadingKbId.value = null
    uploadTargetKbId.value = null
    event.target.value = ''
  }
}

async function deletePersonalKb(kb) {
  if (!confirm(`确认删除个人知识库「${kb.name}」？`)) return
  const { ok, status, data } = await apiFetch(`/api/rag/kbs/${kb.id}?mode=logical`, { method: 'DELETE' })
  if (!ok) {
    uploadError.value = status === 403 ? '只能删除自己的个人知识库' : (data?.message || data?.error || '删除失败')
    uploadErrorKbId.value = kb.id
    return
  }
  selectedKbIds.value = selectedKbIds.value.filter(id => id !== kb.id)
  if (manageSelectedKbId.value === kb.id) manageSelectedKbId.value = knowledgeBases.value.find(item => item.id !== kb.id)?.id || null
  await refreshKnowledgeBases()
  await fetchDocs()
}

async function openUpgradeApply(kb) {
  upgradeApplyTarget.value = kb
  upgradeApplyForm.value = { target_kb_id: '', selected_doc_ids: [], reason: '' }
  upgradeApplyError.value = ''
  showUpgradeApplyDialog.value = true
  upgradeApplyDocsLoading.value = true
  const { data } = await apiFetch(`/api/rag/documents?kb_id=${kb.id}&pageSize=100`)
  upgradeApplyDocs.value = Array.isArray(data?.data) ? data.data : []
  upgradeApplyDocsLoading.value = false
}

function toggleUpgradeDoc(docId) {
  const idx = upgradeApplyForm.value.selected_doc_ids.indexOf(docId)
  if (idx === -1) upgradeApplyForm.value.selected_doc_ids.push(docId)
  else upgradeApplyForm.value.selected_doc_ids.splice(idx, 1)
}

function toggleAllUpgradeDocs() {
  if (upgradeApplyAllSelected.value) {
    upgradeApplyForm.value.selected_doc_ids = []
  } else {
    upgradeApplyForm.value.selected_doc_ids = upgradeApplyDocs.value.map(d => d.id)
  }
}

async function submitUpgradeApply() {
  if (!upgradeApplyForm.value.target_kb_id) { upgradeApplyError.value = '请选择目标知识库'; return }
  if (!upgradeApplyForm.value.selected_doc_ids.length) { upgradeApplyError.value = '请至少选择一个文档'; return }
  upgradeApplyError.value = ''
  upgradeApplyLoading.value = true
  const { ok, status, data } = await apiFetch('/api/rag/kbs/upgrade-requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_kb_id: upgradeApplyTarget.value.id,
      target_kb_id: Number(upgradeApplyForm.value.target_kb_id),
      doc_ids: upgradeApplyForm.value.selected_doc_ids,
      reason: upgradeApplyForm.value.reason,
    }),
  })
  upgradeApplyLoading.value = false
  if (!ok) { upgradeApplyError.value = data?.message || `提交失败（${status}）`; return }
  showUpgradeApplyDialog.value = false
}

async function openUpgradeHistory() {
  showUpgradeHistoryDialog.value = true
  upgradeHistoryLoading.value = true
  const { data } = await apiFetch('/api/rag/kbs/upgrade-requests')
  upgradeHistory.value = Array.isArray(data?.data) ? data.data : []
  upgradeHistoryLoading.value = false
}

function formatKbScope(kb) {
  if (kb.scope_type === 'personal') return '个人库'
  if (kb.scope_type === 'department') return '科室库'
  return '公共库'
}

function displayRisk(item) {
  if (typeof item === 'string') return item
  return item?.label || item?.text || item?.message || JSON.stringify(item)
}

async function fetchDocs(page = docsPage.value) {
  if (!manageSelectedKbId.value) {
    docs.value = []
    docsTotal.value = 0
    return
  }
  docsLoading.value = true
  docsPage.value = page
  const params = new URLSearchParams()
  params.set('kb_id', String(manageSelectedKbId.value))
  if (docSearch.value.trim()) params.set('search', docSearch.value.trim())
  params.set('page', String(docsPage.value))
  params.set('pageSize', String(docsPageSize.value))
  try {
    const { ok, data } = await apiFetch(`/api/rag/documents?${params.toString()}`)
    if (!ok) throw new Error(data?.message || data?.error || '加载文件失败')
    docs.value = Array.isArray(data?.data) ? data.data : []
    docsTotal.value = data?.total || 0
    selectedDocIds.value = selectedDocIds.value.filter(id => docs.value.some(doc => doc.id === id))
  } catch (error) {
    uploadError.value = error.message
  } finally {
    docsLoading.value = false
  }
}

function onDocSearch() {
  fetchDocs(1)
}

function toggleDocSelection(docId) {
  const i = selectedDocIds.value.indexOf(docId)
  if (i >= 0) selectedDocIds.value.splice(i, 1)
  else selectedDocIds.value.push(docId)
}

function selectAllDocs(checked) {
  selectedDocIds.value = checked ? docs.value.map(doc => doc.id) : []
}

function downloadDoc(doc) {
  const a = document.createElement('a')
  a.href = `/api/rag/documents/${doc.id}/download`
  a.download = doc.file_name || doc.title || `document-${doc.id}`
  a.click()
}

function downloadSelectedDocs() {
  const targets = docs.value.filter(doc => selectedDocIds.value.includes(doc.id))
  targets.forEach(doc => downloadDoc(doc))
}

async function openDocPreviewByDoc(doc) {
  docPreviewOpen.value = true
  docPreviewLoading.value = true
  docPreviewErr.value = ''
  docPreviewData.value = null
  docPreviewTitle.value = doc.title || doc.file_name || `文档 #${doc.id}`
  docPreviewChunkId.value = null
  docPreviewTab.value = 'raw'
  try {
    const { ok, data } = await apiFetch(`/api/rag/documents/${doc.id}/preview`)
    if (!ok) throw new Error(data?.message || data?.error || '加载预览失败')
    docPreviewData.value = data
  } catch (error) {
    docPreviewErr.value = error.message
  } finally {
    docPreviewLoading.value = false
  }
}

async function openSourcePreview(src) {
  if (!src.doc_id) return
  docPreviewOpen.value = true
  docPreviewLoading.value = true
  docPreviewErr.value = ''
  docPreviewData.value = null
  docPreviewTitle.value = src.title || `文档 #${src.doc_id}`
  docPreviewChunkId.value = src.chunk_id || null
  docPreviewTab.value = 'chunks'
  try {
    const qs = src.chunk_id ? `?chunk_id=${encodeURIComponent(src.chunk_id)}` : ''
    const { ok, data } = await apiFetch(`/api/rag/documents/${src.doc_id}/preview${qs}`)
    if (!ok) throw new Error(data?.message || data?.error || '加载失败')
    docPreviewData.value = data
  } catch (error) {
    docPreviewErr.value = error.message
  } finally {
    docPreviewLoading.value = false
  }
}

function closeDocPreview() {
  docPreviewOpen.value = false
  docPreviewData.value = null
  docPreviewErr.value = ''
}

function formatDate(value) {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}
</script>

<template>
  <div class="chat-workspace">
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <template v-if="!sidebarCollapsed">
      <div class="sidebar-header">
        <button class="new-chat-btn" @click="newConversation">
          <span class="new-chat-plus">⊕</span>
          <span>开启新对话</span>
        </button>
      </div>

      <div class="kb-summary-card">
        <div class="kb-select-label">当前知识库</div>
        <div class="kb-combobox" @focusout="setTimeout(() => { kbSelectOpen = false }, 120)">
          <input
            v-model="kbSearchText"
            class="kb-combobox-input"
            :placeholder="selectedKbSummary"
            @focus="focusKbSelect"
            @input="kbSelectOpen = true"
          />
          <span class="kb-combobox-arrow">⌄</span>
          <div v-if="kbSelectOpen" class="kb-combobox-menu">
            <button
              v-for="kb in filteredKnowledgeBases"
              :key="kb.id"
              class="kb-option"
              :class="{ selected: selectedKbIds.includes(kb.id) }"
              @mousedown.prevent="chooseKbFromSelect(kb.id)"
            >
              <span class="kb-option-main">{{ kb.name }}</span>
              <span class="kb-option-meta">{{ formatKbScope(kb) }} · {{ kb.doc_count || 0 }} 个文件</span>
              <span v-if="selectedKbIds.includes(kb.id)" class="kb-option-check">✓</span>
            </button>
            <div v-if="!filteredKnowledgeBases.length" class="kb-option-empty">未找到知识库</div>
          </div>
        </div>
        <div v-if="kbRequiredHint" class="error-tip">请先选择至少一个知识库再提问。</div>
      </div>

      <div class="conversation-panel">
        <div class="section-head">
          <span>最近会话</span>
          <span class="muted-text">仅显示通用问答</span>
        </div>
        <div class="conversation-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === activeConvId }"
            role="button"
            tabindex="0"
            @click="selectConversation(conv.id)"
            @keydown.enter.prevent="selectConversation(conv.id)"
            @keydown.space.prevent="selectConversation(conv.id)"
            @mouseenter="hoverConvId = conv.id"
            @mouseleave="hoverConvId = null"
          >
            <div class="conv-main">
              <template v-if="editingConvId === conv.id">
                <input
                  :data-conv-rename-input="conv.id"
                  v-model="editingConvTitle"
                  class="conv-title-input"
                  maxlength="200"
                  @click.stop
                  @keydown.enter.prevent="submitConversationRename(conv)"
                  @keydown.esc.prevent="cancelConversationRename"
                />
              </template>
              <template v-else>
                <div class="conv-title">{{ conv.title || '未命名会话' }}</div>
                <div class="conv-time">{{ formatDate(conv.updated_at || conv.created_at) }}</div>
              </template>
            </div>
            <div class="conv-actions" :class="{ visible: hoverConvId === conv.id }">
              <template v-if="editingConvId === conv.id">
                <button
                  class="icon-btn"
                  type="button"
                  title="保存会话名称"
                  :disabled="conversationActionId === conv.id"
                  @click.stop="submitConversationRename(conv)"
                >
                  ✓
                </button>
                <button
                  class="icon-btn"
                  type="button"
                  title="取消重命名"
                  :disabled="conversationActionId === conv.id"
                  @click.stop="cancelConversationRename"
                >
                  ✕
                </button>
              </template>
              <template v-else>
                <button
                  class="icon-btn"
                  type="button"
                  title="重命名会话"
                  :disabled="conversationActionId === conv.id"
                  @click.stop="startConversationRename(conv)"
                >
                  ✎
                </button>
                <button
                  class="icon-btn"
                  type="button"
                  title="删除会话"
                  :disabled="conversationActionId === conv.id"
                  @click.stop="deleteConversation(conv)"
                >
                  🗑
                </button>
              </template>
            </div>
          </div>
          <div v-if="!conversations.length" class="empty-note">暂无通用问答会话</div>
        </div>
      </div>

      <button class="manage-entry" :class="{ active: activeView === 'manage' }" @click="openManageView()">
        知识库管理
      </button>
      </template>
      <template v-else>
        <div class="collapsed-actions">
          <button class="collapsed-icon-btn" title="新建会话" @click="newConversation">✚</button>
          <button class="collapsed-icon-btn" title="知识库选择" @click="openKbDrawer">库</button>
          <button class="collapsed-icon-btn" title="知识库管理" @click="openManageView()">管</button>
        </div>
      </template>
    </aside>

    <div class="sidebar-divider">
      <button
        class="sidebar-toggle"
        :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
        @click="toggleSidebar"
      >
        {{ sidebarCollapsed ? '☰' : '◧' }}
      </button>
    </div>

    <section class="main-panel">
      <template v-if="activeView === 'chat'">
        <div class="main-toolbar">
          <div>
            <div class="page-title">{{ activeConv?.title || '知识问答' }}</div>
            <div class="page-subtitle">{{ selectedKbSummary }}</div>
          </div>
        </div>

        <div ref="msgContainer" class="message-board">
          <div v-if="!messages.length && !loading" class="message-empty">
            <div class="empty-title">开始新的通用知识问答</div>
            <div class="empty-note">可选择一个或多个知识库进行检索问答。</div>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
            <div class="msg-bubble">
              <div v-if="msg.content_markdown" class="msg-content" v-html="renderMd(msg.content_markdown)" />
              <div v-else-if="msg._streaming" class="streaming-hint">{{ msg._status || '正在检索知识库...' }}</div>

              <div v-if="msg.sources?.length" class="msg-section">
                <div class="msg-section-title">引用来源</div>
                <button
                  v-for="(src, si) in msg.sources"
                  :key="si"
                  class="source-item"
                  @click="openSourcePreview(src)"
                >
                  <div class="source-head">
                    <span>{{ src.title || `文档 #${src.doc_id}` }}</span>
                    <span v-if="src.score != null" class="source-score">{{ (src.score * 100).toFixed(0) }}%</span>
                  </div>
                  <div class="source-snippet">{{ src.snippet }}</div>
                </button>
              </div>

              <div v-if="msg.risk_highlights?.length" class="msg-section">
                <div class="risk-list">
                  <span v-for="(risk, ri) in msg.risk_highlights" :key="ri" class="risk-tag">⚠ {{ displayRisk(risk) }}</span>
                </div>
              </div>

              <div v-if="msg.disclaimer" class="msg-disclaimer">{{ msg.disclaimer }}</div>

              <div v-if="msg.role === 'assistant' && msg.id && !msg._streaming" class="msg-feedback">
                <button
                  class="feedback-btn"
                  :class="{ active: feedbackState[msg.id] === 'up' }"
                  :disabled="feedbackState[msg.id] === 'sending'"
                  @click="submitFeedback(msg, 'up')"
                >
                  👍 有帮助
                </button>
                <button
                  class="feedback-btn"
                  :class="{ active: feedbackState[msg.id] === 'down' }"
                  :disabled="feedbackState[msg.id] === 'sending'"
                  @click="submitFeedback(msg, 'down')"
                >
                  👎 需改进
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-if="quickTemplates.length" class="template-row">
          <button v-for="tpl in quickTemplates" :key="tpl.template_id" class="template-chip" @click="applyTemplate(tpl)">
            {{ tpl.name }}
          </button>
        </div>

        <div class="composer">
          <div class="composer-card">
            <textarea
              v-model="inputText"
              class="composer-input"
              placeholder="输入问题，按 Enter 发送，Shift + Enter 换行"
              @keydown="handleKeydown"
            />
            <button class="send-icon-btn" :disabled="loading" @click="sendMessage">↑</button>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="main-toolbar">
          <div>
            <div class="page-title">知识库管理</div>
            <div class="page-subtitle">查看可访问知识库及其文件</div>
          </div>
        </div>

        <div class="manage-layout">
          <div class="manage-kb-panel">
            <div class="section-head">
              <span>我的个人库</span>
              <button class="text-btn" @click="openUpgradeHistory">申请记录</button>
            </div>
            <div class="create-kb-card">
              <input v-model="kbForm.name" class="field-input" placeholder="新建个人知识库名称" />
              <input v-model="kbForm.description" class="field-input" placeholder="描述（可选）" />
              <div v-if="kbFormError" class="error-tip">{{ kbFormError }}</div>
              <button class="btn-primary small-btn" :disabled="kbFormLoading" @click="createPersonalKb">
                {{ kbFormLoading ? '创建中...' : '创建个人库' }}
              </button>
            </div>
            <div v-if="!personalKbs.length" class="empty-note">暂无个人知识库</div>
            <button
              v-for="kb in personalKbs"
              :key="kb.id"
              class="kb-card"
              :class="{ active: String(manageSelectedKbId) === String(kb.id) }"
              @click="manageSelectedKbId = kb.id; fetchDocs(1)"
            >
              <div class="kb-card-title-row">
                <span class="kb-card-title">{{ kb.name }}</span>
                <span class="kb-card-count">{{ kb.doc_count || 0 }}</span>
              </div>
              <div class="kb-card-desc">{{ kb.description || '无描述' }}</div>
              <div class="kb-card-actions">
                <span class="kb-scope">个人库</span>
                <button class="text-btn" @click.stop="openUpgradeApply(kb)">申请升级</button>
                <button class="text-btn danger-text" @click.stop="deletePersonalKb(kb)">删除</button>
              </div>
            </button>

            <div class="section-head with-top-gap"><span>科室库</span></div>
            <div v-if="!departmentKbs.length" class="empty-note">暂无科室知识库</div>
            <button
              v-for="kb in departmentKbs"
              :key="kb.id"
              class="kb-card"
              :class="{ active: String(manageSelectedKbId) === String(kb.id) }"
              @click="manageSelectedKbId = kb.id; fetchDocs(1)"
            >
              <div class="kb-card-title-row">
                <span class="kb-card-title">{{ kb.name }}</span>
                <span class="kb-card-count">{{ kb.doc_count || 0 }}</span>
              </div>
              <div class="kb-card-desc">{{ kb.description || '无描述' }}</div>
              <div class="kb-card-actions"><span class="kb-scope">科室库</span></div>
            </button>

            <div class="section-head with-top-gap"><span>公共库</span></div>
            <div v-if="!publicKbs.length" class="empty-note">暂无公共知识库</div>
            <button
              v-for="kb in publicKbs"
              :key="kb.id"
              class="kb-card"
              :class="{ active: String(manageSelectedKbId) === String(kb.id) }"
              @click="manageSelectedKbId = kb.id; fetchDocs(1)"
            >
              <div class="kb-card-title-row">
                <span class="kb-card-title">{{ kb.name }}</span>
                <span class="kb-card-count">{{ kb.doc_count || 0 }}</span>
              </div>
              <div class="kb-card-desc">{{ kb.description || '无描述' }}</div>
              <div class="kb-card-actions"><span class="kb-scope">公共库</span></div>
            </button>
          </div>

          <div class="manage-doc-panel">
            <div class="manage-doc-toolbar">
              <div>
                <div class="page-title small">{{ manageSelectedKb?.name || '请选择知识库' }}</div>
                <div class="page-subtitle">{{ manageSelectedKb ? formatKbScope(manageSelectedKb) : '选择左侧知识库后查看文件' }}</div>
              </div>
              <div class="toolbar-actions wrap">
                <input v-model="docSearch" class="field-input search-input" placeholder="搜索文件名" @keydown.enter="onDocSearch" />
                <button class="btn-secondary" @click="onDocSearch">搜索</button>
                <button class="btn-secondary" :disabled="!selectedDocIds.length" @click="downloadSelectedDocs">批量下载</button>
                <button
                  v-if="canUploadToManageKb"
                  class="btn-primary"
                  :disabled="uploadLoadingKbId === manageSelectedKbId"
                  @click="triggerUpload(manageSelectedKbId)"
                >
                  {{ uploadLoadingKbId === manageSelectedKbId ? '上传中...' : '上传文件' }}
                </button>
              </div>
            </div>

            <div v-if="uploadErrorKbId === manageSelectedKbId && uploadError" class="error-banner">{{ uploadError }}</div>

            <div v-if="!manageSelectedKbId" class="manage-empty">请先在左侧选择知识库。</div>
            <div v-else class="doc-table-wrap">
              <div v-if="docsLoading" class="manage-empty">加载中...</div>
              <div v-else-if="!docs.length" class="manage-empty">暂无文件</div>
              <template v-else>
                <table class="doc-table">
                  <thead>
                    <tr>
                      <th><input type="checkbox" :checked="selectedDocIds.length && selectedDocIds.length === docs.length" @change="selectAllDocs($event.target.checked)" /></th>
                      <th>文件名</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th>更新时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="doc in docs" :key="doc.id">
                      <td><input type="checkbox" :checked="selectedDocIds.includes(doc.id)" @change="toggleDocSelection(doc.id)" /></td>
                      <td>
                        <div class="doc-title">{{ doc.title }}</div>
                        <div class="doc-meta">{{ doc.file_name || `文档 #${doc.id}` }}</div>
                      </td>
                      <td>{{ doc.file_ext || '--' }}</td>
                      <td>{{ doc.status || '--' }}</td>
                      <td>{{ formatDate(doc.updated_at || doc.created_at) }}</td>
                      <td>
                        <div class="table-actions">
                          <button class="text-btn" @click="openDocPreviewByDoc(doc)">预览</button>
                          <button class="text-btn" @click="downloadDoc(doc)">下载</button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>

                <div class="pager">
                  <button class="btn-secondary" :disabled="docsPage <= 1" @click="fetchDocs(docsPage - 1)">上一页</button>
                  <span>第 {{ docsPage }} / {{ totalDocPages }} 页</span>
                  <button class="btn-secondary" :disabled="docsPage >= totalDocPages" @click="fetchDocs(docsPage + 1)">下一页</button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </template>
    </section>

    <input ref="fileInput" type="file" multiple hidden @change="handleUpload" />

    <!-- 升级申请弹层 -->
    <teleport to="body">
      <div v-if="showUpgradeApplyDialog" class="drawer-backdrop" @click.self="showUpgradeApplyDialog = false">
        <div class="upgrade-modal">
          <div class="drawer-header">
            <div class="page-title small">申请升级 — {{ upgradeApplyTarget?.name }}</div>
            <button class="close-btn" @click="showUpgradeApplyDialog = false">✕</button>
          </div>
          <p class="upgrade-hint">审批通过后，所选文档将被复制到目标知识库，个人库不变。</p>

          <div class="upgrade-field">
            <label class="upgrade-label">目标知识库 <span class="req">*</span></label>
            <select v-model="upgradeApplyForm.target_kb_id" class="field-input">
              <option value="">请选择科室库或公共库</option>
              <option v-for="kb in upgradeTargetKbs" :key="kb.id" :value="kb.id">
                {{ kb.name }}（{{ kb.scope_type === 'public' ? '公共' : '科室' }}）
              </option>
            </select>
            <p v-if="!upgradeTargetKbs.length" class="upgrade-hint">当前没有可用的科室库或公共库，请联系管理员</p>
          </div>

          <div class="upgrade-field">
            <label class="upgrade-label">选择要升级的文档 <span class="req">*</span></label>
            <div v-if="upgradeApplyDocsLoading" class="upgrade-hint">加载文档...</div>
            <div v-else-if="!upgradeApplyDocs.length" class="upgrade-hint">该知识库暂无文档</div>
            <div v-else class="upgrade-doc-list">
              <label class="upgrade-doc-item upgrade-doc-all">
                <input type="checkbox" :checked="upgradeApplyAllSelected" @change="toggleAllUpgradeDocs" />
                <span>全选（{{ upgradeApplyDocs.length }} 篇）</span>
              </label>
              <label v-for="doc in upgradeApplyDocs" :key="doc.id" class="upgrade-doc-item">
                <input
                  type="checkbox"
                  :checked="upgradeApplyForm.selected_doc_ids.includes(doc.id)"
                  @change="toggleUpgradeDoc(doc.id)"
                />
                <span class="upgrade-doc-title">{{ doc.title || doc.file_name }}</span>
                <span class="upgrade-doc-ext">.{{ doc.file_ext }}</span>
              </label>
            </div>
          </div>

          <div class="upgrade-field">
            <label class="upgrade-label">申请原因</label>
            <textarea v-model="upgradeApplyForm.reason" class="field-input" rows="2" placeholder="可选，说明升级理由" />
          </div>

          <p v-if="upgradeApplyError" class="error-tip">{{ upgradeApplyError }}</p>
          <div class="upgrade-footer">
            <button class="btn-secondary" @click="showUpgradeApplyDialog = false">取消</button>
            <button class="btn-primary" :disabled="upgradeApplyLoading" @click="submitUpgradeApply">
              {{ upgradeApplyLoading ? '提交中...' : '提交申请' }}
            </button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- 申请记录弹层 -->
    <teleport to="body">
      <div v-if="showUpgradeHistoryDialog" class="drawer-backdrop" @click.self="showUpgradeHistoryDialog = false">
        <div class="upgrade-history-modal">
          <div class="drawer-header">
            <div class="page-title small">我的升级申请记录</div>
            <button class="close-btn" @click="showUpgradeHistoryDialog = false">✕</button>
          </div>
          <div v-if="upgradeHistoryLoading" class="manage-empty">加载中...</div>
          <div v-else-if="!upgradeHistory.length" class="manage-empty">暂无申请记录</div>
          <div v-else class="upgrade-history-list">
            <div v-for="req in upgradeHistory" :key="req.id" class="upgrade-history-row">
              <div class="upgrade-history-main">
                <span class="upgrade-history-source">{{ req.source_kb_name || `库 #${req.source_kb_id}` }}</span>
                <span class="upgrade-history-arrow">→</span>
                <span class="upgrade-history-target">{{ req.target_kb_name || `库 #${req.target_kb_id}` }}</span>
                <span class="upgrade-history-docs">{{ req.doc_ids?.length ?? 0 }} 篇</span>
              </div>
              <div class="upgrade-history-meta">
                <span
                  class="upgrade-status-badge"
                  :class="{
                    'badge-pending': req.status === 'pending',
                    'badge-approved': req.status === 'approved',
                    'badge-rejected': req.status === 'rejected',
                  }"
                >
                  {{ req.status === 'pending' ? '待审批' : req.status === 'approved' ? '已批准' : '已拒绝' }}
                </span>
                <span v-if="req.review_comment" class="upgrade-history-comment">{{ req.review_comment }}</span>
                <span class="upgrade-history-time">{{ req.created_at ? new Date(req.created_at).toLocaleDateString() : '--' }}</span>
              </div>
            </div>
          </div>
          <div class="upgrade-footer">
            <button class="btn-secondary" @click="showUpgradeHistoryDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="kbDrawerOpen" class="drawer-backdrop" @click.self="kbDrawerOpen = false">
        <div class="drawer-panel">
          <div class="drawer-header">
            <div>
              <div class="page-title small">选择知识库</div>
              <div class="page-subtitle">可多选，用于当前通用问答</div>
            </div>
            <button class="close-btn" @click="kbDrawerOpen = false">✕</button>
          </div>
          <div v-if="kbLoading" class="manage-empty">加载中...</div>
          <div v-else class="drawer-body">
            <div class="drawer-section">
              <div class="section-head"><span>我的个人库</span></div>
              <label v-for="kb in personalKbs" :key="kb.id" class="drawer-kb-row">
                <input :checked="selectedKbIds.includes(kb.id)" type="checkbox" @change="toggleKb(kb.id)" />
                <div class="drawer-kb-info">
                  <div>{{ kb.name }}</div>
                  <div class="muted-text">{{ kb.doc_count || 0 }} 个文件</div>
                </div>
                <button class="text-btn" @click.prevent="openManageView(kb.id); kbDrawerOpen = false">管理</button>
              </label>
            </div>
            <div class="drawer-section">
              <div class="section-head"><span>科室库</span></div>
              <label v-for="kb in departmentKbs" :key="kb.id" class="drawer-kb-row">
                <input :checked="selectedKbIds.includes(kb.id)" type="checkbox" @change="toggleKb(kb.id)" />
                <div class="drawer-kb-info">
                  <div>{{ kb.name }}</div>
                  <div class="muted-text">{{ kb.doc_count || 0 }} 个文件</div>
                </div>
                <button class="text-btn" @click.prevent="openFileDrawer(kb.id); kbDrawerOpen = false">文件</button>
              </label>
            </div>
            <div class="drawer-section">
              <div class="section-head"><span>公共库</span></div>
              <label v-for="kb in publicKbs" :key="kb.id" class="drawer-kb-row">
                <input :checked="selectedKbIds.includes(kb.id)" type="checkbox" @change="toggleKb(kb.id)" />
                <div class="drawer-kb-info">
                  <div>{{ kb.name }}</div>
                  <div class="muted-text">{{ kb.doc_count || 0 }} 个文件</div>
                </div>
                <button class="text-btn" @click.prevent="openFileDrawer(kb.id); kbDrawerOpen = false">文件</button>
              </label>
            </div>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="fileDrawerOpen" class="drawer-backdrop" @click.self="fileDrawerOpen = false">
        <div class="drawer-panel wide-drawer">
          <div class="drawer-header">
            <div>
              <div class="page-title small">文件查看</div>
              <div class="page-subtitle">{{ manageSelectedKb?.name || '请选择知识库' }}</div>
            </div>
            <button class="close-btn" @click="fileDrawerOpen = false">✕</button>
          </div>
          <div class="drawer-toolbar">
            <select v-model="manageSelectedKbId" class="field-input select-input" @change="fetchDocs(1)">
              <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
            </select>
            <input v-model="docSearch" class="field-input search-input" placeholder="搜索文件名" @keydown.enter="onDocSearch" />
            <button class="btn-secondary" @click="onDocSearch">搜索</button>
          </div>
          <div class="drawer-body">
            <div v-if="docsLoading" class="manage-empty">加载中...</div>
            <div v-else-if="!docs.length" class="manage-empty">暂无文件</div>
            <div v-else class="drawer-doc-list">
              <div v-for="doc in docs" :key="doc.id" class="drawer-doc-row">
                <div class="drawer-doc-main">
                  <div class="doc-title">{{ doc.title }}</div>
                  <div class="doc-meta">{{ doc.file_ext || '--' }} · {{ formatDate(doc.updated_at || doc.created_at) }}</div>
                </div>
                <div class="table-actions">
                  <button class="text-btn" @click="openDocPreviewByDoc(doc)">预览</button>
                  <button class="text-btn" @click="downloadDoc(doc)">下载</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="docPreviewOpen" class="drawer-backdrop" @click.self="closeDocPreview">
        <div class="preview-modal">
          <div class="drawer-header">
            <div class="page-title small">{{ docPreviewTitle }}</div>
            <button class="close-btn" @click="closeDocPreview">✕</button>
          </div>
          <div v-if="docPreviewLoading" class="manage-empty">加载中...</div>
          <div v-else-if="docPreviewErr" class="error-banner">{{ docPreviewErr }}</div>
          <template v-else-if="docPreviewData">
            <div class="preview-meta">
              <span>版本 v{{ docPreviewData.version_no || '--' }}</span>
              <span>模型 {{ docPreviewData.embedding_model || '--' }}</span>
              <span>{{ docPreviewData.chunk_count || 0 }} chunks</span>
            </div>
            <div class="preview-tabs">
              <button class="preview-tab" :class="{ active: docPreviewTab === 'raw' }" @click="docPreviewTab = 'raw'">原始文本</button>
              <button class="preview-tab" :class="{ active: docPreviewTab === 'clean' }" @click="docPreviewTab = 'clean'">清洗文本</button>
              <button class="preview-tab" :class="{ active: docPreviewTab === 'chunks' }" @click="docPreviewTab = 'chunks'">Chunks</button>
            </div>
            <div class="preview-body">
              <div v-show="docPreviewTab === 'raw'" class="preview-text"><pre>{{ docPreviewData.raw_text_preview || '暂无原始文本' }}</pre></div>
              <div v-show="docPreviewTab === 'clean'" class="preview-text"><pre>{{ docPreviewData.cleaned_text_preview || '暂无清洗文本' }}</pre></div>
              <div v-show="docPreviewTab === 'chunks'" class="preview-chunk-list">
                <div v-if="!docPreviewData.chunks_preview?.length" class="manage-empty">暂无 Chunk 数据</div>
                <div
                  v-for="chunk in docPreviewData.chunks_preview || []"
                  :key="chunk.chunk_index"
                  class="preview-chunk-item"
                  :class="{ hit: chunk.is_hit || chunk.chunk_id === docPreviewChunkId }"
                >
                  <div class="preview-chunk-head">
                    <span>{{ chunk.chunk_id }}</span>
                    <span>{{ (chunk.text || '').length }} 字</span>
                  </div>
                  <div class="preview-chunk-text">{{ chunk.text }}</div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.chat-workspace {
  display: flex;
  height: calc(100vh - 52px);
  min-height: calc(100vh - 52px);
  max-height: calc(100vh - 52px);
  padding: 26px 32px 32px;
  gap: 0;
  overflow: hidden;
  background: #f4f9ff;
  color: #16324f;
  font-size: 14px;
}

.sidebar {
  width: 237px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 4px 18px 4px 0;
  border-right: none;
  background: transparent;
  transition: width 0.2s ease, padding 0.2s ease;
}

.sidebar.collapsed {
  width: 56px;
  padding-right: 8px;
}

.sidebar-header,
.kb-summary-card,
.conversation-panel,
.manage-entry,
.main-panel,
.drawer-panel,
.preview-modal,
.kb-card,
.create-kb-card {
  border-radius: 16px;
  background: transparent;
  border: none;
  box-shadow: none;
  backdrop-filter: none;
}

.sidebar-header,
.kb-summary-card,
.conversation-panel {
  padding: 8px 10px 0;
}

.sidebar-title,
.page-title {
  font-size: 17px;
  font-weight: 700;
  color: #16324f;
  line-height: 1.3;
}

.page-title.small {
  font-size: 15px;
}

.main-toolbar > div:first-child .page-title {
  border-left: 3px solid #19c6d0;
  padding-left: 10px;
  font-weight: 700;
}

.sidebar-subtitle,
.page-subtitle,
.muted-text,
.empty-note,
.doc-meta,
.conv-time,
.kb-card-desc,
.msg-disclaimer {
  color: #6b7280;
  font-size: 12.5px;
}

.sidebar-title {
  margin-bottom: 2px;
}

.new-chat-btn {
  width: 100%;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid rgba(109, 145, 186, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  color: #334155;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 8px 22px rgba(95,130,171,0.08);
  transition: all 0.2s ease;
}

.new-chat-btn:hover {
  background: #fff;
  color: #2563eb;
  border-color: rgba(37, 99, 235, 0.24);
}

.new-chat-plus {
  color: #64748b;
  font-size: 14px;
}

.page-subtitle {
  color: #7d94ad;
  margin-top: 6px;
  padding-left: 15px;
}

.btn-primary,
.btn-secondary,
.text-btn,
.manage-entry,
.conv-item,
.source-item,
.composer-link,
.template-chip,
.preview-tab {
  transition: all 0.2s ease;
}

.btn-primary,
.btn-secondary,
.manage-entry {
  border: none;
  cursor: pointer;
  font-weight: 600;
}

.btn-primary {
  background: #fff;
  color: #2563eb;
  padding: 8px 12px;
  border-radius: 12px;
  border: 1px solid rgba(37,99,235,0.16);
  box-shadow: none;
}

.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-secondary {
  background: #fff;
  color: #2563eb;
  border: 1px solid rgba(37,99,235,0.16);
  padding: 8px 12px;
  border-radius: 12px;
}

.small-btn {
  width: 100%;
}

.text-btn {
  border: none;
  background: transparent;
  color: #4f46e5;
  cursor: pointer;
  padding: 0;
}

.danger-text {
  color: #dc2626;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13.5px;
  font-weight: 600;
}

.with-top-gap {
  margin-top: 18px;
}

.kb-summary-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
}

.kb-select-label {
  font-size: 13px;
  font-weight: 600;
  color: #16324f;
}

.kb-combobox {
  position: relative;
}

.kb-combobox-input {
  width: 100%;
  height: 38px;
  border: 1px solid rgba(109,145,186,0.18);
  border-radius: 12px;
  padding: 0 34px 0 12px;
  background: rgba(255,255,255,0.78);
  color: #16324f;
  font: inherit;
  outline: none;
  box-shadow: 0 8px 18px rgba(95,130,171,0.04);
}

.kb-combobox-input::placeholder {
  color: #6b7280;
  opacity: 1;
}

.kb-combobox-input:focus {
  border-color: rgba(37,99,235,0.28);
  background: #fff;
}

.kb-combobox-arrow {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-55%);
  color: #94a3b8;
  pointer-events: none;
}

.kb-combobox-menu {
  position: absolute;
  z-index: 20;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  max-height: 260px;
  overflow-y: auto;
  padding: 6px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(109,145,186,0.14);
  box-shadow: 0 18px 36px rgba(95,130,171,0.16);
}

.kb-option {
  position: relative;
  width: 100%;
  border: 0;
  border-radius: 10px;
  background: transparent;
  padding: 8px 28px 8px 10px;
  text-align: left;
  cursor: pointer;
}

.kb-option:hover,
.kb-option.selected {
  background: #eef4ff;
}

.kb-option-main {
  display: block;
  color: #16324f;
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-option-meta {
  display: block;
  margin-top: 3px;
  color: #8a9bb0;
  font-size: 12px;
}

.kb-option-check {
  position: absolute;
  right: 10px;
  top: 12px;
  color: #2563eb;
  font-weight: 700;
}

.kb-option-empty {
  padding: 12px;
  color: #94a3b8;
  font-size: 12.5px;
}

.kb-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.kb-chip,
.risk-tag,
.kb-scope {
  display: inline-flex;
  align-items: center;
  padding: 2px 0;
  border-radius: 0;
  background: transparent;
  color: #2563eb;
  font-size: 12px;
}

.error-tip,
.error-banner {
  color: #b91c1c;
  font-size: 12.5px;
}

.error-banner {
  padding: 10px 12px;
  border-radius: 12px;
  background: #fef2f2;
}

.conversation-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: 6px;
}

.conversation-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conv-item {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 14px;
  text-align: left;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
}

.conv-item:hover,
.conv-item.active {
  border-color: rgba(47,111,237,0.12);
  background: rgba(255,255,255,0.56);
}

.conv-main {
  min-width: 0;
  flex: 1;
}

.conv-title,
.doc-title,
.kb-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #16324f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-title-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(37, 99, 235, 0.28);
  border-radius: 10px;
  background: #ffffff;
  color: #16324f;
  font-size: 13px;
  outline: none;
}

.conv-title-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.conv-actions {
  display: flex;
  gap: 6px;
  opacity: 0;
}

.conv-actions.visible {
  opacity: 1;
}

.icon-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(255,255,255,0.9);
  border: none;
  color: #64748b;
  cursor: pointer;
}

.icon-btn:disabled,
.icon-btn.disabled {
  color: #9ca3af;
  cursor: not-allowed;
}

.manage-entry {
  margin-top: auto;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.62);
  color: #52708e;
  text-align: center;
  border: 1px solid rgba(109, 145, 186, 0.1);
  box-shadow: 0 10px 24px rgba(95,130,171,0.06);
}

.manage-entry.active,
.manage-entry:hover {
  background: #fff;
  color: #2563eb;
}

.collapsed-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 10px;
}

.collapsed-icon-btn {
  width: 40px;
  height: 40px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  border-radius: 12px;
  background: rgba(255,255,255,0.7);
  color: #52708e;
  cursor: pointer;
}

.sidebar-divider {
  width: 1px;
  align-self: stretch;
  background: rgba(109,145,186,0.18);
  position: relative;
  margin: 0 16px 0 2px;
}

.sidebar-toggle {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  width: 34px;
  height: 34px;
  border: 1px solid rgba(109,145,186,0.16);
  border-radius: 12px;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(95,130,171,0.08);
  font-size: 16px;
}

.main-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
}

.main-toolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-actions.wrap {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.message-board {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px 8px 0;
}

.message-empty,
.manage-empty {
  height: 100%;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  color: #94a3b8;
}

.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: #475569;
}

.msg-row {
  display: flex;
  margin-bottom: 16px;
}

.msg-row.user {
  justify-content: flex-end;
}

.msg-row.assistant {
  justify-content: flex-start;
}

.msg-bubble {
  max-width: min(880px, 82%);
  padding: 13px 15px;
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 12px 28px rgba(95, 130, 171, 0.08);
}

.msg-row.user .msg-bubble {
  background: #ffffff;
  color: #16324f;
  border-color: rgba(109, 145, 186, 0.12);
}

.msg-content :deep(p:first-child) {
  margin-top: 0;
}

.msg-content :deep(p:last-child) {
  margin-bottom: 0;
}

.msg-section {
  margin-top: 12px;
}

.msg-section-title {
  margin-bottom: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
}

.source-item {
  width: 100%;
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
  padding: 8px 10px;
  cursor: pointer;
  margin-bottom: 8px;
}

.source-item:hover {
  border-color: rgba(47,111,237,0.24);
  background: #eff6ff;
}

.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
}

.source-score {
  color: #4f46e5;
}

.source-snippet {
  margin-top: 6px;
  font-size: 12.5px;
  color: #64748b;
}

.risk-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.msg-row.user .msg-disclaimer,
.msg-row.user .source-item,
.msg-row.user .risk-tag {
  color: inherit;
}

.msg-feedback {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.feedback-btn {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #2563eb;
  padding: 7px 9px;
  border-radius: 10px;
  cursor: pointer;
}

.feedback-btn.active {
  border-color: #1d4ed8;
}

.streaming-hint {
  color: #64748b;
}

.template-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.template-chip {
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #4b5563;
  padding: 7px 10px;
  border-radius: 999px;
  cursor: pointer;
}

.template-chip:hover {
  border-color: #c7d2fe;
  color: #4338ca;
}

.composer {
  margin-top: 12px;
}

.composer-card {
  position: relative;
  border: 1px solid rgba(109,145,186,0.16);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(95,130,171,0.06);
  padding: 14px 56px 14px 18px;
}

.composer-input,
.field-input,
.select-input {
  width: 100%;
  border: 1px solid rgba(109,145,186,0.18);
  border-radius: 14px;
  padding: 12px 14px;
  font: inherit;
  background: #fff;
  color: #16324f;
}

.composer-input {
  min-height: 58px;
  max-height: 132px;
  resize: none;
  border: none;
  padding: 0;
  outline: none;
  box-shadow: none;
  line-height: 1.55;
}

.search-input {
  min-width: 220px;
}

.composer-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 12px;
}

.composer-link {
  border: none;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  padding: 0;
  font-size: 12.5px;
}

.composer-link:last-of-type {
  margin-right: auto;
}

.send-icon-btn {
  position: absolute;
  right: 16px;
  bottom: 14px;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  border: none;
  background: #e8edff;
  color: #4f46e5;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.send-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.manage-layout {
  display: flex;
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.manage-kb-panel {
  width: 290px;
  flex-shrink: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.manage-doc-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.create-kb-card {
  border: 1px solid #eef2f7;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.kb-card {
  width: 100%;
  text-align: left;
  border: 1px solid #e5e7eb;
  padding: 11px 12px;
  margin-bottom: 8px;
  cursor: pointer;
}

.kb-card.active,
.kb-card:hover {
  border-color: rgba(47,111,237,0.22);
  background: #eff6ff;
}

.kb-card-title-row,
.kb-card-actions,
.manage-doc-toolbar,
.preview-meta,
.preview-chunk-head,
.drawer-header,
.drawer-toolbar,
.drawer-kb-row,
.drawer-doc-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.kb-card-count {
  color: #4338ca;
  font-size: 12.5px;
}

.doc-table-wrap {
  flex: 1;
  min-height: 0;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  background: #fff;
  overflow: hidden;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
}

.doc-table th,
.doc-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
  font-size: 12.5px;
}

.doc-table th {
  background: #f7fbff;
  color: #64748b;
  font-weight: 600;
}

.table-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.pager {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  padding: 12px;
}

.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 2000;
}

.drawer-backdrop-transparent {
  background: transparent;
}

.drawer-backdrop-left {
  justify-content: flex-start;
}

.drawer-panel,
.preview-modal {
  width: 420px;
  height: 100%;
  padding: 20px;
  border-radius: 0;
  background: #fff;
  display: flex;
  flex-direction: column;
}

.wide-drawer {
  width: 620px;
}

.preview-modal {
  width: min(860px, 92vw);
  height: min(88vh, 860px);
  margin: auto;
  border-radius: 20px;
}

.drawer-body,
.preview-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.drawer-section {
  margin-bottom: 20px;
}

.drawer-kb-row,
.drawer-doc-row {
  width: 100%;
  padding: 12px 0;
  border-bottom: 1px solid #eef2f7;
}

.drawer-kb-info,
.drawer-doc-main {
  flex: 1;
  min-width: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 10px;
  background: #f3f4f6;
  cursor: pointer;
}

.preview-tabs {
  display: flex;
  gap: 8px;
  padding: 12px 0;
}

.preview-tab {
  border: 1px solid #e5e7eb;
  background: #fff;
  padding: 8px 12px;
  border-radius: 999px;
  cursor: pointer;
}

.preview-tab.active {
  border-color: #2f6fed;
  color: #2563eb;
  background: #eef2ff;
}

.preview-text pre,
.preview-chunk-text {
  white-space: pre-wrap;
  word-break: break-word;
  color: #334155;
  line-height: 1.7;
}

.preview-chunk-item {
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 12px;
  margin-bottom: 10px;
}

.preview-chunk-item.hit {
  border-color: #a5b4fc;
  background: #eef2ff;
}

.upgrade-modal {
  width: 480px;
  max-width: 92vw;
  max-height: 88vh;
  overflow-y: auto;
  margin: auto;
  padding: 22px 24px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.16);
  display: flex;
  flex-direction: column;
}

.upgrade-history-modal {
  width: 560px;
  max-width: 92vw;
  max-height: 88vh;
  overflow-y: auto;
  margin: auto;
  padding: 22px 24px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.16);
  display: flex;
  flex-direction: column;
}

.upgrade-hint { font-size: 12.5px; color: #6b7280; margin: 6px 0 14px; }
.upgrade-field { margin-top: 14px; }
.upgrade-label { display: block; font-size: 13px; font-weight: 600; color: #16324f; margin-bottom: 6px; }
.req { color: #dc2626; }

.upgrade-doc-list {
  border: 1px solid rgba(109,145,186,0.18);
  border-radius: 12px;
  max-height: 200px;
  overflow-y: auto;
}

.upgrade-doc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 13px;
  color: #334155;
}

.upgrade-doc-item:hover { background: #f8fafc; }
.upgrade-doc-item input { flex-shrink: 0; cursor: pointer; }
.upgrade-doc-all { border-bottom: 1px solid rgba(109,145,186,0.14); font-weight: 600; color: #475569; }
.upgrade-doc-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upgrade-doc-ext { font-size: 11px; color: #94a3b8; flex-shrink: 0; }
.upgrade-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }

.upgrade-history-list { overflow-y: auto; margin-top: 8px; }

.upgrade-history-row {
  padding: 12px 0;
  border-bottom: 1px solid #eef2f7;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upgrade-history-main { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.upgrade-history-source, .upgrade-history-target { font-weight: 600; color: #16324f; }
.upgrade-history-arrow { color: #94a3b8; }
.upgrade-history-docs { font-size: 12px; color: #94a3b8; margin-left: auto; }
.upgrade-history-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.upgrade-history-comment { font-size: 12px; color: #64748b; }
.upgrade-history-time { font-size: 11.5px; color: #94a3b8; white-space: nowrap; }

.upgrade-status-badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.badge-pending  { background: #fef9c3; color: #854d0e; }
.badge-approved { background: #dcfce7; color: #166534; }
.badge-rejected { background: #fee2e2; color: #991b1b; }

@media (max-width: 1200px) {
  .chat-workspace {
    flex-direction: column;
    height: auto;
    min-height: 100vh;
    padding: 18px;
  }

  .sidebar {
    width: auto;
    padding-right: 0;
  }

  .sidebar.collapsed {
    width: auto;
    padding-right: 0;
  }

  .sidebar-divider {
    width: 100%;
    height: 1px;
    margin: 10px 0;
  }

  .sidebar-toggle {
    left: auto;
    right: 10px;
    top: 50%;
    transform: translateY(-50%);
  }

  .manage-layout {
    flex-direction: column;
  }

  .manage-kb-panel {
    width: auto;
  }

  .main-toolbar,
  .manage-doc-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .msg-bubble {
    max-width: 100%;
  }
}
</style>
