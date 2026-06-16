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
const errorEvent    = computed(() => events.value.find(e => e.type === 'error'))

const isLive = computed(() =>
  sseStatus.value === 'connecting' || sseStatus.value === 'open'
)

// ── Formatters ────────────────────────────────────────────────
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
  const flat = { ...(d.patient_info || {}), ...(d.lesion_clinical || {}), ...(d.lesion_symptoms || {}) }
  return Object.entries(flat)
    .filter(([k, v]) => CLINICAL_LABELS[k] && v != null && v !== '' && v !== false)
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

// ── Load ──────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const res = await apiFetch(`/api/tasks/${taskId}`)
    if (res.ok) {
      task.value = await res.json()
      if (Array.isArray(task.value.result_snapshot) && task.value.result_snapshot.length) {
        events.value = task.value.result_snapshot
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
.header-actions { margin-left: auto; display: flex; gap: 8px; }

.body-grid {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 16px;
  align-items: start;
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

.kv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.kv-item { }
.kv-label { font-size: 11px; color: #94a3b8; margin-bottom: 3px; }
.kv-value { font-size: 13px; color: #334155; font-weight: 500; word-break: break-all; }

.desc-list { display: flex; flex-direction: column; gap: 7px; }
.desc-row { display: flex; gap: 12px; font-size: 13px; line-height: 1.5; }
.desc-key { color: #94a3b8; flex-shrink: 0; width: 80px; }
.desc-val { color: #334155; flex: 1; }

.risk-banner {
  border-radius: 8px; padding: 14px 18px;
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 14px;
}
.risk-label { font-size: 12px; color: #64748b; }
.risk-value { font-size: 24px; font-weight: 800; }

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

.live-banner {
  background: #eff6ff; border-radius: 8px; padding: 12px 16px;
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; color: #2563EB; margin-bottom: 14px;
}

.sidebar-card { margin-bottom: 12px; }
.sidebar-card:last-child { margin-bottom: 0; }

.action-btn { width: 100%; margin-bottom: 8px; }
.action-btn:last-child { margin-bottom: 0; }
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
        <span class="header-meta">{{ fmtDateTime(task.created_at) }}</span>
        <span class="header-meta" style="font-family:monospace;font-size:11px">{{ task.task_id }}</span>
        <div class="header-actions">
          <a-button size="small" @click="router.push(`/patients?patient_id=${task.patient_id}`)">重新分析</a-button>
        </div>
      </div>

      <!-- ── Body ───────────────────────────────────────── -->
      <div class="body-grid">

        <!-- Left: main analysis content -->
        <div>

          <!-- Live banner -->
          <div v-if="isLive" class="live-banner">
            <a-spin size="small" />
            AI 推理进行中，请稍候…
          </div>

          <!-- Error banner -->
          <a-alert v-if="errorEvent" type="error"
            :message="errorEvent.data?.message || '推理过程出现错误'"
            show-icon style="margin-bottom:14px" />

          <!-- 综合结论 -->
          <div class="card" v-if="resultEvent">
            <div class="card-title"><span class="card-dot"></span>综合结论</div>
            <div class="risk-banner" :style="`background:${riskBg}`">
              <div>
                <div class="risk-label">风险等级</div>
                <div class="risk-value" :style="`color:${riskColor}`">
                  {{ resultEvent.data?.risk_level || '—' }}
                </div>
              </div>
              <a-tag
                :color="resultEvent.data?.status === 'complete' ? 'success' : 'warning'"
                style="margin-left:auto"
              >{{ resultEvent.data?.status === 'complete' ? '完整报告' : '数据不足' }}</a-tag>
            </div>

            <div v-if="resultEvent.data?.key_concerns?.length" style="margin-bottom:14px">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600">核心关注</div>
              <div class="concern-list">
                <div v-for="(c, i) in resultEvent.data.key_concerns" :key="i" class="concern-item">
                  <span class="bullet">•</span>
                  <span>{{ c.item || c }}
                    <span v-if="c.source_id" style="color:#94a3b8;font-size:11px">[{{ c.source_id }}]</span>
                  </span>
                </div>
              </div>
            </div>

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
          <div v-else-if="!isLive" class="card">
            <div class="card-title"><span class="card-dot"></span>综合结论</div>
            <div class="empty-state">暂无综合结论</div>
          </div>

          <!-- 影像分析 -->
          <div class="card">
            <div class="card-title"><span class="card-dot"></span>影像分析</div>
            <template v-if="imageEvent">

              <!-- 对比组件：左侧 PACS 原图（若有关联），右侧热力图/证据图 -->
              <div style="margin-bottom:16px">
                <ImageCompare
                  :left-url="task.pacs_image_url || null"
                  :right-url="imageEvent.data?.image_url || null"
                  left-label="原图"
                  right-label="AI 证据图"
                />
                <div v-if="!task.pacs_image_url" style="font-size:11px;color:#94a3b8;margin-top:6px">
                  原图未关联 PACS 记录（旧任务或手工上传）；右侧为 AI 证据热力图。
                </div>
                <div v-else style="font-size:11px;color:#94a3b8;margin-top:6px">
                  左侧为 PACS 原图，右侧为 AI 证据热力图。拖动分割线对比。
                </div>
              </div>

              <!-- coverage / location 结构化展示 -->
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

              <!-- morphology -->
              <div v-if="morphItems().length">
                <div style="font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">形态学特征</div>
                <div class="desc-list">
                  <div v-for="item in morphItems()" :key="item.label" class="desc-row">
                    <span class="desc-key">{{ item.label }}</span>
                    <span class="desc-val">{{ item.value }}</span>
                  </div>
                </div>
              </div>

            </template>
            <template v-else>
              <div class="image-placeholder">
                影像预览区 — 原图 / AI 证据图对比（待分析或未上传影像）
              </div>
              <div class="empty-state">
                <span v-if="isLive"><a-spin size="small" style="margin-right:6px" />影像分析进行中…</span>
                <span v-else>暂无影像分析结果</span>
              </div>
            </template>
          </div>

          <!-- 临床文本分析 -->
          <div class="card">
            <div class="card-title"><span class="card-dot"></span>临床文本分析</div>
            <div v-if="task.chief_complaint" style="margin-bottom:14px">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px;font-weight:600">主诉原文</div>
              <div style="font-size:13px;color:#334155;background:#f8fafc;border-radius:6px;padding:10px 12px;line-height:1.6">
                {{ task.chief_complaint }}
              </div>
            </div>
            <template v-if="clinicalEvent">
              <div style="font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">AI 提取摘要</div>
              <div class="desc-list">
                <div v-for="item in clinicalItems()" :key="item.label" class="desc-row">
                  <span class="desc-key">{{ item.label }}</span>
                  <span class="desc-val">{{ item.value }}</span>
                </div>
              </div>
            </template>
            <div v-else class="empty-state">
              <span v-if="isLive"><a-spin size="small" style="margin-right:6px" />病历解析进行中…</span>
              <span v-else>暂无临床分析结果</span>
            </div>
          </div>

          <!-- 病理/检验 -->
          <div class="card">
            <div class="card-title"><span class="card-dot"></span>病理 / 检验证据</div>
            <template v-if="pathologyEvent">
              <div class="desc-list">
                <div v-for="item in pathologyItems()" :key="item.label" class="desc-row">
                  <span class="desc-key">{{ item.label }}</span>
                  <span class="desc-val">{{ item.value }}</span>
                </div>
              </div>
            </template>
            <div v-else class="empty-state">
              <span v-if="isLive"><a-spin size="small" style="margin-right:6px" />病理分析进行中…</span>
              <span v-else>暂无病理结果</span>
            </div>
          </div>

        </div>

        <!-- Right: sidebar -->
        <div>

          <!-- 患者信息 -->
          <div class="card sidebar-card">
            <div class="card-title"><span class="card-dot"></span>患者信息</div>
            <div class="kv-grid">
              <div class="kv-item">
                <div class="kv-label">姓名</div>
                <div class="kv-value">{{ task.patient_name || '—' }}</div>
              </div>
              <div class="kv-item">
                <div class="kv-label">性别</div>
                <div class="kv-value">{{ task.gender === 1 ? '男' : task.gender === 2 ? '女' : '—' }}</div>
              </div>
              <div class="kv-item">
                <div class="kv-label">年龄</div>
                <div class="kv-value">
                  {{ calcAge(task.birth_date) != null ? calcAge(task.birth_date) + ' 岁' : '—' }}
                </div>
              </div>
              <div class="kv-item">
                <div class="kv-label">出生日期</div>
                <div class="kv-value">{{ fmtDate(task.birth_date) }}</div>
              </div>
              <div class="kv-item" style="grid-column:span 2">
                <div class="kv-label">手机</div>
                <div class="kv-value">{{ maskPhone(task.phone) }}</div>
              </div>
              <div class="kv-item" style="grid-column:span 2">
                <div class="kv-label">身份证</div>
                <div class="kv-value">{{ maskIdCard(task.id_card) }}</div>
              </div>
              <div class="kv-item" style="grid-column:span 2">
                <div class="kv-label">内部患者 ID</div>
                <div class="kv-value" style="font-family:monospace;font-size:12px">{{ task.patient_id || '—' }}</div>
              </div>
            </div>
          </div>

          <!-- 就诊信息 -->
          <div class="card sidebar-card">
            <div class="card-title"><span class="card-dot"></span>就诊信息</div>
            <div class="desc-list">
              <div class="desc-row">
                <span class="desc-key">就诊日期</span>
                <span class="desc-val">{{ fmtDate(task.visit_date) }}</span>
              </div>
              <div class="desc-row">
                <span class="desc-key">主诉</span>
                <span class="desc-val">{{ task.chief_complaint || '—' }}</span>
              </div>
              <div class="desc-row">
                <span class="desc-key">Visit ID</span>
                <span class="desc-val" style="font-family:monospace;font-size:11px">{{ task.visit_id || '—' }}</span>
              </div>
            </div>
          </div>

        </div>
      </div>

    </template>
  </div>
</template>
