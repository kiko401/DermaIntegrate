<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFetch } from '../utils/api.js'
import { useRouter } from 'vue-router'
import {
  UserOutlined, ClockCircleOutlined, CheckCircleOutlined, ApiOutlined,
} from '@ant-design/icons-vue'

const router = useRouter()
const totalPatients = ref('—')
const tasks = ref([])

function formatDate(val) {
  if (!val) return '—'
  if (val instanceof Date) return val.toISOString().slice(0, 10)
  return String(val).slice(0, 10)
}

function timeAgo(val) {
  if (!val) return '—'
  const diff = Date.now() - new Date(val).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} 小时前`
  return `${Math.floor(hrs / 24)} 天前`
}

const recentVisits = computed(() =>
  tasks.value.slice(0, 4).map(t => ({
    name: t.patient_name || '未知',
    complaint: t.chief_complaint || '—',
    date: formatDate(t.visit_date),
    tag: '',
    analyzed: t.status === 'complete',
  }))
)

const recentTasks = computed(() =>
  tasks.value.slice(0, 3).map(t => ({
    name: t.patient_name || '未知',
    complaint: t.chief_complaint || '—',
    result: t.status,
    time: timeAgo(t.created_at),
  }))
)

const pendingCount = computed(() => tasks.value.filter(t => t.status === 'pending').length)
const completeCount = computed(() => tasks.value.filter(t => t.status === 'complete').length)
const todayCount = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return tasks.value.filter(t => formatDate(t.created_at) === today).length
})

onMounted(async () => {
  try {
    const [pRes, tRes] = await Promise.all([
      apiFetch('/api/patients'),
      apiFetch('/api/tasks'),
    ])
    const [patients, taskData] = await Promise.all([pRes.json(), tRes.json()])
    if (Array.isArray(patients)) totalPatients.value = patients.length
    if (Array.isArray(taskData)) tasks.value = taskData
  } catch {}
})

const doctorName = computed(() => {
  try { return JSON.parse(localStorage.getItem('doctor_info') || '{}').name || 'doctor' } catch { return 'doctor' }
})

const taskColor = (r) => r === 'complete' ? 'blue' : r === 'error' ? 'red' : 'orange'
const taskLabel = (r) => r === 'complete' ? '完成' : r === 'error' ? '失败' : '分析中'
</script>

<template>
  <div class="page">

    <!-- Header -->
    <div class="page-header">
      <div>
        <div class="section-title">工作台</div>
        <div class="page-sub">皮肤病辅助诊断 · AI 多模态推理 · 多源数据集成</div>
      </div>
    </div>

    <!-- Stat cards -->
    <div class="stat-row">
      <div class="card stat-card">
        <div class="stat-icon-wrap" style="background:#eff6ff">
          <UserOutlined style="color:#2563EB;font-size:20px" />
        </div>
        <div class="stat-body">
          <div class="stat-num" style="color:#2563EB">{{ totalPatients }}</div>
          <div class="stat-label">患者总数</div>
          <div class="stat-hint">已建档患者</div>
        </div>
      </div>
      <div class="card stat-card">
        <div class="stat-icon-wrap" style="background:#fffbeb">
          <ClockCircleOutlined style="color:#D97706;font-size:20px" />
        </div>
        <div class="stat-body">
          <div class="stat-num" style="color:#D97706">{{ pendingCount }}</div>
          <div class="stat-label">待分析任务</div>
          <div class="stat-hint">等待 AI 推理</div>
        </div>
      </div>
      <div class="card stat-card">
        <div class="stat-icon-wrap" style="background:#ecfdf5">
          <CheckCircleOutlined style="color:#059669;font-size:20px" />
        </div>
        <div class="stat-body">
          <div class="stat-num" style="color:#059669">{{ completeCount }}</div>
          <div class="stat-label">已完成分析</div>
          <div class="stat-hint">本周累计</div>
        </div>
      </div>
      <div class="card stat-card">
        <div class="stat-icon-wrap" style="background:#ecfdf5">
          <ApiOutlined style="color:#059669;font-size:20px" />
        </div>
        <div class="stat-body">
          <div class="stat-num" style="font-size:22px;color:#059669">正常运行</div>
          <div class="stat-label">AI 推理服务</div>
          <div class="stat-hint">多模态推理域在线</div>
        </div>
      </div>
    </div>

    <!-- Main 2:1 layout -->
    <div class="main-row">

      <!-- Left: Recent visits (larger) -->
      <div class="card main-left">
        <div class="card-head">
          <div>
            <div class="card-title">最近就诊</div>
            <div class="card-sub">待处理 · 最新录入</div>
          </div>
          <span class="card-link" @click="router.push('/patients')">进入患者管理 →</span>
        </div>
        <div v-for="v in recentVisits" :key="v.name" class="visit-row">
          <div class="v-avatar">{{ v.name[0] }}</div>
          <div class="v-info">
            <div class="v-name-row">
              <span class="row-name">{{ v.name }}</span>
              <a-tag v-if="v.tag" color="purple" style="margin:0 0 0 6px;font-size:11px">{{ v.tag }}</a-tag>
            </div>
            <div class="v-complaint">{{ v.complaint }}</div>
          </div>
          <div class="v-right">
            <a-tag :color="v.analyzed ? 'cyan' : 'default'" style="margin:0;font-size:12px">
              {{ v.analyzed ? '已分析' : '未分析' }}
            </a-tag>
            <div class="row-date" style="margin-top:4px">{{ v.date }}</div>
          </div>
        </div>
      </div>

      <!-- Right: AI tasks + quick status -->
      <div class="right-col">
        <div class="card" style="flex:1">
          <div class="card-head">
            <div>
              <div class="card-title">AI 分析动态</div>
              <div class="card-sub">最近推理任务</div>
            </div>
            <span class="card-link" @click="router.push('/tasks')">全部记录 →</span>
          </div>
          <div v-for="t in recentTasks" :key="t.name" class="task-row">
            <div class="t-avatar">{{ t.name[0] }}</div>
            <div class="t-info">
              <div class="row-name">{{ t.name }}</div>
              <div class="t-complaint">{{ t.complaint }}</div>
            </div>
            <div class="t-right">
              <a-tag :color="taskColor(t.result)" style="margin:0;font-size:12px">{{ taskLabel(t.result) }}</a-tag>
              <div class="row-date" style="margin-top:4px">{{ t.time }}</div>
            </div>
          </div>
        </div>

        <div class="card doctor-card">
          <div class="card-title" style="margin-bottom:12px">当前工作站</div>
          <div class="dc-row">
            <span class="dc-label">接诊医生</span>
            <span class="dc-val">{{ doctorName }}</span>
          </div>
          <div class="dc-row">
            <span class="dc-label">今日接诊</span>
            <span class="dc-val">{{ todayCount }} 人</span>
          </div>
          <div class="dc-row">
            <span class="dc-label">系统状态</span>
            <span class="dc-val" style="color:#059669">● 正常</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Platform summary -->
    <div class="card platform-card">
      <div class="card-head" style="margin-bottom:14px">
        <span class="card-title">平台能力摘要</span>
        <span class="row-date">最近同步：06-14 03:40</span>
      </div>
      <div class="platform-grid">
        <div class="ps-item">
          <div class="ps-label">数据接入</div>
          <div class="ps-rows">
            <div class="ps-row"><span class="pdot" style="background:#10B981"></span>HIS 内部数据库<span class="ps-val green">连通</span></div>
            <div class="ps-row"><span class="pdot" style="background:#cbd5e1"></span>FHIR Mock Server<span class="ps-val muted">未启用</span></div>
          </div>
        </div>
        <div class="ps-sep"></div>
        <div class="ps-item">
          <div class="ps-label">AI 推理域</div>
          <div class="ps-rows">
            <div class="ps-row"><span class="pdot" style="background:#2563EB"></span>推理服务<span class="ps-val blue">正常</span></div>
            <div class="ps-row"><span class="pdot" style="background:#10B981"></span>FastAPI 后端<span class="ps-val green">在线</span></div>
          </div>
        </div>
        <div class="ps-sep"></div>
        <div class="ps-item">
          <div class="ps-label">系统信息</div>
          <div class="ps-rows">
            <div class="ps-row" style="color:#64748b;font-size:12px">平均推理耗时 ~45 秒</div>
            <div class="ps-row" style="color:#64748b;font-size:12px">今日登录 03:41 · 无告警</div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.page { padding: 28px 32px; background: #f5f7fa; min-height: 100%; }

.page-header { margin-bottom: 22px; }
.section-title {
  font-size: 20px; font-weight: 700; color: #1e293b;
  border-left: 3px solid #14B8A6; padding-left: 12px; line-height: 1.3;
}
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 5px; padding-left: 15px; }

.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  padding: 20px 22px;
}

/* Stat row */
.stat-row { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 16px; }
.stat-card { display: flex; align-items: flex-start; gap: 16px; padding: 22px; }
.stat-icon-wrap {
  width: 48px; height: 48px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.stat-body { flex: 1; }
.stat-num { font-size: 34px; font-weight: 800; line-height: 1.1; margin-bottom: 4px; }
.stat-label { font-size: 13px; color: #475569; font-weight: 500; }
.stat-hint { font-size: 11px; color: #94a3b8; margin-top: 3px; }

/* Main 2:1 row */
.main-row { display: grid; grid-template-columns: 1fr 380px; gap: 14px; margin-bottom: 16px; }
.main-left { }
.right-col { display: flex; flex-direction: column; gap: 14px; }

.card-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.card-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.card-sub { font-size: 11px; color: #94a3b8; margin-top: 3px; }
.card-link { font-size: 12px; color: #2563EB; cursor: pointer; white-space: nowrap; padding-top: 2px; }

/* Visit rows */
.visit-row { display: flex; align-items: flex-start; gap: 12px; padding: 12px 0; border-bottom: 1px solid #f1f5f9; }
.visit-row:last-child { border-bottom: none; padding-bottom: 0; }
.v-avatar {
  width: 36px; height: 36px; border-radius: 50%; background: #eff6ff; color: #2563EB;
  font-size: 14px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.v-info { flex: 1; min-width: 0; }
.v-name-row { display: flex; align-items: center; margin-bottom: 3px; }
.row-name { font-size: 14px; font-weight: 600; color: #1e293b; }
.v-complaint { font-size: 12px; color: #64748b; }
.v-right { text-align: right; flex-shrink: 0; }

/* Task rows */
.task-row { display: flex; align-items: flex-start; gap: 12px; padding: 11px 0; border-bottom: 1px solid #f1f5f9; }
.task-row:last-child { border-bottom: none; padding-bottom: 0; }
.t-avatar {
  width: 32px; height: 32px; border-radius: 50%; background: #f5f3ff; color: #7c3aed;
  font-size: 13px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.t-info { flex: 1; min-width: 0; }
.t-complaint { font-size: 12px; color: #94a3b8; margin-top: 2px; }
.t-right { text-align: right; flex-shrink: 0; }

/* Doctor card */
.doctor-card { padding: 18px 22px; }
.dc-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid #f8fafc; }
.dc-row:last-child { border-bottom: none; }
.dc-label { font-size: 12px; color: #94a3b8; }
.dc-val { font-size: 13px; font-weight: 500; color: #334155; }

.row-date { font-size: 11px; color: #94a3b8; }

/* Platform */
.platform-card { }
.platform-grid { display: grid; grid-template-columns: 1fr 1px 1fr 1px 1fr; gap: 0 28px; }
.ps-sep { background: #f1f5f9; }
.ps-item { }
.ps-label { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
.ps-rows { display: flex; flex-direction: column; gap: 7px; }
.ps-row { display: flex; align-items: center; gap: 7px; font-size: 13px; color: #475569; }
.pdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.ps-val { margin-left: auto; font-size: 13px; font-weight: 500; }
.green { color: #059669; }
.blue { color: #2563EB; }
.muted { color: #94a3b8; }
</style>
