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
  min-height: 100%;
  background:
      radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
      radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
      linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}

.page-header {
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 800;
  color: #16324f;
  border-left: 3px solid #19c6d0;
  padding-left: 12px;
  line-height: 1.3;
}

.page-sub {
  font-size: 12px;
  color: #7d94ad;
  margin-top: 6px;
  padding-left: 15px;
}

.search-bar-card {
  background: rgba(255, 255, 255, 0.76);
  border-radius: 18px;
  padding: 14px 20px;
  margin-bottom: 14px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 14px 30px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.search-main {
  flex: 1;
  min-width: 200px;
  max-width: none;
}

.search-input {
  width: 100%;
}

.reset-btn {
  color: #52708e !important;
  border: 1px solid rgba(92,128,170,0.18) !important;
  background: rgba(255,255,255,0.78) !important;
  border-radius: 12px !important;
  box-shadow: 0 8px 20px rgba(100,130,168,0.08);
}

.card {
  background: rgba(255, 255, 255, 0.78);
  border-radius: 20px;
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
  padding: 18px 20px;
  margin-bottom: 14px;
}

.table-card {
  padding: 16px 16px 10px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}

.card-title {
  font-size: 15px;
  font-weight: 800;
  color: #18395e;
}

.card-sub {
  font-size: 12px;
  color: #7f97b1;
}

:deep(.ant-table) {
  background: transparent;
}

:deep(.ant-table-container) {
  border-radius: 16px;
  overflow: hidden;
}

:deep(.ant-table-thead > tr > th) {
  background: rgba(244, 249, 255, 0.92) !important;
  color: #5c7692 !important;
  font-size: 12px;
  font-weight: 800;
  border-bottom: 1px solid rgba(116,152,193,0.12) !important;
}

:deep(.ant-table-tbody > tr > td) {
  background: rgba(255,255,255,0.38);
  border-bottom: 1px solid rgba(116,152,193,0.08) !important;
  transition: background 0.22s ease;
}

:deep(.ant-table-row) {
  cursor: pointer;
}

:deep(.ant-table-row:hover td) {
  background: rgba(237,245,255,0.88) !important;
}

:deep(.ant-table-placeholder .ant-table-cell) {
  background: transparent !important;
}

:deep(.ant-pagination .ant-pagination-item) {
  border-radius: 10px;
  border-color: rgba(116,152,193,0.14);
}

:deep(.ant-pagination .ant-pagination-item-active) {
  border-color: #2f6fed;
}

:deep(.ant-pagination .ant-pagination-item-active a) {
  color: #2f6fed;
}

:deep(.ant-input-affix-wrapper) {
  height: 35px;
  border-radius: 14px !important;
  border: 1px solid rgba(116,152,193,0.14) !important;
  background: rgba(248,251,255,0.78) !important;
  box-shadow: none !important;
  padding: 0 14px !important;
}

:deep(.ant-input-affix-wrapper:hover) {
  border-color: rgba(48,112,238,0.22) !important;
}

:deep(.ant-input-affix-wrapper-focused) {
  background: rgba(255,255,255,0.92) !important;
  border-color: rgba(48,112,238,0.24) !important;
  box-shadow: 0 0 0 4px rgba(48,112,238,0.08) !important;
}

:deep(.ant-input) {
  color: #1b3b60 !important;
  background: transparent !important;
  font-size: 14px;
  line-height: 1;
}

:deep(.ant-input::placeholder) {
  color: #9bb0c6;
}

.patient-name-cell {
  display: flex;
  align-items: center;
  gap: 9px;
}

.p-avatar {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2f6fed 0%, #19c6d0 100%);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 10px 22px rgba(47,111,237,0.16);
}

.p-name {
  font-size: 13px;
  font-weight: 700;
  color: #18395e;
  line-height: 1.3;
}

.demog-text {
  font-size: 12px;
  color: #5f7894;
  font-weight: 500;
}

.empi-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.empi-tag {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(25,198,208,0.10);
  color: #0f766e;
  font-weight: 700;
  font-family: monospace;
  font-size: 11px;
}

.empi-none {
  font-size: 11px;
  color: #a3b3c3;
}

.id-text {
  font-size: 11px;
  color: #6f87a1;
}

.data-tag {
  margin: 0;
  font-size: 11px;
  border-radius: 999px;
}

.no-data {
  font-size: 11px;
  color: #b6c2cf;
}

.action-btn {
  border-radius: 12px !important;
  border-color: rgba(47,111,237,0.36) !important;
  color: #2f6fed !important;
  background: rgba(47,111,237,0.04) !important;
  font-weight: 700;
}

.action-btn:hover {
  color: #19c6d0 !important;
  border-color: rgba(25,198,208,0.4) !important;
  background: rgba(25,198,208,0.06) !important;
}
</style>

