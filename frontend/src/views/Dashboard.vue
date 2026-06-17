<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../utils/api.js'

const router = useRouter()
const tasks = ref([])
const aiHealthy = ref(null)
const hisHealthy = ref(null)
const searchKeyword = ref('')
const syncTime = ref('')
const aiResponseMs = ref(null)

function formatHHMM(d) {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const SEVEN_DAYS = 7 * 24 * 60 * 60 * 1000

function timeAgo(val) {
  if (!val) return '—'
  const m = Math.floor((Date.now() - new Date(val)) / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

function shortTime(val) {
  return val ? String(val).replace('T', ' ').slice(0, 16) : '—'
}

function goSearch() {
  const q = searchKeyword.value.trim()
  router.push(q ? `/patients?q=${encodeURIComponent(q)}` : '/patients')
}

// 续办区1：按最近任务时间去重，最多3条（来源：任务列表）
const recentPatients = computed(() => {
  const seen = new Set()
  const out = []
  for (const t of [...tasks.value].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))) {
    const key = t.patient_name || '未知'
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ name: key, summary: t.chief_complaint || '—', time: timeAgo(t.created_at), patientId: t.patient_id })
    if (out.length === 3) break
  }
  return out
})

// 续办区2：进行中任务
const ongoingTasks = computed(() =>
  tasks.value.filter(t => ['pending', 'processing', 'analyzing'].includes(t.status)).slice(0, 5)
)

// 异常区1：近7天失败任务
const failedTasks = computed(() => {
  const cutoff = Date.now() - SEVEN_DAYS
  return tasks.value.filter(t =>
    ['error', 'failed'].includes(t.status) && new Date(t.created_at) > cutoff
  ).slice(0, 5)
})

function riskLevel(task) {
  try {
    const evts = typeof task.result_snapshot === 'string' ? JSON.parse(task.result_snapshot) : task.result_snapshot
    return evts?.find(e => e.type === 'result')?.data?.risk_level || '—'
  } catch { return '—' }
}

// 异常区2：近7天中高风险（result_snapshot解析）
const highRiskTasks = computed(() => {
  const cutoff = Date.now() - SEVEN_DAYS
  return tasks.value.filter(t => {
    if (t.status !== 'complete' || new Date(t.created_at) <= cutoff) return false
    try {
      const evts = typeof t.result_snapshot === 'string' ? JSON.parse(t.result_snapshot) : t.result_snapshot
      if (!Array.isArray(evts)) return false
      const lv = evts.find(e => e.type === 'result')?.data?.risk_level || ''
      return lv.includes('高') || lv.includes('中') || lv.toLowerCase().includes('high') || lv.toLowerCase().includes('med')
    } catch { return false }
  }).slice(0, 5)
})

// 异常区3：服务告警
const serviceAlerts = computed(() => {
  const alerts = []
  if (aiHealthy.value === false) {
    alerts.push({ label: 'AI 推理服务当前不可用', desc: '暂时无法发起新的分析任务，请稍后重试或联系系统管理员' })
    alerts.push({ label: '流式结果推送异常', desc: '分析结果可能无法实时展示，可在 AI 分析记录页查看历史快照' })
  }
  if (hisHealthy.value === false) {
    alerts.push({ label: 'HIS 数据源连接断开', desc: '临床视图中的病历数据可能无法加载，请检查 HIS 服务状态' })
  }
  return alerts
})

onMounted(async () => {
  const [tRes, hRes, hisRes] = await Promise.allSettled([
    apiFetch('/api/tasks'),
    fetch('/api/health/ai'),
    fetch('/api/health/his'),
  ])
  if (tRes.status === 'fulfilled' && tRes.value.ok) tasks.value = await tRes.value.json()
  if (hRes.status === 'fulfilled' && hRes.value.ok) {
    const h = await hRes.value.json()
    aiHealthy.value = h.ok === true
    aiResponseMs.value = h.response_time_ms ?? null
  } else {
    aiHealthy.value = false
  }
  hisHealthy.value = hisRes.status === 'fulfilled' && hisRes.value.ok
  syncTime.value = formatHHMM(new Date())
})
</script>

<template>
  <div class="page">

    <!-- 标题区 -->
    <div class="page-header">
      <div class="section-title">首页</div>
      <div class="page-sub">续办事项 · 异常提醒 · 风险预警</div>
    </div>

    <!-- 搜索工具条 -->
    <div class="search-bar">
      <a-input
        v-model:value="searchKeyword"
        placeholder="搜索患者姓名 / 手机号 / 身份证号"
        allow-clear
        class="search-input"
        @pressEnter="goSearch"
      />
      <a-button type="primary" class="search-btn" @click="goSearch">检索患者</a-button>
    </div>

    <!-- 第一行：续办双卡 -->
    <div class="two-col row-card">

      <div class="card equal-card">
        <div class="card-head">
          <div>
            <div class="card-title">近期活跃病例</div>
            <div class="card-sub">按最近任务时间 · 点击进入临床视图</div>
          </div>
          <span class="weak-link" @click="router.push('/patients')">查看全部患者</span>
        </div>
        <div class="card-body">
          <div v-if="recentPatients.length === 0" class="empty-tip">暂无记录</div>
          <div v-for="p in recentPatients" :key="p.name" class="item-row"
               @click="router.push(p.patientId ? '/integration?patient_id=' + p.patientId : '/integration')"
               style="cursor:pointer">
            <div class="avatar blue">{{ p.name[0] }}</div>
            <div class="item-info">
              <div class="item-name">{{ p.name }}</div>
              <div class="item-sub">{{ p.summary }}</div>
            </div>
            <div class="item-time">{{ p.time }}</div>
          </div>
        </div>
      </div>

      <div class="card equal-card">
        <div class="card-head">
          <div>
            <div class="card-title">进行中的分析</div>
            <div class="card-sub">当前仍在运行的 AI 分析任务</div>
          </div>
          <span class="weak-link" @click="router.push('/tasks?status=processing')">查看全部任务</span>
        </div>
        <div class="card-body">
          <div v-if="ongoingTasks.length === 0" class="empty-tip">当前无进行中任务</div>
          <div v-for="t in ongoingTasks" :key="t.task_id" class="item-row"
               @click="router.push('/tasks/' + t.task_id)" style="cursor:pointer">
            <div class="avatar purple">{{ (t.patient_name || '?')[0] }}</div>
            <div class="item-info">
              <div class="item-name">{{ t.patient_name || '未知' }}</div>
              <div class="item-sub">{{ t.chief_complaint || '—' }}</div>
            </div>
            <a-tag color="processing" style="margin:0;font-size:11px;flex-shrink:0">
              {{ t.status === 'pending' ? '等待中' : '分析中' }}
            </a-tag>
          </div>
        </div>
      </div>

    </div>

    <!-- 第二行：异常双卡 -->
    <div class="two-col row-card">

      <div class="card equal-card">
        <div class="card-head">
          <div>
            <div class="card-title">
              推理失败任务
              <span v-if="failedTasks.length" class="badge-red">{{ failedTasks.length }}</span>
            </div>
            <div class="card-sub">近 7 天</div>
          </div>
          <span class="weak-link" @click="router.push('/tasks?status=failed')">查看全部</span>
        </div>
        <div class="card-body">
          <div v-if="failedTasks.length === 0" class="empty-tip">近 7 天无失败任务</div>
          <div v-for="t in failedTasks" :key="t.task_id" class="item-row"
               @click="router.push('/tasks/' + t.task_id)" style="cursor:pointer">
            <div class="avatar red">{{ (t.patient_name || '?')[0] }}</div>
            <div class="item-info">
              <div class="item-name">{{ t.patient_name || '未知' }}</div>
              <div class="item-sub">{{ t.chief_complaint || '—' }}</div>
            </div>
            <div class="item-time">{{ shortTime(t.created_at) }}</div>
          </div>
        </div>
      </div>

      <div class="card equal-card" :class="highRiskTasks.length ? 'card-risk' : ''">
        <div class="card-head">
          <div>
            <div class="card-title">
              高危风险病例
              <span v-if="highRiskTasks.length" class="badge-amber">{{ highRiskTasks.length }}</span>
            </div>
            <div class="card-sub">近 7 天 AI 判定 · 中高风险</div>
          </div>
          <span class="weak-link" @click="router.push('/tasks?risk=mid_and_above')">查看全部任务</span>
        </div>
        <div class="card-body">
          <div v-if="highRiskTasks.length === 0" class="empty-tip">近 7 天无中高危病例</div>
          <div v-for="t in highRiskTasks" :key="t.task_id" class="item-row"
               @click="router.push('/tasks/' + t.task_id)" style="cursor:pointer">
            <div class="avatar amber">{{ (t.patient_name || '?')[0] }}</div>
            <div class="item-info">
              <div class="item-name">{{ t.patient_name || '未知' }}</div>
              <div class="item-sub">{{ t.chief_complaint || '—' }}</div>
            </div>
            <a-tag
              :color="riskLevel(t).includes('高') || riskLevel(t).toLowerCase().includes('high') ? 'error' : 'warning'"
              style="margin:0;font-size:11px;flex-shrink:0">
              {{ riskLevel(t) }}
            </a-tag>
          </div>
        </div>
      </div>

    </div>

    <!-- 底部：平台能力摘要 -->
    <div class="card summary-bar">
      <div class="summary-title-col">
        <div class="summary-title">平台能力摘要</div>
      </div>

      <div class="summary-cols">

        <div class="summary-col">
          <div class="summary-col-head">数据接入</div>
          <div class="summary-row">
            <span :class="['dot', hisHealthy === false ? 'red-dot' : hisHealthy === true ? 'green-dot' : 'gray-dot']"></span>
            <span class="summary-item-label">HIS 内部数据库</span>
            <span :class="['summary-item-val', hisHealthy === false ? 'val-red' : hisHealthy === true ? 'val-green' : 'val-gray']">
              {{ hisHealthy === null ? '检测中' : hisHealthy ? '连通' : '断开' }}
            </span>
          </div>
          <div class="summary-row">
            <span class="dot gray-dot"></span>
            <span class="summary-item-label">FHIR Mock Server</span>
            <span class="summary-item-val val-gray">未启用</span>
          </div>
        </div>

        <div class="summary-sep"></div>

        <div class="summary-col">
          <div class="summary-col-head">AI 推理域</div>
          <div class="summary-row">
            <span :class="['dot', aiHealthy === false ? 'red-dot' : aiHealthy === true ? 'green-dot' : 'gray-dot']"></span>
            <span class="summary-item-label">推理服务</span>
            <span :class="['summary-item-val', aiHealthy === false ? 'val-red' : aiHealthy === true ? 'val-green' : 'val-gray']">
              {{ aiHealthy === null ? '检测中' : aiHealthy ? '正常' : '异常' }}
            </span>
          </div>
          <div class="summary-row">
            <span :class="['dot', aiHealthy === false ? 'red-dot' : aiHealthy === true ? 'green-dot' : 'gray-dot']"></span>
            <span class="summary-item-label">FastAPI 后端</span>
            <span :class="['summary-item-val', aiHealthy === false ? 'val-red' : aiHealthy === true ? 'val-green' : 'val-gray']">
              {{ aiHealthy === null ? '检测中' : aiHealthy ? '在线' : '离线' }}
            </span>
          </div>
        </div>

        <div class="summary-sep"></div>

        <div class="summary-col">
          <div class="summary-col-head">系统信息</div>
          <div class="summary-info-line">AI 响应耗时 {{ aiResponseMs !== null ? aiResponseMs + ' ms' : '—' }}</div>
          <div class="summary-info-line">{{ serviceAlerts.length ? serviceAlerts.length + ' 个服务告警' : '无告警' }}</div>
        </div>

      </div>

      <div class="summary-sync">最近同步：{{ syncTime || '—' }}</div>
      <span class="detail-link" @click="router.push('/integration?tab=status')">查看完整系统状态</span>
    </div>

  </div>
</template>

<style scoped>
.page {
  padding: 24px 28px 20px;
  background: #f5f7fa;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
}

/* 标题区 */
.page-header { flex-shrink: 0; }
.section-title { font-size: 20px; font-weight: 700; color: #1e293b; border-left: 3px solid #14B8A6; padding-left: 12px; }
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 5px; padding-left: 15px; }

/* 搜索条 */
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07);
  padding: 10px 16px;
}
.search-input { flex: 1; }
.search-btn { flex-shrink: 0; }
.search-btn-weak { flex-shrink: 0; color: #64748b; border-color: #e2e8f0; }
.search-btn-weak:hover { color: #334155; border-color: #cbd5e1; }

/* 行布局 */
.row-card { flex: 1; min-height: 0; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }

/* 卡片基础 */
.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07);
  padding: 16px 18px;
}

/* 等高卡片：内部用flex纵向撑开 */
.equal-card {
  display: flex;
  flex-direction: column;
  min-height: 170px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.card-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.card-sub { font-size: 11px; color: #94a3b8; margin-top: 3px; }

.card-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}

/* 第一行卡片内容区最高显示约4条，第二行约3条 */
.two-col .card-body   { max-height: 180px; }
.three-col .card-body { max-height: 160px; }

/* 细滚动条 */
.card-body::-webkit-scrollbar { width: 3px; }
.card-body::-webkit-scrollbar-track { background: transparent; }
.card-body::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 2px; }
.card-body::-webkit-scrollbar-thumb:hover { background: #cbd5e1; }

/* 弱链接统一 */
.weak-link { font-size: 11px; color: #94a3b8; cursor: pointer; white-space: nowrap; padding-top: 2px; }
.weak-link:hover { color: #64748b; }

/* 列表行 */
.item-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid #f1f5f9;
}
.item-row:last-child { border-bottom: none; padding-bottom: 0; }
.item-row:hover { background: #f8fafc; margin: 0 -4px; padding-left: 4px; padding-right: 4px; border-radius: 6px; }

.avatar {
  width: 30px; height: 30px; border-radius: 50%;
  font-size: 12px; font-weight: 600;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.blue   { background: #eff6ff; color: #2563EB; }
.purple { background: #f5f3ff; color: #7c3aed; }
.red    { background: #fef2f2; color: #dc2626; }
.amber  { background: #fffbeb; color: #d97706; }

.item-info { flex: 1; min-width: 0; }
.item-name { font-size: 13px; font-weight: 500; color: #1e293b; }
.item-sub  { font-size: 12px; color: #94a3b8; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-time { font-size: 11px; color: #94a3b8; flex-shrink: 0; }

.empty-tip { font-size: 13px; color: #94a3b8; padding: 16px 0; text-align: center; display: flex; align-items: center; justify-content: center; }

/* 服务状态正常展示（保留备用） */
.service-ok-tip { font-size: 12px; color: #10B981; font-weight: 500; margin-bottom: 10px; }
.service-ok-items { display: flex; flex-direction: column; gap: 8px; }
.service-ok-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.service-ok-label { color: #64748b; flex: 1; }
.service-ok-val { color: #475569; font-size: 12px; }

/* 底部平台能力摘要 */
.summary-bar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 12px 20px;
  flex-shrink: 0;
}
.summary-title-col { width: 120px; flex-shrink: 0; }
.summary-title { font-size: 13px; font-weight: 600; color: #1e293b; }
.summary-cols { display: flex; align-items: center; flex: 1; gap: 0; }
.summary-col { display: flex; flex-direction: column; gap: 5px; flex: 1; padding: 0 20px; }
.summary-col:first-child { padding-left: 0; }
.summary-col-head { font-size: 11px; color: #94a3b8; margin-bottom: 2px; }
.summary-row { display: flex; align-items: center; gap: 7px; font-size: 12px; }
.summary-item-label { color: #64748b; flex: 1; }
.summary-item-val { font-size: 12px; font-weight: 500; min-width: 36px; text-align: right; }
.val-green { color: #10B981; }
.val-red   { color: #dc2626; }
.val-gray  { color: #94a3b8; }
.summary-info-line { font-size: 12px; color: #64748b; line-height: 1.6; }
.summary-sep { width: 1px; height: 40px; background: #e8ecf2; flex-shrink: 0; margin: 0 4px; }
.summary-sync { font-size: 11px; color: #94a3b8; white-space: nowrap; margin-left: 16px; flex-shrink: 0; }
.detail-link { font-size: 11px; color: #14b8a6; cursor: pointer; white-space: nowrap; margin-left: 12px; flex-shrink: 0; }
.detail-link:hover { color: #0d9488; }
.card-risk { border: 1px solid #fef3c7; }

/* 徽章 */
.badge-red   { display: inline-block; background: #fef2f2; color: #dc2626; font-size: 11px; font-weight: 600; border-radius: 10px; padding: 0 7px; margin-left: 6px; line-height: 18px; }
.badge-amber { display: inline-block; background: #fffbeb; color: #d97706; font-size: 11px; font-weight: 600; border-radius: 10px; padding: 0 7px; margin-left: 6px; line-height: 18px; }

/* 告警行 */
.alert-row { display: flex; align-items: flex-start; gap: 10px; padding: 9px 0; border-bottom: 1px solid #f1f5f9; }
.alert-row:last-child { border-bottom: none; }

/* 圆点 */
.dot       { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.green-dot { background: #10B981; }
.red-dot   { background: #dc2626; }
.gray-dot  { background: #cbd5e1; }

/* 底部旧状态栏样式（已替换为 summary-bar） */
</style>
