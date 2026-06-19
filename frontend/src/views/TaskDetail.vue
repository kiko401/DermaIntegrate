<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch } from '@/utils/api'
import { useSSE } from '@/hooks/useSSE'
import ImageCompare from '@/components/ImageCompare.vue'

const route  = useRoute()
const router = useRouter()
const taskId = route.params.taskId

const task    = ref(null)
const loading = ref(true)

const { events, status: sseStatus, connect, close } = useSSE('')

// ── Computed helpers ──────────────────────────────────────────
const imageEvent    = computed(() => events.value.find(e => e.type === 'image_done'))
const clinicalEvent = computed(() => events.value.find(e => e.type === 'clinical_done'))
const pathologyEvent= computed(() => events.value.find(e => e.type === 'pathology_done'))
const resultEvent   = computed(() => events.value.find(e => e.type === 'result'))
const errorEvent      = computed(() => events.value.find(e => e.type === 'error'))
const forceCloseEvent = computed(() => events.value.find(e => e.type === 'force_close'))

const isLive = computed(() =>
  sseStatus.value === 'connecting' || sseStatus.value === 'open'
)

const isSnapshot = ref(false)

const agentEvents = computed(() =>
  events.value.filter(e => ['image_done', 'clinical_done', 'pathology_done'].includes(e.type))
)

// ── Formatters ────────────────────────────────────────────────
const MORPH_LABELS = {
  border: '边界特征', pigment_network: '色素网络',
  color_distribution: '颜色分布', vascular_pattern: '血管形态',
  special_structures: '特殊结构',
}
const CLINICAL_LABELS = {
  // patient_info
  age: '年龄', gender: '性别', fitzpatrick_skin_type: '肤色分型',
  // lifestyle_history
  smoke: '吸烟史', drink: '饮酒史', pesticide_exposure: '农药接触史',
  // personal_history
  skin_cancer_history: '皮肤癌病史', other_cancer_history: '其他癌症病史',
  // lesion_clinical
  region: '病灶部位', diameter_1_mm: '病灶直径(mm)', elevation: '隆起',
  biopsed: '已活检',
  // lesion_symptoms
  itch: '瘙痒', hurt: '疼痛', changed: '形态变化', bleed: '出血', grew: '增大趋势',
}
const PATHO_LABELS = {
  disease_type: '疾病类型', t_stage: 'T 分期',
  treatment_recommendations: '病理建议',
}
const PATHO_SHOW = new Set(['disease_type', 't_stage', 'treatment_recommendations'])

function boolStr(v) { return v === true ? '是' : v === false ? '否' : v }

function morphItems() {
  const m = imageEvent.value?.data?.morphology
  if (!m) return []
  return Object.entries(m)
    .filter(([, v]) => v != null && v !== '' && v !== false)
    .map(([k, v]) => ({ label: MORPH_LABELS[k] || k, value: String(v) }))
}

function clinicalItems() {
  const d = clinicalEvent.value?.data
  if (!d) return []
  const flat = {
    ...(d.patient_info      || {}),
    ...(d.lifestyle_history || {}),
    ...(d.personal_history  || {}),
    ...(d.lesion_clinical   || {}),
    ...(d.lesion_symptoms   || {}),
  }
  return Object.entries(flat)
    .filter(([k, v]) => CLINICAL_LABELS[k] && v != null && v !== '')
    .map(([k, v]) => ({ label: CLINICAL_LABELS[k], value: String(boolStr(v)) }))
}

function pathologyItems() {
  const d = pathologyEvent.value?.data
  if (!d) return []
  return Object.entries(d)
    .filter(([k, v]) => PATHO_SHOW.has(k) && v != null && v !== '' && v !== false)
    .map(([k, v]) => ({ label: PATHO_LABELS[k] || k, value: String(v) }))
}

// ── Status helpers ────────────────────────────────────────────
function statusColor(s) {
  if (s === 'complete') return 'success'
  if (s === 'error' || s === 'failed') return 'error'
  return 'processing'
}
function statusLabel(s) {
  if (s === 'complete') return '完成'
  if (s === 'error' || s === 'failed') return '失败'
  if (s === 'pending') return '等待中'
  return '分析中'
}

const riskColor = computed(() => {
  const lv = resultEvent.value?.data?.risk_level || ''
  if (lv.includes('高') || lv.toLowerCase().includes('high')) return '#dc2626'
  if (lv.includes('中') || lv.toLowerCase().includes('med')) return '#d97706'
  return '#059669'
})
const riskBg = computed(() => {
  const lv = resultEvent.value?.data?.risk_level || ''
  if (lv.includes('高') || lv.toLowerCase().includes('high')) return '#fef2f2'
  if (lv.includes('中') || lv.toLowerCase().includes('med')) return '#fffbeb'
  return '#f0fdf4'
})
const riskBannerBg = computed(() => {
  const lv = resultEvent.value?.data?.risk_level || ''
  if (lv.includes('高') || lv.toLowerCase().includes('high')) return '#dc2626'
  if (lv.includes('中') || lv.toLowerCase().includes('med')) return '#d97706'
  return '#059669'
})

// ── Privacy helpers ───────────────────────────────────────────
function maskPhone(v) {
  if (!v || v.length < 7) return v || '—'
  return v.slice(0, 3) + '****' + v.slice(-4)
}
function maskIdCard(v) {
  if (!v || v.length < 10) return v || '—'
  return v.slice(0, 6) + '****' + v.slice(-4)
}

// ── Date helpers ──────────────────────────────────────────────
function fmtDate(v) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 10)
}
function fmtDateTime(v) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}
function calcAge(birthDate) {
  if (!birthDate) return null
  const d = new Date(birthDate)
  const now = new Date()
  return now.getFullYear() - d.getFullYear()
}

// ── Status sync: when SSE result arrives, update task.status locally ─
watch(resultEvent, (e) => {
  if (e && task.value) task.value.status = 'complete'
})
watch(errorEvent, (e) => {
  if (e && task.value) task.value.status = 'error'
})
watch(forceCloseEvent, (e) => {
  if (e && task.value) task.value.status = 'error'
})

// ── Load ──────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const res = await apiFetch(`/api/tasks/${taskId}`)
    if (res.ok) {
      task.value = await res.json()
      if (Array.isArray(task.value.result_snapshot) && task.value.result_snapshot.length) {
        events.value = task.value.result_snapshot
        isSnapshot.value = true
      } else if (task.value.status !== 'complete' && task.value.status !== 'error') {
        connect(`/api/tasks/${taskId}/stream`)
      }
    }
  } finally {
    loading.value = false
  }
})

onUnmounted(() => close())
</script>

<style scoped>
.page { padding: 24px 32px; background: #f5f7fa; min-height: 100%; }

.page-header {
  background: #fff;
  border-radius: 12px;
  padding: 18px 24px;
  margin-bottom: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07);
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.header-title { font-size: 17px; font-weight: 700; color: #1e293b; }
.header-meta { font-size: 12px; color: #94a3b8; }

.body-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.risk-top-banner {
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.risk-top-level {
  font-size: 18px;
  font-weight: 800;
  color: #fff;
  white-space: nowrap;
  flex-shrink: 0;
}
.risk-top-concerns {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.risk-top-concern-item {
  font-size: 12px;
  color: rgba(255,255,255,0.9);
  line-height: 1.5;
}
.risk-top-source {
  font-size: 11px;
  color: rgba(255,255,255,0.6);
  margin-left: 4px;
}

.card {
  background: #fff;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07);
}
.card:last-child { margin-bottom: 0; }

.card-title {
  font-size: 13px; font-weight: 600; color: #1e293b;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f5f9;
  display: flex; align-items: center; gap: 8px;
}
.card-dot { width: 3px; height: 14px; border-radius: 2px; background: #14B8A6; }

.kv-label { font-size: 11px; color: #94a3b8; margin-bottom: 3px; }
.kv-value { font-size: 13px; color: #334155; font-weight: 500; word-break: break-all; }

.desc-list { display: flex; flex-direction: column; gap: 7px; }
.desc-row { display: flex; gap: 12px; font-size: 13px; line-height: 1.5; }
.desc-key { color: #94a3b8; flex-shrink: 0; width: 80px; }
.desc-val { color: #334155; flex: 1; }

.morph-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.morph-item { background: #f8fafc; border-radius: 8px; padding: 10px 12px; }
.morph-label { font-size: 11px; font-weight: 600; color: #64748b; margin-bottom: 4px; }
.morph-val { font-size: 13px; color: #334155; line-height: 1.5; word-break: break-all; }

.concern-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.concern-item { display: flex; gap: 8px; font-size: 13px; color: #475569; }
.bullet { color: #14B8A6; font-weight: 700; flex-shrink: 0; }

.image-placeholder {
  background: #f8fafc; border: 1px dashed #cbd5e1;
  border-radius: 8px; padding: 32px;
  text-align: center; color: #94a3b8; font-size: 13px;
}

.empty-state { color: #94a3b8; font-size: 13px; padding: 12px 0; }

.coverage-bar-bg {
  height: 6px; border-radius: 3px; background: #e2e8f0;
  margin-top: 6px; overflow: hidden;
}
.coverage-bar-fill {
  height: 100%; border-radius: 3px; background: #14B8A6;
  transition: width 0.3s;
}

.snapshot-banner {
  background: #f0fdf4; border-radius: 8px; padding: 12px 16px;
  font-size: 13px; color: #059669; margin-bottom: 14px;
  border: 1px solid #bbf7d0;
}

.live-banner {
  background: #fff7ed; border-radius: 8px; padding: 12px 16px;
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; color: #ea580c; margin-bottom: 14px;
  border: 1px solid #fed7aa;
}
</style>

<template>
  <div class="page">

    <div v-if="loading" style="display:flex;align-items:center;justify-content:center;padding:80px 0">
      <a-spin size="large" />
    </div>

    <template v-else-if="!task">
      <a-result status="404" title="任务不存在" sub-title="请检查 Task ID 是否正确">
        <template #extra>
          <a-button type="primary" @click="router.push('/tasks')">返回记录页</a-button>
        </template>
      </a-result>
    </template>

    <template v-else>

      <!-- ── Header ─────────────────────────────────────── -->
      <div class="page-header">
        <a-button size="small" @click="router.back()">← 返回</a-button>
        <span class="header-title">AI 分析详情</span>
        <a-tag :color="statusColor(task.status)" style="margin:0">{{ statusLabel(task.status) }}</a-tag>
        <span class="header-meta" style="font-family:monospace;font-size:11px">{{ task.task_id }}</span>
        <span v-if="task.patient_name" class="header-meta">
          患者：{{ task.patient_name }}（{{ task.gender === 1 ? '男' : task.gender === 2 ? '女' : '—' }}
          {{ calcAge(task.birth_date) != null ? '/' + calcAge(task.birth_date) + '岁' : '' }}）
          ID: {{ task.patient_id }}
        </span>
      </div>

      <!-- ── Body ───────────────────────────────────────── -->
      <div class="body-grid">

        <!-- Mode banners -->
        <div v-if="isSnapshot && !isLive" class="snapshot-banner">
          🔵 当前为历史快照，生成时间：{{ fmtDateTime(task.created_at) }}
        </div>
        <div v-if="isLive" class="live-banner">
          <a-spin size="small" />
          ⏳ 实时推理流（SSE 连接中）
        </div>

        <!-- Error banner -->
        <a-alert v-if="errorEvent" type="error"
          :message="errorEvent.data?.message || '推理过程出现错误'"
          show-icon style="margin-bottom:0" />

        <!-- 管理员强制释放提示 -->
        <a-alert v-if="forceCloseEvent" type="warning"
          message="会话已被管理员强制释放"
          show-icon style="margin-bottom:0" />

        <!-- 风险前置横幅：result 到达后显示 -->
        <div v-if="resultEvent" class="risk-top-banner" :style="`background:${riskBannerBg}`">
          <div class="risk-top-level">⚠️ 风险等级：{{ resultEvent.data?.risk_level || '—' }}</div>
          <div v-if="resultEvent.data?.key_concerns?.length" class="risk-top-concerns">
            <span v-for="(c, i) in resultEvent.data.key_concerns.slice(0, 3)" :key="i" class="risk-top-concern-item">
              {{ c.item || c }}
              <span v-if="c.source_id" class="risk-top-source">[{{ c.source_id }}]</span>
            </span>
          </div>
          <a-tag
            :color="resultEvent.data?.status === 'complete' ? 'success' : 'warning'"
            style="margin-left:auto;flex-shrink:0;align-self:flex-start"
          >{{ resultEvent.data?.status === 'complete' ? '完整报告' : '数据不足' }}</a-tag>
          <a-button
            size="small"
            style="flex-shrink:0;align-self:flex-start;background:rgba(255,255,255,0.2);border-color:rgba(255,255,255,0.4);color:#fff"
            @click="router.push(`/integration?patient_id=${task.patient_id}`)"
          >重新分析</a-button>
        </div>

        <!-- Agent cards: vertical, in arrival order -->
        <template v-for="e in agentEvents" :key="e.type">

          <!-- 影像分析 -->
          <div v-if="e.type === 'image_done'" class="card">
            <div class="card-title"><span class="card-dot"></span>影像分析</div>
            <div style="margin-bottom:16px">
              <ImageCompare
                :left-url="task.pacs_image_url || null"
                :right-url="imageEvent.data?.image_url || null"
                left-label="原图"
                right-label="AI 证据图"
              />
              <div v-if="!task.pacs_image_url" style="font-size:11px;color:#94a3b8;margin-top:6px">
                原图未关联 PACS 记录；右侧为 AI 证据热力图。
              </div>
              <div v-else style="font-size:11px;color:#94a3b8;margin-top:6px">
                左侧 PACS 原图，右侧 AI 证据热力图。拖动分割线对比。
              </div>
            </div>
            <div
              v-if="imageEvent.data?.coverage != null || imageEvent.data?.location"
              style="display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;margin-bottom:14px"
            >
              <div v-if="imageEvent.data?.coverage != null">
                <div class="kv-label">病灶覆盖率</div>
                <div class="kv-value" style="margin-bottom:4px">
                  {{ (imageEvent.data.coverage * 100).toFixed(1) }}%
                </div>
                <div class="coverage-bar-bg">
                  <div class="coverage-bar-fill"
                    :style="`width:${Math.min(100, imageEvent.data.coverage * 100).toFixed(1)}%`">
                  </div>
                </div>
              </div>
              <div v-if="imageEvent.data?.location">
                <div class="kv-label">病灶位置</div>
                <div class="kv-value">{{ imageEvent.data.location }}</div>
              </div>
            </div>
            <div v-if="morphItems().length">
              <div style="font-size:12px;color:#64748b;margin-bottom:10px;font-weight:600">形态学特征</div>
              <div class="morph-grid">
                <div v-for="item in morphItems()" :key="item.label" class="morph-item">
                  <div class="morph-label">{{ item.label }}</div>
                  <div class="morph-val">{{ item.value }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 临床文本分析 -->
          <div v-else-if="e.type === 'clinical_done'" class="card">
            <div class="card-title"><span class="card-dot"></span>临床文本分析</div>
            <div v-if="task.chief_complaint" style="margin-bottom:14px">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600">主诉原文</div>
              <div style="font-size:13px;color:#334155;background:#f8fafc;border-radius:6px;padding:10px 12px;line-height:1.6">
                {{ task.chief_complaint }}
              </div>
            </div>
            <div style="font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">AI 提取摘要</div>
            <div v-if="clinicalItems().length" class="desc-list">
              <div v-for="item in clinicalItems()" :key="item.label" class="desc-row">
                <span class="desc-key">{{ item.label }}</span>
                <span class="desc-val">{{ item.value }}</span>
              </div>
            </div>
            <div v-else class="empty-state">AI 已解析病历，暂无可展示的结构化字段</div>
          </div>

          <!-- 病理/检验 -->
          <div v-else-if="e.type === 'pathology_done'" class="card">
            <div class="card-title"><span class="card-dot"></span>病理 / 检验证据</div>
            <div class="desc-list">
              <div v-for="item in pathologyItems()" :key="item.label" class="desc-row">
                <span class="desc-key">{{ item.label }}</span>
                <span class="desc-val">{{ item.value }}</span>
              </div>
            </div>
          </div>

        </template>

        <!-- Live waiting placeholders -->
        <template v-if="isLive">
          <div v-if="!agentEvents.find(e => e.type === 'image_done')" class="card">
            <div class="card-title"><span class="card-dot"></span>影像分析</div>
            <div class="empty-state"><a-spin size="small" style="margin-right:6px" />分析中…</div>
          </div>
          <div v-if="!agentEvents.find(e => e.type === 'clinical_done')" class="card">
            <div class="card-title"><span class="card-dot"></span>临床文本分析</div>
            <div class="empty-state"><a-spin size="small" style="margin-right:6px" />分析中…</div>
          </div>
          <div v-if="!agentEvents.find(e => e.type === 'pathology_done')" class="card">
            <div class="card-title"><span class="card-dot"></span>病理 / 检验证据</div>
            <div class="empty-state"><a-spin size="small" style="margin-right:6px" />分析中…</div>
          </div>
        </template>

        <!-- 综合研判区：仅建议处理 + 鉴别诊断 + 免责声明 -->
        <div class="card" v-if="resultEvent" style="margin-bottom:0">
          <div class="card-title"><span class="card-dot"></span>综合研判</div>

          <div v-if="resultEvent.data?.recommendations" style="margin-bottom:14px">
            <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600">建议处理</div>
            <div class="concern-list">
              <div v-for="(r, i) in Array.isArray(resultEvent.data.recommendations)
                  ? resultEvent.data.recommendations
                  : [resultEvent.data.recommendations]"
                :key="i" class="concern-item">
                <span class="bullet">•</span>
                <span>{{ typeof r === 'object' ? (r.item ?? JSON.stringify(r)) : r }}</span>
              </div>
            </div>
          </div>

          <div v-if="resultEvent.data?.differential?.length">
            <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600">鉴别诊断</div>
            <div class="concern-list">
              <div v-for="(d, i) in resultEvent.data.differential" :key="i" class="concern-item">
                <span class="bullet">•</span>
                <span>{{ typeof d === 'string' ? d : d.name ?? JSON.stringify(d) }}</span>
              </div>
            </div>
          </div>

          <div v-if="resultEvent.data?.disclaimer" style="margin-top:12px">
            <a-alert type="info" :message="resultEvent.data.disclaimer" show-icon />
          </div>
        </div>

      </div>

    </template>
  </div>
</template>
