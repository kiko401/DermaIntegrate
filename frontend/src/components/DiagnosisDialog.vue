<script setup>
import { ref, watch, computed, onUnmounted } from 'vue'
import { useSSE } from '@/hooks/useSSE'

const props = defineProps({
  taskId: { type: String, default: null },
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['update:open'])

const { events, status, connect, close } = useSSE('')

// Typewriter state
const typedImage    = ref('')
const typedClinical = ref('')
const typedPathology = ref('')
const typedResult   = ref('')

// Serial queue: one section types at a time
const _queue = []
let _typing = false
let _intervalId = null
let _pauseId = null

function typeIn(target, text, speed = 6) {
  if (!text) return
  _queue.push({ target, text, speed })
  if (!_typing) _drainQueue()
}

function _drainQueue() {
  if (_queue.length === 0) { _typing = false; return }
  _typing = true
  const { target, text, speed } = _queue.shift()
  let i = 0
  _intervalId = setInterval(() => {
    target.value += text[i++]
    if (i >= text.length) {
      clearInterval(_intervalId); _intervalId = null
      _pauseId = setTimeout(_drainQueue, 280)
    }
  }, speed)
}

function clearTimers() {
  if (_intervalId) { clearInterval(_intervalId); _intervalId = null }
  if (_pauseId) { clearTimeout(_pauseId); _pauseId = null }
  _queue.length = 0
  _typing = false
}

function toText(val, indent = '') {
  if (val == null) return ''
  if (typeof val !== 'object') return String(val)
  if (Array.isArray(val)) return val.map(v => toText(v)).join(', ')
  return Object.entries(val)
    .filter(([, v]) => v != null && v !== '' && v !== false)
    .map(([k, v]) =>
      typeof v === 'object'
        ? `${indent}${k}:\n${toText(v, indent + '  ')}`
        : `${indent}${k}: ${v}`
    )
    .join('\n')
}

// ── 展示模型 V1：section-specific formatters ──────────────────────────
const MORPH_LABELS = {
  border: '边界特征', pigment_network: '色素网络',
  color_distribution: '颜色分布', vascular_pattern: '血管形态',
  special_structures: '特殊结构',
}
const CLINICAL_LABELS = {
  age: '年龄', gender: '性别', region: '病灶部位',
  itch: '瘙痒', grew: '增大趋势',
}
const PATHO_LABELS = {
  disease_type: '疾病类型', t_stage: 'T 分期',
  treatment_recommendations: '病理建议',
}
const PATHO_SHOW = new Set(['disease_type', 't_stage', 'treatment_recommendations'])

function boolStr(v) { return v === true ? '是' : v === false ? '否' : v }

function formatMorphology(morphology) {
  if (!morphology) return ''
  return Object.entries(morphology)
    .filter(([, v]) => v != null && v !== '' && v !== false)
    .map(([k, v]) => `${MORPH_LABELS[k] || k}: ${v}`)
    .join('\n')
}

function formatClinical(data) {
  if (!data) return ''
  const flat = {
    ...(data.patient_info || {}),
    ...(data.lesion_clinical || {}),
    ...(data.lesion_symptoms || {}),
  }
  return Object.entries(flat)
    .filter(([k, v]) => CLINICAL_LABELS[k] && v != null && v !== '' && v !== false)
    .map(([k, v]) => `${CLINICAL_LABELS[k]}: ${boolStr(v)}`)
    .join('\n')
}

function formatPathology(data) {
  if (!data) return ''
  return Object.entries(data)
    .filter(([k, v]) => PATHO_SHOW.has(k) && v != null && v !== '' && v !== false)
    .map(([k, v]) => `${PATHO_LABELS[k]}: ${v}`)
    .join('\n')
}
// ─────────────────────────────────────────────────────────────────────

watch(() => props.open, (val) => {
  if (val && props.taskId) {
    events.value = []
    typedImage.value = ''; typedClinical.value = ''
    typedPathology.value = ''; typedResult.value = ''
    clearTimers()
    connect(`/api/tasks/${props.taskId}/stream`)
  } else {
    close(); clearTimers()
  }
})

const imageEvent     = computed(() => events.value.find(e => e.type === 'image_done'))
const clinicalEvent  = computed(() => events.value.find(e => e.type === 'clinical_done'))
const pathologyEvent = computed(() => events.value.find(e => e.type === 'pathology_done'))
const resultEvent    = computed(() => events.value.find(e => e.type === 'result'))
const errorEvent     = computed(() => events.value.find(e => e.type === 'error'))

watch(imageEvent, (e) => {
  if (!e) return
  typedImage.value = ''
  typeIn(typedImage, formatMorphology(e.data?.morphology))
})
watch(clinicalEvent, (e) => {
  if (!e) return
  typedClinical.value = ''
  typeIn(typedClinical, formatClinical(e.data))
})
watch(pathologyEvent, (e) => {
  if (!e) return
  typedPathology.value = ''
  typeIn(typedPathology, formatPathology(e.data))
})
watch(resultEvent, (e) => {
  if (!e) return
  typedResult.value = ''
  const d = e.data
  const lines = []
  if (d?.risk_level) lines.push(`风险等级: ${d.risk_level}`)
  if (d?.key_concerns?.length) {
    lines.push('\n核心关注:')
    d.key_concerns.forEach(c => lines.push(`• ${c.item}${c.source_id ? ' [' + c.source_id + ']' : ''}`))
  }
  if (d?.recommendations) {
    lines.push('\n建议:')
    const recs = Array.isArray(d.recommendations) ? d.recommendations : [d.recommendations]
    recs.forEach(r => lines.push(`• ${typeof r === 'object' ? (r.item ?? JSON.stringify(r)) : r}`))
  }
  if (d?.differential?.length) {
    lines.push('\n鉴别诊断:')
    d.differential.forEach(item => lines.push(`• ${typeof item === 'string' ? item : item.name ?? JSON.stringify(item)}`))
  }
  if (d?.disclaimer) lines.push(`\n${d.disclaimer}`)
  typeIn(typedResult, lines.join('\n'))
})

const statusText = computed(() => ({
  idle: '', connecting: '正在连接 AI 服务...', open: '推理进行中...',
  closed: '', error: '连接异常',
}[status.value] ?? ''))

const stepItems = [
  { title: '图像分析' }, { title: '病历解析' },
  { title: '病理分期' }, { title: '最终报告' },
]

const currentStep = computed(() => {
  if (resultEvent.value) return 4
  if (pathologyEvent.value) return 3
  if (clinicalEvent.value) return 2
  if (imageEvent.value) return 1
  return 0
})

const riskClass = computed(() => {
  const level = resultEvent.value?.data?.risk_level || ''
  if (level.includes('高') || level.toLowerCase().includes('high')) return 'high'
  if (level.includes('中') || level.toLowerCase().includes('med')) return 'medium'
  return 'low'
})

function handleClose() { close(); clearTimers(); emit('update:open', false) }

onUnmounted(() => { close(); clearTimers() })
</script>

<style scoped>
.drawer-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 32px;
}

.sec-card {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.sec-card.pending {
  display: flex;
  align-items: center;
  color: #94a3b8;
  font-size: 13px;
}
.sec-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}
.sec-text {
  white-space: pre-wrap;
  font-size: 13px;
  margin: 0;
  font-family: inherit;
  line-height: 1.75;
  color: #334155;
}

/* Final report */
.report-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
  overflow: hidden;
  margin-top: 8px;
}
.risk-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(0,0,0,0.05);
}
.risk-banner.risk-high   { background: #fef2f2; }
.risk-banner.risk-medium { background: #fffbeb; }
.risk-banner.risk-low    { background: #f0fdf4; }

.risk-label { font-size: 12px; color: #64748b; font-weight: 500; }
.risk-value { font-size: 20px; font-weight: 800; }
.risk-banner.risk-high   .risk-value { color: #dc2626; }
.risk-banner.risk-medium .risk-value { color: #d97706; }
.risk-banner.risk-low    .risk-value { color: #059669; }

.report-text {
  white-space: pre-wrap;
  font-size: 13px;
  margin: 0;
  font-family: inherit;
  line-height: 1.85;
  color: #1e293b;
}
</style>

<template>
  <a-drawer
    :open="open"
    placement="right"
    :width="640"
    :body-style="{ padding: 0, display: 'flex', flexDirection: 'column' }"
    @close="handleClose"
  >
    <template #title>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-weight:600;color:#1e293b">AI 辅助诊断</span>
        <a-tag v-if="status === 'connecting' || status === 'open'" color="processing" style="margin:0">推理中</a-tag>
        <a-tag v-else-if="resultEvent" color="success" style="margin:0">完成</a-tag>
        <a-tag v-else-if="errorEvent" color="error" style="margin:0">错误</a-tag>
      </div>
    </template>

    <!-- Progress -->
    <div style="padding:16px 24px 14px;border-bottom:1px solid #f1f5f9">
      <a-steps :current="currentStep" size="small" :items="stepItems" />
    </div>

    <!-- Scrollable content -->
    <div class="drawer-scroll">

      <a-alert v-if="errorEvent" type="error"
        :message="errorEvent.data?.message || '推理过程出现错误'"
        show-icon style="margin-bottom:16px" />

      <!-- 图像分析 -->
      <div v-if="imageEvent" class="sec-card">
        <div class="sec-label">图像分析</div>
        <img v-if="imageEvent.data?.image_url" :src="imageEvent.data.image_url"
          style="max-width:100%;max-height:200px;border-radius:6px;margin-bottom:10px;display:block" />
        <pre class="sec-text">{{ typedImage }}</pre>
      </div>
      <div v-else-if="status === 'open' || status === 'connecting'" class="sec-card pending">
        <a-spin size="small" style="margin-right:8px" />图像分析中…
      </div>

      <!-- 病历解析 -->
      <div v-if="clinicalEvent" class="sec-card">
        <div class="sec-label">病历解析</div>
        <pre class="sec-text">{{ typedClinical }}</pre>
      </div>
      <div v-else-if="imageEvent && status === 'open'" class="sec-card pending">
        <a-spin size="small" style="margin-right:8px" />病历解析中…
      </div>

      <!-- 病理分期 -->
      <div v-if="pathologyEvent" class="sec-card">
        <div class="sec-label">病理分期</div>
        <pre class="sec-text">{{ typedPathology }}</pre>
      </div>

      <!-- 最终报告 -->
      <div v-if="resultEvent" class="report-card">
        <div class="risk-banner" :class="`risk-${riskClass}`">
          <span class="risk-label">风险等级</span>
          <span class="risk-value">{{ resultEvent.data?.risk_level || '—' }}</span>
          <a-tag
            :color="resultEvent.data?.status === 'complete' ? 'success' : 'warning'"
            style="margin-left:auto;margin-bottom:0"
          >{{ resultEvent.data?.status === 'complete' ? '完整报告' : '数据不足' }}</a-tag>
        </div>
        <div style="padding:16px 20px">
          <pre class="report-text">{{ typedResult }}</pre>
          <a-alert v-if="resultEvent.data?.status !== 'complete'" type="warning"
            message="部分模态数据缺失，结果仅供参考" show-icon style="margin-top:12px" />
        </div>
      </div>

    </div>
  </a-drawer>
</template>
