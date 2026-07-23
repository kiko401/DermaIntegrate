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

// sidebar state
const activeTab = ref('conv')
const expandedKbId = ref(null)
const newKbOpen = ref(false)

const conversations = ref([])
const activeConvId = ref(null)
const messages = ref([])
const knowledgeBases = ref([])
const selectedKbIds = ref([])
const inputText = ref('')
const loading = ref(false)
const kbLoading = ref(false)
const msgContainer = ref(null)

const kbForm = ref({ name: '', description: '' })
const kbFormLoading = ref(false)
const kbFormError = ref('')

const fileInput = ref(null)
const uploadTargetKbId = ref(null)
const uploadLoadingKbId = ref(null)
const uploadError = ref('')
const uploadErrorKbId = ref(null)

const activeConv = computed(() => conversations.value.find(c => c.id === activeConvId.value))
const personalKbs = computed(() =>
  knowledgeBases.value.filter(kb => kb.scope_type === 'personal' && kb.scope_owner_id === doctorInfo.value.id)
)
const sharedKbs = computed(() =>
  knowledgeBases.value.filter(kb => !(kb.scope_type === 'personal' && kb.scope_owner_id === doctorInfo.value.id))
)

onMounted(async () => {
  await Promise.all([refreshConversations(), refreshKnowledgeBases()])
  if (conversations.value.length) await selectConversation(conversations.value[0].id)
})

async function refreshConversations() {
  const { data } = await apiFetch('/api/rag/conversations')
  conversations.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
}

async function refreshKnowledgeBases() {
  kbLoading.value = true
  try {
    const { data } = await apiFetch('/api/rag/kbs')
    knowledgeBases.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
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
  await selectConversation(data.id)
}

async function selectConversation(id) {
  activeConvId.value = id
  messages.value = []
  const { data } = await apiFetch(`/api/rag/conversations/${id}/messages`)
  messages.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  scrollToBottom()
}

const kbRequiredHint = ref(false)

async function sendMessage() {
  const question = inputText.value.trim()
  if (!question || loading.value) return
  if (!selectedKbIds.value.length) {
    kbRequiredHint.value = true
    activeTab.value = 'kb'
    return
  }
  kbRequiredHint.value = false
  if (!activeConvId.value) await newConversation()

  messages.value.push({ role: 'user', content_markdown: question, created_at: new Date().toISOString() })
  inputText.value = ''
  loading.value = true
  scrollToBottom()

  // Placeholder for streaming assistant reply
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

      // Process complete SSE blocks separated by \n\n
      const blocks = sseBuffer.split(/\n\n/)
      sseBuffer = blocks.pop() // keep incomplete trailing block

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
        } else if (eventType === 'disclaimer') {
          msg.disclaimer = payload.disclaimer
        } else if (eventType === 'progress') {
          // Show intermediate status text while streaming
          if (!msg.content_markdown && payload.step) {
            msg._status = payload.step
          }
        } else if (eventType === 'error') {
          msg.content_markdown = `请求失败：${payload.message || payload.code}`
          msg._streaming = false
        }
        scrollToBottom()
      }
    }

    // Mark done if result event never arrived (e.g. upstream closed early)
    if (messages.value[assistantIdx]._streaming) {
      messages.value[assistantIdx]._streaming = false
    }
  } catch (error) {
    messages.value[assistantIdx].content_markdown = `请求失败：${error.message}`
    messages.value[assistantIdx]._streaming = false
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => { if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight })
}

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage() }
}

function toggleKb(id) {
  const i = selectedKbIds.value.indexOf(id)
  if (i >= 0) selectedKbIds.value.splice(i, 1)
  else selectedKbIds.value.push(id)
  if (selectedKbIds.value.length) kbRequiredHint.value = false
}

function toggleExpand(kbId) {
  expandedKbId.value = expandedKbId.value === kbId ? null : kbId
}

function toggleNewKb() {
  newKbOpen.value = !newKbOpen.value
  if (!newKbOpen.value) { kbForm.value = { name: '', description: '' }; kbFormError.value = '' }
}

async function createPersonalKb() {
  if (!kbForm.value.name.trim()) { kbFormError.value = '请输入知识库名称'; return }
  kbFormLoading.value = true
  kbFormError.value = ''
  try {
    const { ok, status, data } = await apiFetch('/api/rag/kbs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: kbForm.value.name.trim(), description: kbForm.value.description.trim(), scope_type: 'personal' }),
    })
    if (!ok) {
      if (status === 409) throw new Error('知识库名称已存在')
      throw new Error(data?.message || data?.error || '创建失败')
    }
    kbForm.value = { name: '', description: '' }
    newKbOpen.value = false
    await refreshKnowledgeBases()
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
  if (expandedKbId.value === kb.id) expandedKbId.value = null
  selectedKbIds.value = selectedKbIds.value.filter(id => id !== kb.id)
  await refreshKnowledgeBases()
}

function displayRisk(item) {
  if (typeof item === 'string') return item
  return item?.label || item?.text || item?.message || JSON.stringify(item)
}
</script>

<template>
  <div class="chat-workspace">
    <aside class="sidebar">

      <!-- Tab 切换 -->
      <div class="sidebar-tabs">
        <button class="tab-btn" :class="{ active: activeTab === 'conv' }" @click="activeTab = 'conv'">
          会话
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'kb' }" @click="activeTab = 'kb'">
          知识库
          <span v-if="selectedKbIds.length" class="tab-badge">{{ selectedKbIds.length }}</span>
        </button>
      </div>

      <!-- 会话 Tab -->
      <div v-show="activeTab === 'conv'" class="tab-content">
        <div class="tab-header">
          <button class="btn-new" @click="newConversation">+ 新建会话</button>
        </div>
        <div class="conv-list">
          <div
            v-for="conv in conversations" :key="conv.id"
            class="conv-item" :class="{ active: conv.id === activeConvId }"
            @click="selectConversation(conv.id)"
          >
            <span class="conv-title">{{ conv.title || '未命名会话' }}</span>
            <span class="conv-date">{{ new Date(conv.created_at).toLocaleDateString() }}</span>
          </div>
          <div v-if="!conversations.length" class="empty-hint">暂无会话</div>
        </div>
      </div>

      <!-- 知识库 Tab -->
      <div v-show="activeTab === 'kb'" class="tab-content">
        <div class="tab-header">
          <button class="btn-new" @click="toggleNewKb">
            {{ newKbOpen ? '取消' : '+ 新建个人库' }}
          </button>
        </div>

        <!-- 新建表单（内联，不弹窗） -->
        <div v-if="newKbOpen" class="new-kb-form">
          <input
            v-model="kbForm.name" class="field-input" placeholder="知识库名称"
            @keydown.enter="createPersonalKb"
          />
          <input v-model="kbForm.description" class="field-input" placeholder="描述（可选）" />
          <div v-if="kbFormError" class="error-tip">{{ kbFormError }}</div>
          <button class="btn-confirm" :disabled="kbFormLoading" @click="createPersonalKb">
            {{ kbFormLoading ? '创建中...' : '确认创建' }}
          </button>
        </div>

        <div class="kb-scroll">
          <div v-if="kbLoading" class="empty-hint">加载中...</div>
          <template v-else>

          <!-- 我的个人库 -->
          <div class="kb-section-label">我的个人库</div>
          <div v-if="!personalKbs.length" class="empty-hint">还没有个人知识库</div>

          <div v-for="kb in personalKbs" :key="kb.id" class="kb-group">
            <div class="kb-item" :class="{ selected: selectedKbIds.includes(kb.id) }">
              <span class="kb-dot" @click="toggleKb(kb.id)" />
              <span class="kb-name" @click="toggleKb(kb.id)">{{ kb.name }}</span>
              <span class="kb-count">{{ kb.doc_count || 0 }}</span>
              <button class="kb-expand-btn" @click="toggleExpand(kb.id)">
                {{ expandedKbId === kb.id ? '▾' : '▸' }}
              </button>
            </div>

            <!-- 展开：上传 / 删除 -->
            <div v-if="expandedKbId === kb.id" class="kb-detail">
              <p v-if="kb.description" class="kb-detail-desc">{{ kb.description }}</p>
              <div v-if="uploadErrorKbId === kb.id && uploadError" class="error-tip">{{ uploadError }}</div>
              <div class="kb-detail-actions">
                <button
                  class="btn-sm"
                  :disabled="uploadLoadingKbId === kb.id"
                  @click="triggerUpload(kb.id)"
                >
                  {{ uploadLoadingKbId === kb.id ? '上传中...' : '上传文档' }}
                </button>
                <button class="btn-sm btn-danger" @click="deletePersonalKb(kb)">删除</button>
              </div>
            </div>
          </div>

          <!-- 公共 / 科室库 -->
          <template v-if="sharedKbs.length">
            <div class="kb-section-label" style="margin-top: 12px;">公共 / 科室库</div>
            <div
              v-for="kb in sharedKbs" :key="kb.id"
              class="kb-item" :class="{ selected: selectedKbIds.includes(kb.id) }"
              @click="toggleKb(kb.id)"
            >
              <span class="kb-dot" />
              <span class="kb-name">{{ kb.name }}</span>
              <span class="kb-count">{{ kb.doc_count || 0 }}</span>
              <span class="kb-scope-tag">{{ kb.scope_type === 'public' ? '公开' : '科室' }}</span>
            </div>
          </template>

          </template>
        </div>
      </div>

    </aside>

    <!-- 聊天主区域 -->
    <div class="chat-main">
      <div class="chat-header">
        <span class="chat-title">{{ activeConv?.title || '知识库问答' }}</span>
        <span v-if="selectedKbIds.length" class="kb-badge">{{ selectedKbIds.length }} 个知识库</span>
      </div>

      <div ref="msgContainer" class="msg-list">
        <div v-if="!messages.length && !loading" class="msg-empty">发送问题，从知识库中获取回答</div>
        <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
          <div class="msg-bubble" :class="{ loading: msg._streaming && !msg.content_markdown }">
            <div v-if="msg.content_markdown" class="msg-content" v-html="renderMd(msg.content_markdown)" />
            <span v-else-if="msg._streaming" class="streaming-hint">{{ msg._status || '正在检索知识库...' }}</span>

            <div v-if="msg.sources?.length" class="msg-sources">
              <div class="sources-label">引用来源</div>
              <div v-for="(src, si) in msg.sources" :key="si" class="source-item">
                <span class="source-title">{{ src.title || `文档#${src.doc_id}` }}</span>
                <span v-if="src.score != null" class="source-score">[{{ (src.score * 100).toFixed(0) }}%]</span>
                <span class="source-snippet">{{ src.snippet }}</span>
              </div>
            </div>

            <div v-if="msg.risk_highlights?.length" class="msg-risks">
              <span v-for="(risk, ri) in msg.risk_highlights" :key="ri" class="risk-tag">
                ⚠ {{ displayRisk(risk) }}
              </span>
            </div>

            <div v-if="msg.disclaimer" class="msg-disclaimer">{{ msg.disclaimer }}</div>
          </div>
        </div>

        <div v-if="loading && !messages.some(m => m._streaming)" class="msg-row assistant">
          <div class="msg-bubble loading">正在检索知识库...</div>
        </div>
      </div>

      <div class="input-bar">
        <div v-if="kbRequiredHint" class="kb-hint">请先在左侧「知识库」标签中选择至少一个知识库</div>
        <div class="input-row">
          <textarea
            v-model="inputText"
            class="input-box"
            placeholder="输入问题，按 Enter 发送（Shift+Enter 换行）"
            :disabled="loading"
            rows="3"
            @keydown="handleKeydown"
          />
          <button class="btn-send" :disabled="loading || !inputText.trim()" @click="sendMessage">
            发送
          </button>
        </div>
      </div>
    </div>

    <input
      ref="fileInput"
      type="file"
      multiple
      style="display:none"
      accept=".txt,.md,.pdf,.docx,.csv,.xlsx,.xls"
      @change="handleUpload"
    />
  </div>
</template>

<style scoped>
.chat-workspace { display: flex; height: calc(100vh - 52px); overflow: hidden; }

/* ── 侧栏 ── */
.sidebar { width: 260px; min-width: 220px; border-right: 1px solid #e2e8f0; background: #fff; display: flex; flex-direction: column; }

.sidebar-tabs { display: flex; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; }
.tab-btn { flex: 1; padding: 10px 4px; border: none; background: none; font-size: 13px; color: #64748b; cursor: pointer; position: relative; border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; }
.tab-btn:hover { color: #334155; }
.tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }
.tab-badge { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 8px; background: #2563eb; color: #fff; font-size: 10px; font-weight: 700; margin-left: 4px; }

.tab-content { display: flex; flex-direction: column; flex: 1; overflow: hidden; }
.tab-header { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; flex-shrink: 0; }

/* 会话 tab */
.conv-list { flex: 1; overflow-y: auto; padding: 6px 0; }
.conv-item { padding: 9px 14px; cursor: pointer; transition: background 0.1s; }
.conv-item:hover { background: #f8fafc; }
.conv-item.active { background: #eff6ff; }
.conv-title { display: block; font-size: 13px; color: #334155; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.conv-date { display: block; font-size: 11px; color: #94a3b8; margin-top: 2px; }

/* 知识库 tab */
.new-kb-form { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
.kb-scroll { flex: 1; overflow-y: auto; padding: 8px 0; }
.kb-section-label { font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.06em; padding: 4px 14px 4px; }

.kb-group { }
.kb-item { display: flex; align-items: center; gap: 6px; padding: 6px 14px; cursor: pointer; transition: background 0.1s; }
.kb-item:hover { background: #f8fafc; }
.kb-item.selected { background: #eff6ff; }
.kb-dot { width: 7px; height: 7px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0; transition: background 0.15s; }
.kb-item.selected .kb-dot { background: #2563eb; }
.kb-name { flex: 1; font-size: 13px; color: #334155; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.kb-item.selected .kb-name { color: #2563eb; }
.kb-count { font-size: 11px; color: #94a3b8; flex-shrink: 0; }
.kb-expand-btn { border: none; background: none; color: #94a3b8; cursor: pointer; font-size: 11px; padding: 0 2px; flex-shrink: 0; line-height: 1; }
.kb-expand-btn:hover { color: #334155; }
.kb-scope-tag { font-size: 10px; padding: 1px 5px; border-radius: 4px; background: #f1f5f9; color: #64748b; flex-shrink: 0; }

.kb-detail { margin: 0 14px 4px; padding: 8px 10px; background: #f8fafc; border-radius: 6px; border: 1px solid #f1f5f9; }
.kb-detail-desc { font-size: 12px; color: #64748b; margin: 0 0 8px; }
.kb-detail-actions { display: flex; gap: 6px; }

/* ── 공통 버튼 ── */
.btn-new { width: 100%; font-size: 12px; padding: 5px 10px; border: 1px solid #2563eb; color: #2563eb; border-radius: 5px; background: none; cursor: pointer; }
.btn-new:hover { background: #eff6ff; }
.btn-confirm { align-self: flex-start; font-size: 12px; padding: 5px 12px; background: #2563eb; color: #fff; border: none; border-radius: 5px; cursor: pointer; }
.btn-confirm:hover:not(:disabled) { background: #1d4ed8; }
.btn-confirm:disabled { background: #93c5fd; cursor: not-allowed; }
.btn-sm { border: 1px solid #cbd5e1; background: #fff; color: #334155; border-radius: 5px; font-size: 12px; padding: 4px 8px; cursor: pointer; }
.btn-sm:hover:not(:disabled) { background: #eff6ff; border-color: #93c5fd; }
.btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-danger { color: #dc2626; border-color: #fecaca; }
.btn-danger:hover:not(:disabled) { background: #fef2f2; }

.field-input { width: 100%; box-sizing: border-box; border: 1px solid #dbe5f0; border-radius: 6px; padding: 7px 10px; font-size: 13px; outline: none; }
.field-input:focus { border-color: #2563eb; }
.error-tip { color: #dc2626; font-size: 12px; margin: 2px 0; }
.empty-hint { padding: 12px 14px; font-size: 12px; color: #94a3b8; }

/* ── 聊天主区域 ── */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.chat-header { display: flex; align-items: center; gap: 12px; padding: 14px 24px; border-bottom: 1px solid #e2e8f0; background: #fff; flex-shrink: 0; }
.chat-title { font-size: 15px; font-weight: 600; color: #1e293b; }
.kb-badge { font-size: 11px; padding: 2px 8px; background: #eff6ff; color: #2563eb; border-radius: 10px; }

.msg-list { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; background: #f8fafc; }
.msg-empty { text-align: center; color: #94a3b8; font-size: 14px; margin-top: 60px; }
.msg-row { display: flex; }
.msg-row.user { justify-content: flex-end; }
.msg-row.assistant { justify-content: flex-start; }
.msg-bubble { max-width: 72%; padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; }
.msg-row.user .msg-bubble { background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
.msg-row.assistant .msg-bubble { background: #fff; color: #334155; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; }
.msg-bubble.loading { color: #94a3b8; font-style: italic; }
.streaming-hint { color: #94a3b8; font-style: italic; font-size: 13px; }
.msg-content { white-space: normal; word-break: break-word; margin: 0; line-height: 1.65; }
.msg-content :deep(p) { margin: 0 0 8px; }
.msg-content :deep(p:last-child) { margin-bottom: 0; }
.msg-content :deep(ul), .msg-content :deep(ol) { margin: 4px 0 8px; padding-left: 20px; }
.msg-content :deep(li) { margin-bottom: 3px; }
.msg-content :deep(strong) { font-weight: 600; }
.msg-content :deep(code) { background: rgba(0,0,0,0.06); border-radius: 3px; padding: 1px 4px; font-size: 12px; }
.msg-content :deep(pre) { background: rgba(0,0,0,0.06); border-radius: 6px; padding: 8px 12px; overflow-x: auto; margin: 6px 0; }
.msg-content :deep(pre code) { background: none; padding: 0; }

.msg-sources { margin-top: 12px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.sources-label { font-size: 11px; font-weight: 600; color: #64748b; margin-bottom: 6px; }
.source-item { font-size: 12px; color: #475569; margin-bottom: 4px; }
.source-title { font-weight: 500; color: #2563eb; margin-right: 4px; }
.source-score { color: #94a3b8; margin-right: 6px; }
.source-snippet { color: #64748b; }
.msg-risks { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.risk-tag { font-size: 11px; padding: 2px 8px; border-radius: 12px; background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
.msg-disclaimer { margin-top: 10px; font-size: 11px; color: #f59e0b; border-top: 1px solid #fef3c7; padding-top: 8px; }

.input-bar { display: flex; flex-direction: column; gap: 6px; padding: 16px 24px; background: #fff; border-top: 1px solid #e2e8f0; flex-shrink: 0; }
.kb-hint { font-size: 12px; color: #b45309; background: #fef3c7; border: 1px solid #fde68a; border-radius: 6px; padding: 6px 12px; }
.input-row { display: flex; gap: 12px; }
.input-box { flex: 1; resize: none; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; font-size: 14px; font-family: inherit; outline: none; transition: border-color 0.15s; }
.input-box:focus { border-color: #2563eb; }
.input-box:disabled { background: #f8fafc; color: #94a3b8; }
.btn-send { padding: 0 20px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; transition: background 0.15s; white-space: nowrap; }
.btn-send:hover:not(:disabled) { background: #1d4ed8; }
.btn-send:disabled { background: #93c5fd; cursor: not-allowed; }
</style>
