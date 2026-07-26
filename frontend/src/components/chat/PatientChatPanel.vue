<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
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
  // ???????????ID????
  conversationId: { type: [String, Number], default: null },
  patientContext: { type: Object, default: null },
})

const convId = ref(props.conversationId || null)
const messages = ref([])
const loadingHistory = ref(false)
const patientContext = ref(null)

// 问答状态
const question = ref('')
const sending = ref(false)
const streaming = ref(false)
const streamAnswer = ref('')

// SSE
let sseSource = null
const inputRef = ref(null)

// 知识库选择
const availableKbs = ref([])
const selectedKbIds = ref([])
const kbLoading = ref(false)

async function loadKbs() {
  kbLoading.value = true
  try {
    const res = await apiFetch('/api/rag/kbs')
    const data = await res.json()
    availableKbs.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
    if (availableKbs.value.length === 1 && !selectedKbIds.value.length) {
      selectedKbIds.value = [availableKbs.value[0].id]
    }
  } catch {
    // ignore
  } finally {
    kbLoading.value = false
  }
}

async function init() {
  if (convId.value) {
    await loadHistory()
    if (!patientContext.value && props.patientContext) {
      patientContext.value = props.patientContext
    }
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
        patient_context: props.patientContext || null,
      }),
    })
    if (!res.ok) throw new Error('创建会话失败')
    const data = await res.json()
    convId.value = data.id
    patientContext.value = props.patientContext || (data.patient_context_json
      ? (typeof data.patient_context_json === 'string'
          ? JSON.parse(data.patient_context_json)
          : data.patient_context_json)
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
    if (patientContext.value) qs.set('patient_context', JSON.stringify(patientContext.value))
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

// ── 反馈 ──────────────────────────────────────────────────────────────
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

function closeSse() {
  if (sseSource) {
    sseSource.close()
    sseSource = null
  }
}

onMounted(async () => {
  await loadKbs()
  await init()
})

onUnmounted(() => {
  closeSse()
})
</script>

<template>
  <div class="pcp-root">
    <!-- 患者上下文摘要条 -->
    <div v-if="patientContext" class="pcp-context-bar">
      <span class="pcp-context-label">上下文</span>
      <span class="pcp-context-text">{{ patientContext.summary_text }}</span>
    </div>

    <!-- 知识库选择 -->
    <div class="pcp-kb-bar">
      <span class="pcp-kb-label">知识库</span>
      <a-select
        v-model:value="selectedKbIds"
        mode="multiple"
        size="small"
        placeholder="不选则使用默认"
        :options="availableKbs.map(kb => ({ label: kb.name, value: kb.id }))"
        :loading="kbLoading"
        style="flex: 1; min-width: 0;"
        :max-tag-count="2"
        allow-clear
      />
    </div>

    <!-- 消息列表 -->
    <div class="pcp-messages">
      <a-spin v-if="loadingHistory" class="pcp-loading" />

      <template v-else>
        <div v-if="!messages.length" class="pcp-empty">
          <div class="pcp-empty-icon">💬</div>
          <div class="pcp-empty-text">基于当前患者上下文提问</div>
          <div class="pcp-empty-sub">患者信息已自动注入，AI 会结合临床数据检索知识库</div>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="pcp-msg-wrap"
          :class="msg.role === 'user' ? 'pcp-msg-user' : 'pcp-msg-assistant'"
        >
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="pcp-bubble pcp-bubble-user">
            {{ msg.content_markdown }}
          </div>

          <!-- AI 消息 -->
          <div v-else class="pcp-bubble pcp-bubble-assistant">
            <!-- 阻断提示 -->
            <div v-if="msg.blocked_reason" class="pcp-blocked">
              ⚠️ {{ msg.blocked_reason }}
            </div>

            <div
              v-else
              class="pcp-markdown"
              v-html="renderMd(msg.content_markdown)"
            />

            <!-- 来源引用 -->
            <div v-if="msg.sources && msg.sources.length" class="pcp-sources">
              <div class="pcp-sources-title">参考来源</div>
              <div
                v-for="(src, si) in msg.sources"
                :key="si"
                class="pcp-source-item"
              >
                <span class="pcp-source-title">{{ src.title || `文档 ${src.doc_id}` }}</span>
                <span v-if="src.score != null" class="pcp-source-score">{{ (src.score * 100).toFixed(0) }}%</span>
                <div v-if="src.snippet" class="pcp-source-snippet">{{ src.snippet }}</div>
              </div>
            </div>

            <!-- 免责声明 -->
            <div v-if="msg.disclaimer" class="pcp-disclaimer">
              {{ msg.disclaimer }}
            </div>

            <!-- 反馈按钮 -->
            <div v-if="msg.id" class="pcp-feedback">
              <button
                :class="['pcp-fb-btn', feedbackState[msg.id] === 'up' && 'pcp-fb-up']"
                :disabled="feedbackState[msg.id] === 'sending'"
                title="有帮助"
                @click="submitFeedback(msg, 'up')"
              >👍</button>
              <button
                :class="['pcp-fb-btn', feedbackState[msg.id] === 'down' && 'pcp-fb-down']"
                :disabled="feedbackState[msg.id] === 'sending'"
                title="没帮助"
                @click="submitFeedback(msg, 'down')"
              >👎</button>
            </div>
          </div>
        </div>

        <!-- 流式占位 -->
        <div v-if="streaming" class="pcp-msg-wrap pcp-msg-assistant">
          <div class="pcp-bubble pcp-bubble-assistant">
            <div class="pcp-markdown" v-html="renderMd(streamAnswer) || '&nbsp;'" />
            <span class="pcp-cursor" />
          </div>
        </div>
      </template>

      <div ref="messagesEndRef" />
    </div>

    <!-- 输入区 -->
    <div class="pcp-input-area">
      <a-textarea
        ref="inputRef"
        v-model:value="question"
        placeholder="基于该患者提问，按 Enter 发送，Shift+Enter 换行"
        :auto-size="{ minRows: 2, maxRows: 5 }"
        :disabled="sending || streaming || loadingHistory"
        @keydown="onKeydown"
        class="pcp-textarea"
      />
      <a-button
        type="primary"
        :loading="sending"
        :disabled="!question.trim() || loadingHistory"
        @click="send"
        class="pcp-send-btn"
      >
        发送
      </a-button>
    </div>
  </div>
</template>

<style scoped>
.pcp-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.pcp-context-bar {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(47, 111, 237, 0.06);
  border-bottom: 1px solid rgba(47, 111, 237, 0.1);
  font-size: 11px;
  line-height: 1.5;
}

.pcp-context-label {
  flex-shrink: 0;
  font-weight: 700;
  color: #2f6fed;
  padding-top: 1px;
}

.pcp-context-text {
  color: #35506f;
  flex: 1;
  min-width: 0;
}

.pcp-kb-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-bottom: 1px solid rgba(116, 152, 193, 0.1);
}

.pcp-kb-label {
  font-size: 11px;
  font-weight: 600;
  color: #8aa0b8;
  flex-shrink: 0;
}

.pcp-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.pcp-loading {
  display: flex;
  justify-content: center;
  padding: 32px;
}

.pcp-empty {
  text-align: center;
  padding: 32px 16px;
}

.pcp-empty-icon {
  font-size: 28px;
  margin-bottom: 8px;
}

.pcp-empty-text {
  font-size: 13px;
  font-weight: 600;
  color: #5f7894;
}

.pcp-empty-sub {
  font-size: 11px;
  color: #8aa0b8;
  margin-top: 4px;
  line-height: 1.6;
}

.pcp-msg-wrap {
  display: flex;
}

.pcp-msg-user {
  justify-content: flex-end;
}

.pcp-msg-assistant {
  justify-content: flex-start;
}

.pcp-bubble {
  max-width: 90%;
  border-radius: 14px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.6;
}

.pcp-bubble-user {
  background: linear-gradient(135deg, #2f6fed 0%, #19c6d0 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.pcp-bubble-assistant {
  background: rgba(248, 251, 255, 0.9);
  border: 1px solid rgba(116, 152, 193, 0.12);
  color: #35506f;
  border-bottom-left-radius: 4px;
  width: 100%;
  max-width: 100%;
}

.pcp-blocked {
  color: #c2410c;
  background: rgba(254, 215, 170, 0.4);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
}

.pcp-markdown {
  font-size: 12px;
  line-height: 1.7;
  color: #35506f;
  word-break: break-word;
}
.pcp-markdown :deep(p) { margin: 0 0 6px; }
.pcp-markdown :deep(p:last-child) { margin-bottom: 0; }
.pcp-markdown :deep(ul), .pcp-markdown :deep(ol) { margin: 4px 0 6px; padding-left: 18px; }
.pcp-markdown :deep(li) { margin-bottom: 2px; }
.pcp-markdown :deep(strong) { font-weight: 600; }
.pcp-markdown :deep(code) { background: rgba(47,111,237,0.08); border-radius: 3px; padding: 1px 4px; font-size: 11px; }
.pcp-markdown :deep(pre) { background: rgba(47,111,237,0.06); border-radius: 6px; padding: 8px 10px; overflow-x: auto; margin: 4px 0; }
.pcp-markdown :deep(pre code) { background: none; padding: 0; }

.pcp-sources {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(116, 152, 193, 0.1);
}

.pcp-sources-title {
  font-size: 10px;
  font-weight: 700;
  color: #8aa0b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 5px;
}

.pcp-source-item {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 4px;
}

.pcp-source-title {
  font-size: 11px;
  font-weight: 600;
  color: #2f6fed;
}

.pcp-source-score {
  font-size: 10px;
  color: #8aa0b8;
}

.pcp-source-snippet {
  width: 100%;
  font-size: 11px;
  color: #5f7894;
  line-height: 1.5;
  background: rgba(116, 152, 193, 0.06);
  border-radius: 6px;
  padding: 4px 8px;
}

.pcp-disclaimer {
  margin-top: 8px;
  font-size: 10px;
  color: #8aa0b8;
  line-height: 1.6;
  border-top: 1px solid rgba(116, 152, 193, 0.1);
  padding-top: 6px;
}

.pcp-feedback { display: flex; gap: 5px; margin-top: 6px; }
.pcp-fb-btn { border: 1px solid #e2e8f0; background: #fff; border-radius: 5px; padding: 2px 7px; font-size: 13px; cursor: pointer; color: #94a3b8; transition: border-color 0.15s, background 0.15s; }
.pcp-fb-btn:hover:not(:disabled) { border-color: #2563eb; background: #eff6ff; }
.pcp-fb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pcp-fb-up { background: #dcfce7 !important; border-color: #16a34a !important; }
.pcp-fb-down { background: #fee2e2 !important; border-color: #dc2626 !important; }

.pcp-cursor {
  display: inline-block;
  width: 2px;
  height: 12px;
  background: #2f6fed;
  border-radius: 1px;
  animation: blink 0.9s infinite;
  vertical-align: middle;
  margin-left: 2px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.pcp-input-area {
  padding: 10px 12px;
  border-top: 1px solid rgba(116, 152, 193, 0.1);
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.pcp-textarea {
  flex: 1;
  border-radius: 12px !important;
  font-size: 12px;
  resize: none;
}

.pcp-send-btn {
  flex-shrink: 0;
  border-radius: 10px !important;
  border: none !important;
  background: #2f9fe2 !important;
  font-weight: 600;
  align-self: flex-end;
}
</style>
