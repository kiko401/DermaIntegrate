<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { message } from 'ant-design-vue'
import { apiFetch } from '@/utils/api'
import { marked } from 'marked'

marked.setOptions({ breaks: true })

function renderMd(text) {
  if (!text) return ''
  return marked.parse(text)
}

const props = defineProps({
  patientId: { type: [String, Number], required: true },
  conversationId: { type: [String, Number], default: null },
  patientContext: { type: Object, default: null },
})

const convId = ref(props.conversationId || null)
const messages = ref([])
const loadingHistory = ref(false)
const patientContext = ref(null)

const question = ref('')
const sending = ref(false)
const streaming = ref(false)
const streamAnswer = ref('')
const inputRef = ref(null)

const availableKbs = ref([])
const selectedKbIds = ref([])
const kbLoading = ref(false)
const kbDrawerOpen = ref(false)
const fileDrawerOpen = ref(false)

const docSearch = ref('')
const docs = ref([])
const docsLoading = ref(false)
const fileKbId = ref(null)

const docPreviewOpen = ref(false)
const docPreviewLoading = ref(false)
const docPreviewErr = ref('')
const docPreviewData = ref(null)
const docPreviewTitle = ref('')
const docPreviewChunkId = ref(null)
const docPreviewTab = ref('chunks')

let sseSource = null

const selectedKbList = computed(() => availableKbs.value.filter(kb => selectedKbIds.value.includes(kb.id)))
const selectedKbSummary = computed(() => {
  if (!selectedKbList.value.length) return '未选择知识库'
  if (selectedKbList.value.length === 1) return selectedKbList.value[0].name
  return `已选择 ${selectedKbList.value.length} 个知识库`
})
const currentFileKb = computed(() => availableKbs.value.find(kb => String(kb.id) === String(fileKbId.value)) || null)

async function loadKbs() {
  kbLoading.value = true
  try {
    const res = await apiFetch('/api/rag/kbs')
    const data = await res.json()
    availableKbs.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
    if (availableKbs.value.length === 1 && !selectedKbIds.value.length) {
      selectedKbIds.value = [availableKbs.value[0].id]
    }
    if (!fileKbId.value) fileKbId.value = selectedKbIds.value[0] || availableKbs.value[0]?.id || null
  } catch {
    // ignore
  } finally {
    kbLoading.value = false
  }
}

async function init() {
  if (convId.value) {
    await loadHistory()
    if (!patientContext.value && props.patientContext) patientContext.value = props.patientContext
    return
  }
  loadingHistory.value = true
  try {
    const res = await apiFetch('/api/rag/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: '患者上下文问答',
        scene_type: 'patient_context',
        patient_id: props.patientId,
        kb_ids: selectedKbIds.value,
      }),
    })
    if (!res.ok) throw new Error('创建会话失败')
    const data = await res.json()
    convId.value = data.id
    patientContext.value = props.patientContext || (data.patient_context_json
      ? (typeof data.patient_context_json === 'string' ? JSON.parse(data.patient_context_json) : data.patient_context_json)
      : null)
  } catch (e) {
    message.error(e.message || '初始化会话失败')
  } finally {
    loadingHistory.value = false
  }
}

async function loadHistory() {
  if (!convId.value) return
  loadingHistory.value = true
  try {
    const res = await apiFetch(`/api/rag/conversations/${convId.value}/messages`)
    if (!res.ok) throw new Error()
    const data = await res.json()
    messages.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  } catch {
    message.error('加载历史消息失败')
  } finally {
    loadingHistory.value = false
  }
}

async function send() {
  const q = question.value.trim()
  if (!q || sending.value || streaming.value) return
  if (!convId.value) {
    message.warning('会话未就绪，请稍后')
    return
  }
  if (!selectedKbIds.value.length) {
    kbDrawerOpen.value = true
    message.warning('请至少选择一个知识库')
    return
  }

  messages.value.push({ role: 'user', content_markdown: q, _local: true })
  question.value = ''
  sending.value = true
  streamAnswer.value = ''
  streaming.value = true
  await scrollBottom()

  let finalPayload = null

  try {
    const qs = new URLSearchParams({ question: q })
    selectedKbIds.value.forEach(id => qs.append('kb_ids', String(id)))
    const url = `/api/rag/conversations/${convId.value}/stream?${qs.toString()}`

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

        if (eventType === 'result') {
          finalPayload = payload
          if (payload.answer) streamAnswer.value = payload.answer
        } else if (eventType === 'saved') {
          if (finalPayload) finalPayload._savedMessageId = payload.message_id
        } else if (eventType === 'disclaimer') {
          if (finalPayload) finalPayload.disclaimer = payload.disclaimer
        } else if (eventType === 'progress') {
          streamAnswer.value = payload.message || payload.step || streamAnswer.value
        } else if (eventType === 'error') {
          throw new Error(payload.message || payload.code || '问答失败')
        }
        await scrollBottom()
      }
    }

    if (finalPayload) {
      messages.value.push({
        role: 'assistant',
        id: finalPayload._savedMessageId || null,
        content_markdown: finalPayload.answer || streamAnswer.value || '',
        sources: finalPayload.sources || [],
        disclaimer: finalPayload.disclaimer || '',
        confidence: finalPayload.confidence,
        blocked_reason: finalPayload.blocked_reason || null,
        risk_highlights: finalPayload.risk_highlights || [],
      })
    }
    await scrollBottom()
  } catch (e) {
    message.error(e.message || '问答失败')
    messages.value = messages.value.filter(m => !m._local)
    question.value = q
  } finally {
    sending.value = false
    streaming.value = false
    streamAnswer.value = ''
    await scrollBottom()
  }
}

const feedbackState = ref({})

async function submitFeedback(msg, rating) {
  if (!msg.id) return
  const key = msg.id
  if (feedbackState.value[key] === 'sending') return
  feedbackState.value[key] = 'sending'
  try {
    const res = await apiFetch('/api/rag/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: msg.id, rating }),
    })
    feedbackState.value[key] = res.ok ? rating : null
    if (!res.ok) delete feedbackState.value[key]
  } catch {
    delete feedbackState.value[key]
  }
}

async function fetchDocs() {
  if (!fileKbId.value) {
    docs.value = []
    return
  }
  docsLoading.value = true
  try {
    const params = new URLSearchParams()
    params.set('kb_id', String(fileKbId.value))
    if (docSearch.value.trim()) params.set('search', docSearch.value.trim())
    params.set('page', '1')
    params.set('pageSize', '50')
    const res = await apiFetch(`/api/rag/documents?${params.toString()}`)
    const data = await res.json()
    docs.value = Array.isArray(data?.data) ? data.data : []
  } catch {
    docs.value = []
  } finally {
    docsLoading.value = false
  }
}

function toggleKb(id) {
  const idx = selectedKbIds.value.indexOf(id)
  if (idx >= 0) selectedKbIds.value.splice(idx, 1)
  else selectedKbIds.value.push(id)
  if (!fileKbId.value) fileKbId.value = id
}

function openKbDrawer() {
  kbDrawerOpen.value = true
}

function openFileDrawer(kbId = null) {
  if (kbId) fileKbId.value = kbId
  else if (!fileKbId.value) fileKbId.value = selectedKbIds.value[0] || availableKbs.value[0]?.id || null
  fileDrawerOpen.value = true
  fetchDocs()
}

function downloadDoc(doc) {
  const a = document.createElement('a')
  a.href = `/api/rag/documents/${doc.id}/download`
  a.download = doc.file_name || doc.title || `document-${doc.id}`
  a.click()
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
    const res = await apiFetch(`/api/rag/documents/${src.doc_id}/preview${qs}`)
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      throw new Error(d?.message || d?.error || '加载失败')
    }
    docPreviewData.value = await res.json()
  } catch (e) {
    docPreviewErr.value = e.message || '加载失败'
  } finally {
    docPreviewLoading.value = false
  }
}

async function openDocPreview(doc) {
  docPreviewOpen.value = true
  docPreviewLoading.value = true
  docPreviewErr.value = ''
  docPreviewData.value = null
  docPreviewTitle.value = doc.title || doc.file_name || `文档 #${doc.id}`
  docPreviewChunkId.value = null
  docPreviewTab.value = 'raw'
  try {
    const res = await apiFetch(`/api/rag/documents/${doc.id}/preview`)
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      throw new Error(d?.message || d?.error || '加载预览失败')
    }
    docPreviewData.value = await res.json()
  } catch (e) {
    docPreviewErr.value = e.message || '加载预览失败'
  } finally {
    docPreviewLoading.value = false
  }
}

function closeDocPreview() {
  docPreviewOpen.value = false
  docPreviewData.value = null
  docPreviewErr.value = ''
}

const messagesEndRef = ref(null)
async function scrollBottom() {
  await nextTick()
  messagesEndRef.value?.scrollIntoView({ behavior: 'smooth' })
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function applyTemplate(tpl) {
  question.value = tpl.question_template
  nextTick(() => inputRef.value?.focus())
}

function closeSse() {
  if (sseSource) {
    sseSource.close()
    sseSource = null
  }
}

const quickTemplates = ref([])
const templatesLoading = ref(false)

async function loadTemplates() {
  templatesLoading.value = true
  try {
    const res = await apiFetch('/api/rag/tools/templates')
    if (!res.ok) return
    const data = await res.json()
    quickTemplates.value = Array.isArray(data?.templates) ? data.templates : []
  } catch {
    // ignore
  } finally {
    templatesLoading.value = false
  }
}

onMounted(async () => {
  await loadKbs()
  await loadTemplates()
  await init()
})

onUnmounted(() => {
  closeSse()
})
</script>

<template>
  <div class="pcp-root">
    <div class="pcp-topbar">
      <div class="pcp-context-card">
        <div class="pcp-context-title">患者上下文</div>
        <div class="pcp-context-text">{{ patientContext?.summary_text || '正在准备患者上下文...' }}</div>
      </div>

      <div class="pcp-actions-card">
        <div class="pcp-selected-text">{{ selectedKbSummary }}</div>
        <div class="pcp-action-row">
          <button class="pcp-btn secondary" @click="openKbDrawer">选择知识库</button>
          <button class="pcp-btn secondary" @click="openFileDrawer()">查看文件</button>
        </div>
      </div>
    </div>

    <div class="pcp-messages">
      <a-spin v-if="loadingHistory" class="pcp-loading" />

      <template v-else>
        <div v-if="!messages.length" class="pcp-empty">
          <div class="pcp-empty-title">基于当前患者上下文提问</div>
          <div class="pcp-empty-sub">系统会自动结合当前患者临床摘要和所选知识库回答。</div>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="pcp-msg-wrap"
          :class="msg.role === 'user' ? 'pcp-msg-user' : 'pcp-msg-assistant'"
        >
          <div v-if="msg.role === 'user'" class="pcp-bubble pcp-bubble-user">
            {{ msg.content_markdown }}
          </div>

          <div v-else class="pcp-bubble pcp-bubble-assistant">
            <div v-if="msg.blocked_reason" class="pcp-blocked">⚠ {{ msg.blocked_reason }}</div>
            <div v-else class="pcp-markdown" v-html="renderMd(msg.content_markdown)" />

            <div v-if="msg.sources?.length" class="pcp-section">
              <div class="pcp-section-title">引用来源</div>
              <button
                v-for="(src, si) in msg.sources"
                :key="si"
                class="pcp-source-item"
                @click="openSourcePreview(src)"
              >
                <div class="pcp-source-head">
                  <span>{{ src.title || `文档 ${src.doc_id}` }}</span>
                  <span v-if="src.score != null" class="pcp-source-score">{{ (src.score * 100).toFixed(0) }}%</span>
                </div>
                <div v-if="src.snippet" class="pcp-source-snippet">{{ src.snippet }}</div>
              </button>
            </div>

            <div v-if="msg.disclaimer" class="pcp-disclaimer">{{ msg.disclaimer }}</div>

            <div v-if="msg.id" class="pcp-feedback">
              <button
                :class="['pcp-fb-btn', feedbackState[msg.id] === 'up' && 'pcp-fb-up']"
                :disabled="feedbackState[msg.id] === 'sending'"
                @click="submitFeedback(msg, 'up')"
              >👍 有帮助</button>
              <button
                :class="['pcp-fb-btn', feedbackState[msg.id] === 'down' && 'pcp-fb-down']"
                :disabled="feedbackState[msg.id] === 'sending'"
                @click="submitFeedback(msg, 'down')"
              >👎 需改进</button>
            </div>
          </div>
        </div>

        <div v-if="streaming" class="pcp-msg-wrap pcp-msg-assistant">
          <div class="pcp-bubble pcp-bubble-assistant">
            <div class="pcp-markdown" v-html="renderMd(streamAnswer) || '&nbsp;'" />
            <span class="pcp-cursor" />
          </div>
        </div>
      </template>

      <div ref="messagesEndRef" />
    </div>

    <div v-if="quickTemplates.length" class="pcp-templates">
      <button
        v-for="tpl in quickTemplates"
        :key="tpl.template_id"
        class="pcp-tpl-chip"
        :title="tpl.question_template"
        @click="applyTemplate(tpl)"
      >{{ tpl.name }}</button>
    </div>

    <div class="pcp-input-area">
      <a-textarea
        ref="inputRef"
        v-model:value="question"
        placeholder="基于该患者提问，按 Enter 发送，Shift + Enter 换行"
        :auto-size="{ minRows: 2, maxRows: 5 }"
        :disabled="sending || streaming || loadingHistory"
        @keydown="onKeydown"
        class="pcp-textarea"
      />
    </div>
  </div>

  <teleport to="body">
    <div v-if="kbDrawerOpen" class="pcp-overlay" @click.self="kbDrawerOpen = false">
      <div class="pcp-drawer">
        <div class="pcp-drawer-head">
          <div>
            <div class="pcp-panel-title">选择知识库</div>
            <div class="pcp-panel-sub">用于当前患者问答</div>
          </div>
          <button class="pcp-close-btn" @click="kbDrawerOpen = false">✕</button>
        </div>

        <div v-if="kbLoading" class="pcp-panel-empty">加载中...</div>
        <div v-else class="pcp-drawer-body">
          <label v-for="kb in availableKbs" :key="kb.id" class="pcp-kb-row">
            <input :checked="selectedKbIds.includes(kb.id)" type="checkbox" @change="toggleKb(kb.id)" />
            <div class="pcp-kb-main">
              <div class="pcp-kb-name">{{ kb.name }}</div>
              <div class="pcp-kb-meta">{{ kb.doc_count || 0 }} 个文件</div>
            </div>
            <button class="pcp-link-btn" @click.prevent="openFileDrawer(kb.id); kbDrawerOpen = false">文件</button>
          </label>
        </div>
      </div>
    </div>
  </teleport>

  <teleport to="body">
    <div v-if="fileDrawerOpen" class="pcp-overlay" @click.self="fileDrawerOpen = false">
      <div class="pcp-drawer pcp-drawer-wide">
        <div class="pcp-drawer-head">
          <div>
            <div class="pcp-panel-title">文件查看</div>
            <div class="pcp-panel-sub">{{ currentFileKb?.name || '请选择知识库' }}</div>
          </div>
          <button class="pcp-close-btn" @click="fileDrawerOpen = false">✕</button>
        </div>

        <div class="pcp-file-toolbar">
          <select v-model="fileKbId" class="pcp-select" @change="fetchDocs()">
            <option v-for="kb in availableKbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
          </select>
          <input v-model="docSearch" class="pcp-search" placeholder="搜索文件名" @keydown.enter="fetchDocs()" />
          <button class="pcp-btn secondary" @click="fetchDocs()">搜索</button>
        </div>

        <div class="pcp-drawer-body">
          <div v-if="docsLoading" class="pcp-panel-empty">加载中...</div>
          <div v-else-if="!docs.length" class="pcp-panel-empty">暂无文件</div>
          <div v-else class="pcp-file-list">
            <div v-for="doc in docs" :key="doc.id" class="pcp-file-row">
              <div class="pcp-file-main">
                <div class="pcp-file-title">{{ doc.title }}</div>
                <div class="pcp-file-meta">{{ doc.file_ext || '--' }} · {{ doc.file_name || `文档 #${doc.id}` }}</div>
              </div>
              <div class="pcp-file-actions">
                <button class="pcp-link-btn" @click="openDocPreview(doc)">预览</button>
                <button class="pcp-link-btn" @click="downloadDoc(doc)">下载</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </teleport>

  <teleport to="body">
    <div v-if="docPreviewOpen" class="pcp-overlay" @click.self="closeDocPreview">
      <div class="pcp-preview-modal">
        <div class="pcp-drawer-head">
          <div class="pcp-panel-title">{{ docPreviewTitle }}</div>
          <button class="pcp-close-btn" @click="closeDocPreview">✕</button>
        </div>

        <div v-if="docPreviewLoading" class="pcp-panel-empty">加载中...</div>
        <div v-else-if="docPreviewErr" class="pcp-preview-error">{{ docPreviewErr }}</div>
        <template v-else-if="docPreviewData">
          <div class="pcp-preview-meta">
            <span>版本 v{{ docPreviewData.version_no || '--' }}</span>
            <span>模型 {{ docPreviewData.embedding_model || '--' }}</span>
            <span>{{ docPreviewData.chunk_count || 0 }} chunks</span>
          </div>

          <div class="pcp-preview-tabs">
            <button class="pcp-preview-tab" :class="{ active: docPreviewTab === 'raw' }" @click="docPreviewTab = 'raw'">原始文本</button>
            <button class="pcp-preview-tab" :class="{ active: docPreviewTab === 'clean' }" @click="docPreviewTab = 'clean'">清洗文本</button>
            <button class="pcp-preview-tab" :class="{ active: docPreviewTab === 'chunks' }" @click="docPreviewTab = 'chunks'">Chunks</button>
          </div>

          <div class="pcp-preview-body">
            <div v-show="docPreviewTab === 'raw'" class="pcp-preview-text">
              <pre>{{ docPreviewData.raw_text_preview || '暂无原始文本' }}</pre>
            </div>
            <div v-show="docPreviewTab === 'clean'" class="pcp-preview-text">
              <pre>{{ docPreviewData.cleaned_text_preview || '暂无清洗文本' }}</pre>
            </div>
            <div v-show="docPreviewTab === 'chunks'">
              <div v-if="!docPreviewData.chunks_preview?.length" class="pcp-panel-empty">暂无 Chunk 数据</div>
              <div
                v-for="chunk in docPreviewData.chunks_preview || []"
                :key="chunk.chunk_index"
                class="pcp-chunk-row"
                :class="{ hit: chunk.is_hit || chunk.chunk_id === docPreviewChunkId }"
              >
                <div class="pcp-chunk-head">
                  <span>{{ chunk.chunk_id }}</span>
                  <span>{{ (chunk.text || '').length }} 字</span>
                </div>
                <div class="pcp-chunk-text">{{ chunk.text }}</div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.pcp-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  font-size: 13px;
  background:
    radial-gradient(circle at 16% 0%, rgba(76,128,255,0.08) 0%, transparent 30%),
    linear-gradient(180deg, #f8fbff 0%, #eef5fb 100%);
}

.pcp-topbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
}

.pcp-context-card,
.pcp-actions-card,
.pcp-bubble,
.pcp-drawer,
.pcp-preview-modal {
  background: #fff;
  border: 1px solid rgba(109, 145, 186, 0.12);
  border-radius: 16px;
  box-shadow: 0 14px 30px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(12px);
}

.pcp-context-card,
.pcp-actions-card {
  padding: 10px 12px;
}

.pcp-context-title,
.pcp-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #16324f;
  margin-bottom: 4px;
}

.pcp-context-text,
.pcp-panel-sub,
.pcp-selected-text,
.pcp-file-meta,
.pcp-kb-meta,
.pcp-empty-sub,
.pcp-disclaimer {
  font-size: 12.5px;
  color: #6b7280;
  line-height: 1.5;
}

.pcp-context-text {
  max-height: 58px;
  overflow-y: auto;
}

.pcp-action-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.pcp-btn {
  border: none;
  border-radius: 10px;
  padding: 7px 10px;
  font-weight: 600;
  font-size: 12.5px;
  cursor: pointer;
}

.pcp-btn.secondary {
  background: rgba(255,255,255,0.78);
  color: #2563eb;
  border: 1px solid rgba(37,99,235,0.16);
}

.pcp-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 12px 12px;
}

.pcp-empty,
.pcp-panel-empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  color: #94a3b8;
}

.pcp-empty-title {
  font-size: 16px;
  font-weight: 700;
  color: #475569;
}

.pcp-msg-wrap {
  display: flex;
  margin-bottom: 14px;
}

.pcp-msg-user {
  justify-content: flex-end;
}

.pcp-msg-assistant {
  justify-content: flex-start;
}

.pcp-bubble {
  max-width: 86%;
  padding: 12px 14px;
}

.pcp-bubble-user {
  background: linear-gradient(135deg, #2f6fed 0%, #19c6d0 100%);
  border-color: transparent;
  color: #fff;
}

.pcp-markdown :deep(p:first-child) {
  margin-top: 0;
}

.pcp-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.pcp-blocked {
  color: #b91c1c;
  font-weight: 600;
}

.pcp-section {
  margin-top: 12px;
}

.pcp-section-title {
  margin-bottom: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
}

.pcp-source-item {
  width: 100%;
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fbff;
  padding: 8px 10px;
  cursor: pointer;
  margin-bottom: 8px;
}

.pcp-source-head,
.pcp-file-row,
.pcp-file-actions,
.pcp-preview-meta,
.pcp-chunk-head,
.pcp-drawer-head,
.pcp-file-toolbar,
.pcp-kb-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.pcp-source-score {
  color: #2563eb;
}

.pcp-source-snippet {
  margin-top: 6px;
  color: #64748b;
  font-size: 12.5px;
}

.pcp-feedback {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.pcp-fb-btn {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #2563eb;
  padding: 7px 9px;
  border-radius: 10px;
  cursor: pointer;
}

.pcp-fb-up,
.pcp-fb-down {
  border-color: #1d4ed8;
}

.pcp-cursor {
  display: inline-block;
  width: 8px;
  height: 18px;
  background: #2563eb;
  animation: blink 1s infinite;
}

.pcp-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 0 12px 12px;
}

.pcp-tpl-chip {
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #4b5563;
  padding: 7px 10px;
  border-radius: 999px;
  cursor: pointer;
}

.pcp-tpl-chip:hover {
  border-color: rgba(47,111,237,0.24);
  color: #2563eb;
}

.pcp-input-area {
  padding: 0 12px 12px;
}

.pcp-textarea {
  width: 100%;
}

.pcp-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 2100;
}

.pcp-drawer,
.pcp-preview-modal {
  width: 400px;
  height: 100%;
  padding: 18px;
  border-radius: 0;
  display: flex;
  flex-direction: column;
}

.pcp-drawer-wide {
  width: 560px;
}

.pcp-preview-modal {
  width: min(860px, 92vw);
  height: min(88vh, 860px);
  margin: auto;
  border-radius: 20px;
}

.pcp-drawer-body,
.pcp-preview-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.pcp-close-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 10px;
  background: #f3f4f6;
  cursor: pointer;
}

.pcp-kb-row,
.pcp-file-row {
  padding: 10px 0;
  border-bottom: 1px solid #eef2f7;
}

.pcp-kb-main,
.pcp-file-main {
  flex: 1;
  min-width: 0;
}

.pcp-kb-name,
.pcp-file-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pcp-link-btn {
  border: none;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  padding: 0;
  font-size: 12.5px;
  font-weight: 500;
}

.pcp-select,
.pcp-search {
  border: 1px solid rgba(109,145,186,0.18);
  border-radius: 10px;
  padding: 8px 10px;
  font: inherit;
  font-size: 12.5px;
  width: 100%;
}

.pcp-preview-error {
  color: #b91c1c;
  padding: 12px 0;
}

.pcp-preview-tabs {
  display: flex;
  gap: 8px;
  padding: 12px 0;
}

.pcp-preview-tab {
  border: 1px solid #e5e7eb;
  background: #fff;
  padding: 8px 12px;
  border-radius: 999px;
  cursor: pointer;
}

.pcp-preview-tab.active {
  border-color: #2f6fed;
  color: #2563eb;
  background: #eef2ff;
}

.pcp-preview-text pre,
.pcp-chunk-text {
  white-space: pre-wrap;
  word-break: break-word;
  color: #334155;
  line-height: 1.7;
}

.pcp-chunk-row {
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 12px;
  margin-bottom: 10px;
}

.pcp-chunk-row.hit {
  border-color: #a5b4fc;
  background: #eef2ff;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}

@media (max-width: 900px) {
  .pcp-topbar,
  .pcp-input-area,
  .pcp-file-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .pcp-bubble {
    max-width: 100%;
  }
}
</style>
