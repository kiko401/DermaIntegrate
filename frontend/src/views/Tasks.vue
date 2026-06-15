<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router  = useRouter()
const tasks   = ref([])
const loading = ref(false)

const hasPending = computed(() => tasks.value.some(t => t.status === 'pending'))

let pollTimer = null

async function fetchTasks() {
  loading.value = true
  try {
    const res = await apiFetch('/api/tasks')
    if (res.ok) tasks.value = await res.json()
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

async function silentRefresh() {
  try {
    const res = await apiFetch('/api/tasks')
    if (res.ok) tasks.value = await res.json()
  } catch {}
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await silentRefresh()
    if (!hasPending.value) stopPolling()
  }, 5000)
}

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

const columns = [
  { title: 'Task ID', dataIndex: 'task_id', key: 'task_id', ellipsis: true, width: 240 },
  { title: '患者', key: 'patient', width: 90 },
  { title: '主诉', key: 'complaint' },
  { title: '状态', key: 'status', width: 90 },
  { title: '创建时间', key: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 90 },
]

onMounted(async () => {
  await fetchTasks()
  if (hasPending.value) startPolling()
})

onUnmounted(stopPolling)
</script>

<template>
  <div style="padding:28px 32px;background:#f5f7fa;min-height:100%">
    <div style="margin-bottom:20px">
      <div style="font-size:20px;font-weight:700;color:#1e293b;border-left:3px solid #14B8A6;padding-left:12px">
        AI 分析记录
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-top:5px;padding-left:15px">全部 AI 诊断任务汇总</div>
    </div>

    <div style="background:#fff;border-radius:12px;padding:20px 22px;box-shadow:0 1px 4px rgba(0,0,0,0.07)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <span style="font-size:14px;font-weight:600;color:#1e293b">任务列表</span>
        <a-button size="small" :loading="loading" @click="fetchTasks">刷新</a-button>
      </div>
      <a-table
        :columns="columns"
        :data-source="tasks"
        :loading="loading"
        row-key="id"
        :pagination="{ pageSize: 15, showSizeChanger: false }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'patient'">
            {{ record.patient_name || '—' }}
          </template>
          <template v-else-if="column.key === 'complaint'">
            {{ record.chief_complaint || '—' }}
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)" style="margin:0">
              {{ statusLabel(record.status) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ record.created_at ? String(record.created_at).replace('T', ' ').slice(0, 16) : '—' }}
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" size="small" @click="router.push('/tasks/' + record.task_id)">查看</a-button>
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>
