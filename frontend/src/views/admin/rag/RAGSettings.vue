<script setup>
import { ref, onMounted } from 'vue'

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, { credentials: 'include', ...opts })
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await res.json() : null
  return { ok: res.ok, status: res.status, data }
}

const config = ref(null)
const form = ref({})
const loading = ref(false)
const saving = ref(false)
const saveMsg = ref('')
const saveError = ref('')

const FIELD_META = [
  { key: 'top_k', label: '检索 Top-K', type: 'integer', desc: '每次检索返回的最大 chunk 数量' },
  { key: 'similarity_threshold', label: '相似度阈值', type: 'float', desc: '低于此值的结果被丢弃（0~1）' },
  { key: 'chunk_size', label: '切分块大小', type: 'integer', desc: '默认 chunk 字符数' },
  { key: 'chunk_overlap', label: '切分重叠', type: 'integer', desc: '相邻 chunk 重叠字符数' },
  { key: 'max_upload_size_mb', label: '最大上传(MB)', type: 'integer', desc: '单文件上传大小限制' },
  { key: 'embedding_model', label: 'Embedding 模型', type: 'string', desc: '默认向量化模型标识' },
  { key: 'context_window_turns', label: '上下文轮数', type: 'integer', desc: '多轮对话保留的历史轮次数' },
  { key: 'max_length', label: '最大回答长度', type: 'integer', desc: '0 = 不限制；否则为字符数上限' },
  { key: 'max_paragraphs', label: '最大回答段落数', type: 'integer', desc: '0 = 不限制；否则为段落数上限' },
  { key: 'log_retention_days', label: '日志保留天数', type: 'integer', desc: '在线日志留存天数（医疗合规建议 180 天）' },
  { key: 'disclaimer_text', label: '免责声明文本', type: 'textarea', desc: '每次回答底部强制展示的医疗免责声明' },
]

const TOGGLE_META = [
  { key: 'enable_tools', label: '启用工具调用', desc: '允许 AI 调用外部工具' },
  { key: 'enable_agent', label: '启用 Agent', desc: '启用 LangGraph 智能体工作流' },
  { key: 'enable_rerank', label: '启用 Rerank', desc: '对检索结果进行重排序' },
  { key: 'enable_feedback_collection', label: '启用反馈采集', desc: '允许医生对回答提交反馈' },
  { key: 'enable_patient_context_injection', label: '启用患者上下文注入', desc: '允许在临床视图中注入患者上下文' },
]

async function loadConfig() {
  loading.value = true
  try {
    const { ok, data } = await apiFetch('/api/rag/config')
    if (ok && data) {
      config.value = data
      form.value = { ...data }
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  saveMsg.value = ''
  saveError.value = ''
  try {
    const { ok, data } = await apiFetch('/api/rag/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (ok) {
      config.value = data
      form.value = { ...data }
      saveMsg.value = '配置已保存，下次问答立即生效'
      setTimeout(() => { saveMsg.value = '' }, 4000)
    } else {
      saveError.value = data?.message || '保存失败'
    }
  } catch (e) {
    saveError.value = e.message
  } finally {
    saving.value = false
  }
}

function reset() {
  if (config.value) form.value = { ...config.value }
}

function inputType(type) {
  if (type === 'integer' || type === 'float') return 'number'
  return 'text'
}

function inputStep(type) {
  return type === 'float' ? '0.01' : '1'
}

onMounted(loadConfig)
</script>

<template>
  <div class="settings-page rag-admin-page">
    <div class="page-header">
      <div class="title-block">
        <h2 class="page-title">RAG 配置</h2>
        <div class="header-desc">配置实时生效，无需重启后端。AI 域每次调用时由应用域注入最新配置值。</div>
      </div>
    </div>

    <div v-if="loading" class="loading-msg">加载配置中...</div>

    <form v-else @submit.prevent="save" class="config-form">
      <!-- 参数配置 -->
      <div class="section">
        <div class="section-title">参数配置</div>
        <div class="field-grid">
          <div v-for="f in FIELD_META" :key="f.key" class="field-item"
               :class="{ 'field-item-full': f.type === 'textarea' }">
            <label class="field-label">{{ f.label }}</label>
            <textarea
              v-if="f.type === 'textarea'"
              v-model="form[f.key]"
              class="field-input field-textarea"
              rows="2"
            />
            <input
              v-else
              v-model="form[f.key]"
              :type="inputType(f.type)"
              :step="inputStep(f.type)"
              class="field-input"
            />
            <div class="field-desc">{{ f.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 开关配置 -->
      <div class="section">
        <div class="section-title">功能开关</div>
        <div class="toggle-grid">
          <div v-for="f in TOGGLE_META" :key="f.key" class="toggle-item">
            <label class="toggle-label">
              <input type="checkbox" v-model="form[f.key]" class="toggle-checkbox" />
              <span class="toggle-name">{{ f.label }}</span>
            </label>
            <div class="toggle-desc">{{ f.desc }}</div>
          </div>
        </div>
      </div>

      <div v-if="saveMsg" class="save-success">{{ saveMsg }}</div>
      <div v-if="saveError" class="save-error">{{ saveError }}</div>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary" :disabled="saving">
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
        <button type="button" class="btn btn-ghost" @click="reset">撤销修改</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.settings-page {
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
.loading-msg { color: #94a3b8; padding: 48px 0; font-size: 14px; text-align: center; }
.config-form { display: flex; flex-direction: column; gap: 24px; }
.section { border-radius: 22px; padding: 22px 24px; }
.section-title { font-size: 15px; font-weight: 700; color: #334155; margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px solid #f1f5f9; }
.field-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 22px; }
.field-item { display: flex; flex-direction: column; gap: 6px; }
.field-item-full { grid-column: 1 / -1; }
.field-label { font-size: 13px; font-weight: 600; color: #475569; }
.field-input { height: 40px; padding: 0 12px; border: 1px solid #cbd5e1; border-radius: 12px; font-size: 13px; color: #334155; background: #fff; transition: border-color 0.15s, box-shadow 0.15s; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
.field-textarea { height: auto; min-height: 96px; padding: 10px 12px; resize: vertical; }
.field-desc { font-size: 11px; color: #94a3b8; line-height: 1.5; }
.toggle-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.toggle-item { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; border: 1px solid #eef2f7; border-radius: 16px; background: #f8fbff; }
.toggle-label { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.toggle-checkbox { width: 16px; height: 16px; accent-color: #2563eb; cursor: pointer; }
.toggle-name { font-size: 13px; font-weight: 600; color: #334155; }
.toggle-desc { font-size: 12px; color: #94a3b8; padding-left: 26px; }
.save-success { background: #dcfce7; color: #16a34a; padding: 12px 14px; border-radius: 12px; font-size: 13px; }
.save-error { background: #fee2e2; color: #dc2626; padding: 12px 14px; border-radius: 12px; font-size: 13px; }
.form-actions { display: flex; gap: 10px; }
.btn { height: 40px; padding: 0 18px; border-radius: 12px; font-size: 13px; cursor: pointer; border: none; font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: linear-gradient(135deg, #2563eb, #3b82f6); color: #fff; }
.btn-primary:hover:not(:disabled) { background: linear-gradient(135deg, #1d4ed8, #2563eb); }
.btn-ghost { background: transparent; color: #64748b; border: 1px solid #e2e8f0; }
.btn-ghost:hover:not(:disabled) { background: #f8fafc; }
@media (max-width: 1200px) { .field-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .field-grid, .toggle-grid { grid-template-columns: 1fr; } .form-actions { flex-wrap: wrap; } }
</style>
