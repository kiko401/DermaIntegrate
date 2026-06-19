<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter, useRoute } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const route = useRoute()

const patients = ref([])
const loadingPatients = ref(false)
const searchQuery = ref('')

const filteredPatients = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return patients.value
  return patients.value.filter(p =>
    p.name?.toLowerCase().includes(q) ||
    p.phone?.includes(q) ||
    p.id_card?.includes(q) ||
    p.empi_id?.toLowerCase().includes(q) ||
    String(p.id).includes(q)
  )
})

async function fetchPatients() {
  loadingPatients.value = true
  try {
    const res = await apiFetch('/api/patients')
    patients.value = await res.json()
  } catch {
    message.error('加载患者列表失败')
  } finally {
    loadingPatients.value = false
  }
}

function resetFilters() {
  searchQuery.value = ''
}

const patientColumns = [
  { title: '内部 ID', key: 'id', width: 90 },
  { title: '患者', key: 'name', width: 150 },
  { title: '性别 / 年龄', key: 'demog', width: 100 },
  { title: 'EMPI 映射状态', key: 'empi_status', width: 220 },
  { title: '操作', key: 'action', width: 90, align: 'center' },
]

function genderLabel(g) {
  if (g === 1 || g === '1' || g === '男') return '男'
  if (g === 2 || g === '2' || g === '女') return '女'
  return '-'
}

function calcAge(birthDate) {
  if (!birthDate) return null
  const birth = new Date(birthDate)
  const now = new Date()
  const age = now.getFullYear() - birth.getFullYear()
  return age > 0 ? age : null
}

onMounted(async () => {
  await fetchPatients()
  const q = route.query.q
  if (q) searchQuery.value = q
})
</script>

<template>
  <div class="page">

    <div class="page-header">
      <div class="page-title">患者管理</div>
      <div class="page-sub">检索患者 · 点击查看档案</div>
    </div>

    <div class="search-bar-card">
      <div class="search-main">
        <a-input
          v-model:value="searchQuery"
          placeholder="姓名 / 内部ID / 外部系统ID"
          allow-clear
          size="large"
          class="search-input"
        >
          <template #prefix>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="color:#94a3b8"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </template>
        </a-input>
      </div>
      <a-button size="small" @click="resetFilters" style="color:#64748b">重置</a-button>
    </div>

    <div class="card table-card">
      <div class="card-head">
        <div class="card-title">患者列表</div>
        <span class="card-sub">{{ filteredPatients.length }} 位患者</span>
      </div>
      <a-table
        :columns="patientColumns"
        :data-source="filteredPatients"
        :loading="loadingPatients"
        row-key="id"
        size="middle"
        :pagination="{ pageSize: 10, showSizeChanger: false, size: 'small' }"
        :custom-row="record => ({ onClick: () => router.push('/clinical/' + record.id) })"
        :locale="{ emptyText: searchQuery ? '无匹配患者' : '暂无患者数据' }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'id'">
            <span class="id-text" style="font-family:monospace">{{ record.id }}</span>
          </template>
          <template v-else-if="column.key === 'name'">
            <div class="patient-name-cell">
              <div class="p-avatar">{{ record.name?.[0] || '?' }}</div>
              <div class="p-name">{{ record.name }}</div>
            </div>
          </template>
          <template v-else-if="column.key === 'demog'">
            <span class="demog-text">
              {{ genderLabel(record.gender) }}
              <template v-if="calcAge(record.birth_date)"> · {{ calcAge(record.birth_date) }} 岁</template>
            </span>
          </template>
          <template v-else-if="column.key === 'empi_status'">
            <div class="empi-cell">
              <div>
                <span v-if="record.empi_id" class="empi-tag">{{ record.empi_id }}</span>
                <span v-else class="empi-none">未归一</span>
              </div>
              <a-space :size="4" wrap style="margin-top:4px">
                <a-tag v-if="record.has_his" color="green" class="data-tag">HIS</a-tag>
                <a-tag v-if="record.has_lis" color="gold" class="data-tag">病理</a-tag>
                <a-tag v-if="record.has_pacs" color="blue" class="data-tag">影像</a-tag>
                <span v-if="!record.has_his && !record.has_lis && !record.has_pacs" class="no-data">—</span>
              </a-space>
            </div>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="primary" size="small" ghost @click.stop="router.push('/clinical/' + record.id)">
              查看档案
            </a-button>
          </template>
        </template>
      </a-table>
    </div>

  </div>
</template>

<style scoped>
.page {
  padding: 26px 32px 40px;
  background: #f5f7fa;
  min-height: 100%;
}

.page-header { margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 700; color: #1e293b; border-left: 3px solid #14B8A6; padding-left: 12px; line-height: 1.3; }
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 5px; padding-left: 15px; }

.search-bar-card {
  background: #fff;
  border-radius: 12px;
  padding: 14px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}
.search-main { flex: 1; min-width: 200px; max-width: 500px; }
.search-input { width: 100%; }

.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  padding: 18px 20px;
  margin-bottom: 14px;
}

.table-card { padding: 16px 16px 10px; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.card-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.card-sub { font-size: 11px; color: #94a3b8; }

:deep(.ant-table-row) { cursor: pointer; }
:deep(.ant-table-row:hover td) { background: #f8fafc !important; }

.patient-name-cell { display: flex; align-items: center; gap: 9px; }
.p-avatar { width: 30px; height: 30px; border-radius: 50%; background: #e2e8f0; color: #475569; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.p-name { font-size: 13px; font-weight: 600; color: #1e293b; line-height: 1.3; }
.demog-text { font-size: 12px; color: #64748b; }
.empi-cell { display: flex; flex-direction: column; gap: 2px; }
.empi-tag { font-size: 11px; color: #059669; font-weight: 600; font-family: monospace; }
.empi-none { font-size: 11px; color: #cbd5e1; }
.id-text { font-size: 11px; color: #94a3b8; }
.data-tag { margin: 0; font-size: 11px; }
.no-data { font-size: 11px; color: #cbd5e1; }
</style>
