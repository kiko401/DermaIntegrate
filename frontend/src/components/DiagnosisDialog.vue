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

function handleClose() { close(); clearTimers(); emit('update:open', false) }

onUnmounted(() => { close(); clearTimers() })
</script>

<template>
  <a-modal :open="open" title="AI 辅助诊断" width="760px" :footer="null" @cancel="handleClose">

    <div v-if="statusText" style="margin-bottom:12px; color:#8c8c8c; font-size:13px">
      <a-spin v-if="status === 'connecting' || status === 'open'" size="small" style="margin-right:6px" />
      {{ statusText }}
    </div>

    <a-alert v-if="errorEvent" type="error"
      :message="errorEvent.data?.message || '推理过程出现错误'" show-icon style="margin-bottom:12px" />

    <!-- 图像分析 -->
    <template v-if="imageEvent">
      <a-card size="small" title="🖼️ 图像分析" style="margin-bottom:12px">
        <div v-if="imageEvent.data?.image_url" style="margin-bottom:8px">
          <img :src="imageEvent.data.image_url" alt="热力图"
            style="max-width:100%; max-height:300px; border-radius:4px" />
        </div>
        <pre style="white-space:pre-wrap; font-size:13px; margin:0; font-family:inherit; line-height:1.7">{{ typedImage }}</pre>
      </a-card>
    </template>
    <template v-else-if="status === 'open' || status === 'connecting'">
      <a-card size="small" style="margin-bottom:12px; color:#bfbfbf">
        <a-spin size="small" style="margin-right:6px" />图像分析中...
      </a-card>
    </template>

    <!-- 病历解析 -->
    <template v-if="clinicalEvent">
      <a-card size="small" title="📋 病历解析" style="margin-bottom:12px">
        <pre style="white-space:pre-wrap; font-size:13px; margin:0; font-family:inherit; line-height:1.7">{{ typedClinical }}</pre>
      </a-card>
    </template>
    <template v-else-if="imageEvent && status === 'open'">
      <a-card size="small" style="margin-bottom:12px; color:#bfbfbf">
        <a-spin size="small" style="margin-right:6px" />病历解析中...
      </a-card>
    </template>

    <!-- 病理分期 -->
    <template v-if="pathologyEvent">
      <a-card size="small" title="🔬 病理分期" style="margin-bottom:12px">
        <pre style="white-space:pre-wrap; font-size:13px; margin:0; font-family:inherit; line-height:1.7">{{ typedPathology }}</pre>
      </a-card>
    </template>

    <!-- 最终报告 -->
    <template v-if="resultEvent">
      <a-divider />
      <a-card size="small" style="margin-bottom:4px">
        <template #title>
          📄 最终报告
          <a-tag :color="resultEvent.data?.status === 'complete' ? 'success' : 'warning'" style="margin-left:8px">
            {{ resultEvent.data?.status === 'complete' ? '完整' : '数据不足' }}
          </a-tag>
        </template>
        <pre style="white-space:pre-wrap; font-size:13px; margin:0; font-family:inherit; line-height:1.7">{{ typedResult }}</pre>
        <a-alert v-if="resultEvent.data?.status !== 'complete'" type="warning"
          message="部分模态数据缺失，结果仅供参考" show-icon style="margin-top:8px" />
      </a-card>
    </template>

    <div style="text-align:right; margin-top:16px">
      <a-button @click="handleClose">关闭</a-button>
    </div>

  </a-modal>
</template>
