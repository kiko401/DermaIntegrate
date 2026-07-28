<script setup>
import { ref, onUnmounted } from 'vue'

// ── 通用 fetch 封装 ──────────────────────────────────────────
async function apiFetch(path, body, method = 'POST') {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await res.json() : null
  return { ok: res.ok, status: res.status, data }
}

// ── 检索调试 ─────────────────────────────────────────────────
const r_query       = ref('')
const r_kbIds       = ref('')
const r_topK        = ref(5)
const r_threshold   = ref(0.35)
const r_loading     = ref(false)
const r_result      = ref(null)
const r_error       = ref('')

async function runRetrieval() {
  const query = r_query.value.trim()
  if (!query) { r_error.value = '请输入 Query'; return }
  const kb_ids = r_kbIds.value
    .split(',')
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)
  if (!kb_ids.length) { r_error.value = '请输入至少一个 KB ID（逗号分隔整数）'; return }

  r_loading.value = true
  r_result.value  = null
  r_error.value   = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/debug/retrieval', {
      question: query,
      kb_ids,
      options: {
        top_k: Number(r_topK.value) || 5,
        similarity_threshold: Number(r_threshold.value) || 0.35,
      },
    })
    if (!ok) {
      r_error.value = data?.detail || data?.error || `请求失败`
    } else {
      r_result.value = data
    }
  } catch (e) {
    r_error.value = e.message
  } finally {
    r_loading.value = false
  }
}

function scoreColor(score) {
  if (score >= 0.8) return '#16a34a'
  if (score >= 0.5) return '#92400e'
  return '#dc2626'
}

// ── 改写调试 ─────────────────────────────────────────────────
const w_query     = ref('')
const w_history   = ref('')
const w_loading   = ref(false)
const w_result    = ref(null)
const w_error     = ref('')

async function runRewrite() {
  const question = w_query.value.trim()
  if (!question) { w_error.value = '请输入问题'; return }

  let history = []
  if (w_history.value.trim()) {
    try {
      history = JSON.parse(w_history.value.trim())
      if (!Array.isArray(history)) throw new Error('history 必须为数组')
    } catch (e) {
      w_error.value = `History JSON 格式错误：${e.message}`
      return
    }
  }

  w_loading.value = true
  w_result.value  = null
  w_error.value   = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/debug/rewrite', { question, history })
    if (!ok) {
      w_error.value = data?.detail || data?.error || `请求失败`
    } else {
      w_result.value = data
    }
  } catch (e) {
    w_error.value = e.message
  } finally {
    w_loading.value = false
  }
}

// ── 工具调试 ─────────────────────────────────────────────────
const t_tools       = ref([])
const t_loadErr     = ref('')
const t_loading     = ref(false)
const t_selected    = ref(null)
const t_argsJson    = ref('{}')
const t_runLoading  = ref(false)
const t_runResult   = ref(null)
const t_runError    = ref('')

async function loadTools() {
  t_loading.value = true
  t_loadErr.value = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/tools', undefined, 'GET')
    if (!ok) {
      t_loadErr.value = data?.detail || data?.error || '加载失败'
    } else {
      t_tools.value = data.tools || []
    }
  } catch (e) {
    t_loadErr.value = e.message
  } finally {
    t_loading.value = false
  }
}

function selectTool(tool) {
  t_selected.value = tool
  t_runResult.value = null
  t_runError.value = ''
  // 填入默认空 args 骨架
  const props = tool.args_schema?.properties || {}
  const skeleton = {}
  for (const key of Object.keys(props)) {
    skeleton[key] = ''
  }
  t_argsJson.value = JSON.stringify(skeleton, null, 2)
}

async function runTool() {
  if (!t_selected.value) { t_runError.value = '请先选择一个工具'; return }
  let args
  try {
    args = JSON.parse(t_argsJson.value)
  } catch (e) {
    t_runError.value = `Arguments JSON 格式错误：${e.message}`
    return
  }
  t_runLoading.value = true
  t_runResult.value  = null
  t_runError.value   = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/tools/test-run', {
      tool_name: t_selected.value.name,
      arguments: args,
    })
    if (!ok) {
      t_runError.value = data?.detail || data?.error || '工具执行失败'
    } else {
      t_runResult.value = data
    }
  } catch (e) {
    t_runError.value = e.message
  } finally {
    t_runLoading.value = false
  }
}

// ── Agent 调试 ────────────────────────────────────────────────
const a_convId      = ref('')
const a_question    = ref('')
const a_kbIds       = ref('')
const a_runLoading  = ref(false)
const a_runId       = ref('')
const a_runError    = ref('')
const a_pollLoading = ref(false)
const a_trace       = ref(null)
const a_pollError   = ref('')
const a_pollTimer   = ref(null)
const a_pollCount   = ref(0)
const MAX_POLLS = 60

async function triggerAgent() {
  const question = a_question.value.trim()
  if (!question) { a_runError.value = '请输入问题'; return }
  const kb_ids = a_kbIds.value
    .split(',')
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)
  if (!kb_ids.length) { a_runError.value = '请输入至少一个 KB ID'; return }
  const conversation_id = parseInt(a_convId.value, 10)
  if (!conversation_id || isNaN(conversation_id)) { a_runError.value = '请输入有效的会话 ID（整数）'; return }

  stopAutoPoll()
  a_runLoading.value = true
  a_runId.value      = ''
  a_trace.value      = null
  a_runError.value   = ''
  a_pollError.value  = ''

  try {
    const { ok, data } = await apiFetch('/api/rag/agents/run', {
      conversation_id,
      question,
      kb_ids,
      history: [],
      patient_context: null,
      options: {},
    })
    if (!ok) {
      a_runError.value = data?.detail || data?.error || 'Agent 触发失败'
    } else {
      a_runId.value = data.run_id
      startAutoPoll()
    }
  } catch (e) {
    a_runError.value = e.message
  } finally {
    a_runLoading.value = false
  }
}

async function pollTrace() {
  if (!a_runId.value) return
  a_pollCount.value++
  if (a_pollCount.value > MAX_POLLS) {
    stopAutoPoll()
    a_pollError.value = '轮询超时（2分钟），请手动刷新或检查 Agent 服务状态'
    return
  }
  a_pollLoading.value = true
  a_pollError.value   = ''
  try {
    const { ok, data } = await apiFetch(`/api/rag/agents/runs/${a_runId.value}`, undefined, 'GET')
    if (!ok) {
      a_pollError.value = data?.detail || data?.error || '查询失败'
      stopAutoPoll()
    } else {
      a_trace.value = data
      const nodes = data.nodes || []
      const allDone = nodes.length > 0 && nodes.every(n =>
        n.status === 'completed' || n.status === 'failed' || n.status === 'skipped'
      )
      if (allDone) stopAutoPoll()
    }
  } catch (e) {
    a_pollError.value = e.message
    stopAutoPoll()
  } finally {
    a_pollLoading.value = false
  }
}

function startAutoPoll() {
  stopAutoPoll()
  a_pollCount.value = 0
  a_pollTimer.value = setInterval(pollTrace, 2000)
}

function stopAutoPoll() {
  if (a_pollTimer.value) {
    clearInterval(a_pollTimer.value)
    a_pollTimer.value = null
  }
}

onUnmounted(stopAutoPoll)

// ── 分块预览 ─────────────────────────────────────────────────
const sp_text       = ref('')
const sp_chunkSize  = ref(800)
const sp_overlap    = ref(120)
const sp_loading    = ref(false)
const sp_result     = ref(null)
const sp_error      = ref('')

async function runSplitPreview() {
  const text = sp_text.value.trim()
  if (!text) { sp_error.value = '请输入文本'; return }
  sp_loading.value = true
  sp_result.value  = null
  sp_error.value   = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/debug/split-preview', {
      text,
      chunk_size:    Number(sp_chunkSize.value) || 800,
      chunk_overlap: Number(sp_overlap.value) || 120,
    })
    if (!ok) {
      sp_error.value = data?.detail || data?.error || '请求失败'
    } else {
      sp_result.value = data
    }
  } catch (e) {
    sp_error.value = e.message
  } finally {
    sp_loading.value = false
  }
}

// ── 关键词搜索（BM25）────────────────────────────────────────
const ks_query   = ref('')
const ks_kbIds   = ref('')
const ks_topK    = ref(5)
const ks_loading = ref(false)
const ks_result  = ref(null)
const ks_error   = ref('')

async function runKeywordSearch() {
  const query = ks_query.value.trim()
  if (!query) { ks_error.value = '请输入关键词'; return }
  const kb_ids = ks_kbIds.value
    .split(',')
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)
  if (!kb_ids.length) { ks_error.value = '请输入至少一个 KB ID'; return }
  ks_loading.value = true
  ks_result.value  = null
  ks_error.value   = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/debug/keyword-search', {
      query,
      kb_ids,
      top_k: Number(ks_topK.value) || 5,
    })
    if (!ok) {
      ks_error.value = data?.detail || data?.error || '请求失败'
    } else {
      ks_result.value = data
    }
  } catch (e) {
    ks_error.value = e.message
  } finally {
    ks_loading.value = false
  }
}


function nodeStatusClass(status) {
  return {
    'node-running':   status === 'running',
    'node-completed': status === 'completed',
    'node-failed':    status === 'failed',
    'node-skipped':   status === 'skipped',
  }
}

function nodeStatusLabel(status) {
  const map = { running: '运行中', completed: '完成', failed: '失败', skipped: '跳过' }
  return map[status] || status
}
</script>

<template>
  <div class="debug-page rag-admin-page">
    <div class="page-header">
      <div class="title-block">
        <h2 class="page-title">调试工具台</h2>
        <div class="header-desc">检索、改写、工具、Agent 与分块调试统一到一页，布局更完整、更便于横向对比。</div>
      </div>
    </div>

    <div class="panels">
      <!-- ══════════════════════════════════════════ 检索调试 ══ -->
      <div class="panel panel-half">
        <div class="panel-title">检索调试</div>

        <div class="form-grid">
          <div class="form-item form-item-full">
            <label class="form-label">Query</label>
            <input
              v-model="r_query"
              class="field-input"
              placeholder="输入检索问题"
              @keydown.enter="runRetrieval"
            />
          </div>
          <div class="form-item">
            <label class="form-label">KB IDs <span class="hint">逗号分隔，如 1,2</span></label>
            <input v-model="r_kbIds" class="field-input" placeholder="1,2" />
          </div>
          <div class="form-item">
            <label class="form-label">Top-K</label>
            <input v-model.number="r_topK" type="number" min="1" max="50" step="1" class="field-input" />
          </div>
          <div class="form-item">
            <label class="form-label">相似度阈值</label>
            <input v-model.number="r_threshold" type="number" min="0" max="1" step="0.01" class="field-input" />
          </div>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" :disabled="r_loading" @click="runRetrieval">
            {{ r_loading ? '检索中...' : '发起检索' }}
          </button>
        </div>

        <div v-if="r_error" class="msg-error">{{ r_error }}</div>

        <div v-if="r_result" class="result-block">
          <div class="result-meta">
            <div class="meta-row">
              <span class="meta-key">改写 Query</span>
              <span class="meta-val">{{ r_result.rewrite_question }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">过滤条件</span>
              <span class="meta-val">
                kb_ids={{ r_result.filter_logic?.kb_ids?.join(',') }}
                &nbsp;top_k={{ r_result.filter_logic?.top_k }}
                &nbsp;threshold={{ r_result.filter_logic?.threshold }}
              </span>
            </div>
            <div v-if="r_result.fallback_reason" class="meta-row">
              <span class="meta-key">阻断原因</span>
              <span class="meta-val warn">{{ r_result.fallback_reason }}</span>
            </div>
          </div>
          <div class="chunk-header">命中 {{ r_result.retrieved_chunks?.length ?? 0 }} 个 Chunk</div>
          <div v-if="!r_result.retrieved_chunks?.length" class="empty-msg">无命中结果</div>
          <div
            v-for="(chunk, i) in r_result.retrieved_chunks"
            :key="chunk.chunk_id || i"
            class="chunk-card"
          >
            <div class="chunk-meta">
              <span class="chunk-idx">#{{ i + 1 }}</span>
              <span class="chunk-id" :title="chunk.chunk_id">{{ chunk.chunk_id }}</span>
              <span class="chunk-doc">doc_id: {{ chunk.doc_id }}</span>
              <span class="chunk-score" :style="{ color: scoreColor(chunk.score) }">
                score: {{ chunk.score?.toFixed(4) }}
              </span>
            </div>
            <div class="chunk-text">{{ chunk.text }}</div>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════ 改写调试 ══ -->
      <div class="panel panel-half">
        <div class="panel-title">改写调试</div>

        <div class="form-grid">
          <div class="form-item form-item-full">
            <label class="form-label">问题</label>
            <input
              v-model="w_query"
              class="field-input"
              placeholder="输入原始问题"
              @keydown.enter="runRewrite"
            />
          </div>
          <div class="form-item form-item-full">
            <label class="form-label">
              History <span class="hint">JSON 数组，可选</span>
            </label>
            <textarea
              v-model="w_history"
              class="field-input field-textarea"
              rows="3"
              placeholder='[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
            />
          </div>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" :disabled="w_loading" @click="runRewrite">
            {{ w_loading ? '改写中...' : '发起改写' }}
          </button>
        </div>

        <div v-if="w_error" class="msg-error">{{ w_error }}</div>

        <div v-if="w_result" class="result-block">
          <div class="rewrite-grid">
            <div class="rewrite-item">
              <div class="rw-label">原始问题</div>
              <div class="rw-val">{{ w_result.original }}</div>
            </div>
            <div class="rewrite-item">
              <div class="rw-label">改写后</div>
              <div class="rw-val highlight">{{ w_result.rewritten }}</div>
            </div>
            <div class="rewrite-item">
              <div class="rw-label">是否纠错</div>
              <div class="rw-val">
                <span :class="w_result.corrected ? 'badge-yes' : 'badge-no'">
                  {{ w_result.corrected ? '是' : '否' }}
                </span>
              </div>
            </div>
            <div v-if="w_result.correction" class="rewrite-item">
              <div class="rw-label">纠错结果</div>
              <div class="rw-val highlight">{{ w_result.correction }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════ 工具调试 ══ -->
      <div class="panel panel-wide">
        <div class="panel-title">工具调试</div>

        <div class="form-actions" style="margin-top:0; margin-bottom:14px;">
          <button class="btn btn-secondary" :disabled="t_loading" @click="loadTools">
            {{ t_loading ? '加载中...' : '加载工具列表' }}
          </button>
        </div>

        <div v-if="t_loadErr" class="msg-error">{{ t_loadErr }}</div>

        <div v-if="t_tools.length" class="tool-list">
          <div
            v-for="tool in t_tools"
            :key="tool.name"
            class="tool-card"
            :class="{ 'tool-card-selected': t_selected?.name === tool.name }"
            @click="selectTool(tool)"
          >
            <div class="tool-header">
              <span class="tool-name">{{ tool.name }}</span>
              <span class="tool-scope">{{ tool.access_scope?.join(', ') }}</span>
              <span :class="tool.enabled ? 'badge-yes' : 'badge-no'" style="font-size:11px;">
                {{ tool.enabled ? '启用' : '禁用' }}
              </span>
            </div>
            <div class="tool-desc">{{ tool.description }}</div>
            <div class="tool-meta">timeout: {{ tool.timeout_seconds }}s</div>
          </div>
        </div>

        <div v-if="t_selected" class="tool-run-area">
          <div class="tool-run-title">执行：{{ t_selected.name }}</div>

          <div class="form-item">
            <label class="form-label">
              Arguments JSON
              <span class="hint">按 args_schema 填写</span>
            </label>
            <div class="schema-hint" v-if="t_selected.args_schema?.properties">
              参数说明：
              <span
                v-for="(prop, key) in t_selected.args_schema.properties"
                :key="key"
                class="schema-prop"
              >
                <b>{{ key }}</b>：{{ prop.description || prop.type }}
              </span>
            </div>
            <textarea
              v-model="t_argsJson"
              class="field-input field-textarea"
              rows="5"
              placeholder='{"key": "value"}'
              style="font-family: monospace; font-size:12px;"
            />
          </div>

          <div class="form-actions">
            <button class="btn btn-primary" :disabled="t_runLoading" @click="runTool">
              {{ t_runLoading ? '执行中...' : '执行工具' }}
            </button>
          </div>

          <div v-if="t_runError" class="msg-error">{{ t_runError }}</div>

          <div v-if="t_runResult" class="result-block">
            <div class="result-meta">
              <div class="meta-row">
                <span class="meta-key">工具</span>
                <span class="meta-val">{{ t_runResult.tool_name }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-key">状态</span>
                <span class="meta-val">
                  <span :class="t_runResult.status === 'completed' ? 'badge-yes' : 'badge-no'">
                    {{ t_runResult.status }}
                  </span>
                </span>
              </div>
              <div v-if="t_runResult.output_summary" class="meta-row">
                <span class="meta-key">摘要</span>
                <span class="meta-val">{{ t_runResult.output_summary }}</span>
              </div>
            </div>
            <div class="detail-label">详细输出</div>
            <pre class="detail-pre">{{ JSON.stringify(t_runResult.output_detail, null, 2) }}</pre>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════ Agent 调试 ══ -->
      <div class="panel panel-wide">
        <div class="panel-title">Agent 调试</div>

        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">会话 ID <span class="hint">整数</span></label>
            <input v-model="a_convId" type="number" class="field-input" placeholder="1" />
          </div>
          <div class="form-item">
            <label class="form-label">KB IDs <span class="hint">逗号分隔</span></label>
            <input v-model="a_kbIds" class="field-input" placeholder="1,2" />
          </div>
          <div class="form-item form-item-full">
            <label class="form-label">问题</label>
            <input v-model="a_question" class="field-input" placeholder="输入问题触发 Agent" />
          </div>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" :disabled="a_runLoading" @click="triggerAgent">
            {{ a_runLoading ? '触发中...' : '触发 Agent' }}
          </button>
        </div>

        <div v-if="a_runError" class="msg-error">{{ a_runError }}</div>

        <div v-if="a_runId" class="agent-run-info">
          <div class="meta-row">
            <span class="meta-key">run_id</span>
            <span class="meta-val mono">{{ a_runId }}</span>
          </div>
          <div class="meta-row" style="margin-top:6px;">
            <button
              class="btn btn-secondary btn-sm"
              :disabled="a_pollLoading"
              @click="pollTrace"
            >
              {{ a_pollLoading ? '查询中...' : '手动刷新轨迹' }}
            </button>
            <span class="hint" style="margin-left:10px;">
              {{ a_pollTimer ? `自动轮询中（${a_pollCount}/${MAX_POLLS}，2s/次）...` : '' }}
            </span>
          </div>
        </div>

        <div v-if="a_pollError" class="msg-error">{{ a_pollError }}</div>

        <div v-if="a_trace" class="trace-block">
          <div class="trace-header">
            工作流：{{ a_trace.workflow }}
            <span class="hint" style="margin-left:8px;">{{ a_trace.created_at }}</span>
          </div>
          <div class="trace-nodes">
            <div
              v-for="(node, idx) in a_trace.nodes"
              :key="node.name || idx"
              class="trace-node"
            >
              <div class="node-index">{{ idx + 1 }}</div>
              <div class="node-name">{{ node.name }}</div>
              <div class="node-status-badge" :class="nodeStatusClass(node.status)">
                {{ nodeStatusLabel(node.status) }}
              </div>
            </div>
          </div>
          <div v-if="!a_trace.nodes?.length" class="empty-msg">
            暂无节点数据（Agent 可能尚未开始执行）
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════ 分块预览 ══ -->
      <div class="panel panel-half">
        <div class="panel-title">分块预览</div>

        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">Chunk Size</label>
            <input v-model.number="sp_chunkSize" type="number" min="50" max="4000" class="field-input" />
          </div>
          <div class="form-item">
            <label class="form-label">Chunk Overlap</label>
            <input v-model.number="sp_overlap" type="number" min="0" max="500" class="field-input" />
          </div>
          <div class="form-item form-item-full">
            <label class="form-label">文本</label>
            <textarea v-model="sp_text" class="field-input field-textarea" rows="5" placeholder="粘贴需要预览分块结果的文本" />
          </div>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" :disabled="sp_loading" @click="runSplitPreview">
            {{ sp_loading ? '预览中...' : '生成分块预览' }}
          </button>
        </div>

        <div v-if="sp_error" class="msg-error">{{ sp_error }}</div>

        <div v-if="sp_result" class="result-block">
          <div class="chunk-header">共 {{ sp_result.chunks?.length ?? 0 }} 个 Chunk</div>
          <div
            v-for="(chunk, i) in sp_result.chunks"
            :key="i"
            class="chunk-card"
          >
            <div class="chunk-meta">
              <span class="chunk-idx">#{{ i + 1 }}</span>
              <span class="chunk-doc">{{ chunk.text?.length ?? 0 }} 字</span>
            </div>
            <div class="chunk-text">{{ chunk.text }}</div>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════ 关键词搜索 ══ -->
      <div class="panel panel-half">
        <div class="panel-title">关键词搜索（BM25）</div>

        <div class="form-grid">
          <div class="form-item form-item-full">
            <label class="form-label">关键词</label>
            <input
              v-model="ks_query"
              class="field-input"
              placeholder="输入关键词"
              @keydown.enter="runKeywordSearch"
            />
          </div>
          <div class="form-item">
            <label class="form-label">KB IDs <span class="hint">逗号分隔</span></label>
            <input v-model="ks_kbIds" class="field-input" placeholder="1,2" />
          </div>
          <div class="form-item">
            <label class="form-label">Top-K</label>
            <input v-model.number="ks_topK" type="number" min="1" max="50" class="field-input" />
          </div>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" :disabled="ks_loading" @click="runKeywordSearch">
            {{ ks_loading ? '搜索中...' : '关键词检索' }}
          </button>
        </div>

        <div v-if="ks_error" class="msg-error">{{ ks_error }}</div>

        <div v-if="ks_result" class="result-block">
          <div class="chunk-header">命中 {{ ks_result.total_hits ?? ks_result.results?.length ?? 0 }} 个 Chunk</div>
          <div v-if="!ks_result.results?.length" class="empty-msg">无命中结果</div>
          <div
            v-for="(hit, i) in ks_result.results"
            :key="hit.chunk_id || i"
            class="chunk-card"
          >
            <div class="chunk-meta">
              <span class="chunk-idx">#{{ i + 1 }}</span>
              <span class="chunk-id" :title="hit.chunk_id">{{ hit.chunk_id }}</span>
              <span class="chunk-doc">doc_id: {{ hit.doc_id }}</span>
              <span class="chunk-score" style="color:#6366f1">bm25: {{ hit.bm25_score?.toFixed(4) }}</span>
            </div>
            <div class="chunk-text">{{ hit.text_snippet }}</div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.debug-page {
  padding: 20px 24px;
  min-height: 100%;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
    radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
    linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}
.page-header { margin-bottom: 24px; }
.title-block { display: flex; flex-direction: column; gap: 6px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }
.header-desc { font-size: 13px; color: #64748b; }
.panels { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; align-items: start; }

.panel {
  border-radius: 22px;
  padding: 22px 24px;
  min-width: 0;
}
.panel-half { grid-column: span 1; }
.panel-wide { grid-column: 1 / -1; }
.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
}

/* 表单 */
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 20px; }
.form-item { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.form-item-full { grid-column: 1 / -1; }
.form-label { font-size: 13px; font-weight: 600; color: #475569; }
.hint { font-weight: 400; color: #94a3b8; margin-left: 4px; }
.field-input {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  font-size: 13px;
  color: #334155;
  background: #fff;
  box-sizing: border-box;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.field-input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
.field-textarea { height: auto; min-height: 120px; padding: 10px 12px; resize: vertical; font-family: inherit; }

.form-actions { margin-top: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.btn {
  height: 38px;
  padding: 0 20px;
  border-radius: 12px;
  font-size: 13px;
  cursor: pointer;
  border: none;
  font-weight: 600;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: linear-gradient(135deg, #2563eb, #3b82f6); color: #fff; }
.btn-primary:hover:not(:disabled) { background: linear-gradient(135deg, #1d4ed8, #2563eb); }
.btn-secondary { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; font-weight: 500; }
.btn-secondary:hover:not(:disabled) { background: #e2e8f0; }
.btn-sm { height: 30px; padding: 0 12px; font-size: 12px; }

.msg-error {
  margin-top: 12px;
  padding: 12px 14px;
  background: #fee2e2;
  color: #dc2626;
  border-radius: 12px;
  font-size: 13px;
}

/* 结果区 */
.result-block { margin-top: 20px; }

.result-meta {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 14px 16px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meta-row { display: flex; gap: 10px; align-items: baseline; font-size: 13px; }
.meta-key { color: #64748b; min-width: 80px; flex-shrink: 0; }
.meta-val { color: #1e293b; word-break: break-all; }
.meta-val.warn { color: #d97706; font-weight: 600; }
.meta-val.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }

.chunk-header { font-size: 13px; font-weight: 700; color: #475569; margin-bottom: 10px; }
.empty-msg { font-size: 13px; color: #94a3b8; padding: 16px 0; }

.chunk-card {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: #fafbfc;
}
.chunk-meta {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 8px; flex-wrap: wrap;
}
.chunk-idx { font-size: 11px; color: #94a3b8; }
.chunk-id  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #64748b; overflow: hidden; text-overflow: ellipsis; max-width: 220px; white-space: nowrap; }
.chunk-doc { font-size: 12px; color: #64748b; }
.chunk-score { font-size: 13px; font-weight: 700; margin-left: auto; }
.chunk-text {
  font-size: 13px; color: #334155; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
  max-height: 220px; overflow-y: auto;
  background: #fff; border: 1px solid #f1f5f9; border-radius: 12px; padding: 10px 12px;
}

/* 改写结果 */
.rewrite-grid { display: flex; flex-direction: column; gap: 12px; }
.rewrite-item { display: flex; flex-direction: column; gap: 4px; }
.rw-label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; }
.rw-val {
  font-size: 14px; color: #1e293b; padding: 12px 14px;
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; word-break: break-all;
}
.rw-val.highlight { background: #eff6ff; border-color: #bfdbfe; color: #1e40af; }

/* 工具面板 */
.tool-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.tool-card {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.tool-card:hover { background: #f8fafc; border-color: #93c5fd; }
.tool-card-selected { background: #eff6ff; border-color: #3b82f6; }
.tool-header { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.tool-name { font-size: 13px; font-weight: 700; color: #1e40af; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.tool-scope { font-size: 11px; color: #64748b; background: #f1f5f9; padding: 2px 8px; border-radius: 999px; }
.tool-desc { font-size: 13px; color: #475569; line-height: 1.5; margin-bottom: 4px; }
.tool-meta { font-size: 11px; color: #94a3b8; }
.tool-run-area { border-top: 1px solid #f1f5f9; margin-top: 16px; padding-top: 16px; }
.tool-run-title { font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 12px; }
.schema-hint {
  font-size: 12px; color: #64748b; background: #f8fafc;
  border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px 10px; margin-bottom: 6px;
}
.schema-prop { display: inline-block; margin-right: 12px; }
.detail-label { font-size: 12px; color: #94a3b8; margin-top: 12px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.04em; }
.detail-pre {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 10px 12px; font-size: 12px; color: #334155; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto;
}

/* Agent 面板 */
.agent-run-info {
  margin-top: 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 16px;
  padding: 12px 16px;
}
.trace-block { margin-top: 16px; }
.trace-header { font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 12px; }
.trace-nodes { display: flex; flex-direction: column; gap: 6px; }
.trace-node {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 16px; background: #fafbfc;
}
.node-index { font-size: 11px; color: #94a3b8; min-width: 20px; text-align: right; }
.node-name { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; color: #334155; flex: 1; }
.node-status-badge {
  display: inline-block; padding: 4px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 700; min-width: 60px; text-align: center;
}
.node-running   { background: #dbeafe; color: #1d4ed8; }
.node-completed { background: #dcfce7; color: #16a34a; }
.node-failed    { background: #fee2e2; color: #dc2626; }
.node-skipped   { background: #f1f5f9; color: #64748b; }

/* 通用 badges */
.badge-yes { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #dcfce7; color: #16a34a; font-size: 12px; font-weight: 700; }
.badge-no  { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #f1f5f9; color: #64748b; font-size: 12px; font-weight: 700; }
@media (max-width: 1100px) {
  .panels { grid-template-columns: 1fr; }
  .panel-half, .panel-wide { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .form-grid { grid-template-columns: 1fr; }
  .meta-row, .trace-node { flex-wrap: wrap; }
}
</style>
