<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const patients = ref([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const filterEmpi = ref('all')
const selected = ref(new Set())

onMounted(fetchPatients)

async function fetchPatients() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/admin/patients', { credentials: 'include' })
    if (!res.ok) throw new Error('请求失败')
    patients.value = await res.json()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const GENDER_MAP = { 1: '男', 2: '女' }

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return patients.value.filter(p => {
    if (filterEmpi.value === 'mapped' && !p.empi_id) return false
    if (filterEmpi.value === 'unmapped' && p.empi_id) return false
    if (!q) return true
    return (
      p.name?.toLowerCase().includes(q) ||
      String(p.id).includes(q) ||
      (p.birth_date && p.birth_date.slice(0, 10).includes(q))
    )
  })
})

const allSelected = computed(() =>
  filtered.value.length > 0 && filtered.value.every(p => selected.value.has(p.id))
)

function toggleAll() {
  if (allSelected.value) {
    filtered.value.forEach(p => selected.value.delete(p.id))
  } else {
    filtered.value.forEach(p => selected.value.add(p.id))
  }
  selected.value = new Set(selected.value)
}

function toggleRow(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}

function goTasks(patientId) {
  router.push({ path: '/admin/tasks', query: { patient_id: patientId } })
}

function goEmpi(patientId) {
  router.push({ path: '/admin/integration', query: { patient_id: patientId } })
}

function goEmpiSource(patientId, source) {
  router.push({ path: '/admin/integration', query: { patient_id: patientId, source } })
}

function batchGoEmpi() {
  const ids = [...selected.value].join(',')
  router.push({ path: '/admin/integration', query: { patient_ids: ids } })
}

const unmappedCount = computed(() => patients.value.filter(p => !p.empi_id).length)
</script>

<template>
  <div class="patient-admin">

    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <h2>患者管理</h2>
        <span class="header-note">仅展示基本信息与数据集成状态，临床数据由医生访问</span>
      </div>
      <div v-if="unmappedCount > 0" class="alert-pill">
        <span class="alert-dot"></span>
        {{ unmappedCount }} 个患者未归一
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="search-wrap">
          <svg class="search-icon" viewBox="0 0 20 20" fill="none">
            <circle cx="8.5" cy="8.5" r="5" stroke="#94a3b8" stroke-width="1.5"/>
            <path d="M13 13l3.5 3.5" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <input v-model="search" class="search-input" placeholder="搜索姓名、ID、出生日期..." />
        </div>
        <div class="filter-tabs">
          <button :class="['filter-tab', filterEmpi === 'all' && 'active']" @click="filterEmpi = 'all'">
            全部 <span class="tab-count">{{ patients.length }}</span>
          </button>
          <button :class="['filter-tab', filterEmpi === 'unmapped' && 'active', 'warn']" @click="filterEmpi = filterEmpi === 'unmapped' ? 'all' : 'unmapped'">
            未归一 <span class="tab-count warn">{{ unmappedCount }}</span>
          </button>
          <button :class="['filter-tab', filterEmpi === 'mapped' && 'active']" @click="filterEmpi = filterEmpi === 'mapped' ? 'all' : 'mapped'">
            已归一 <span class="tab-count">{{ patients.length - unmappedCount }}</span>
          </button>
        </div>
      </div>
      <div class="toolbar-right">
        <button
          v-if="selected.size > 0"
          class="batch-btn"
          @click="batchGoEmpi"
        >
          批量 EMPI 治理 ({{ selected.size }})
        </button>
        <span class="result-count">{{ filtered.length }} 条结果</span>
      </div>
    </div>

    <!-- 状态 -->
    <div v-if="loading" class="state-msg">
      <div class="spinner"></div>
      加载中...
    </div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <!-- 表格 -->
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-check">
              <input type="checkbox" :checked="allSelected" @change="toggleAll" />
            </th>
            <th class="col-id">ID</th>
            <th class="col-name">姓名</th>
            <th class="col-info">性别 / 出生日期</th>
            <th class="col-empi">EMPI 归一</th>
            <th class="col-sources">数据集成</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in filtered"
            :key="p.id"
            :class="{ 'row-selected': selected.has(p.id) }"
          >
            <td class="col-check">
              <input type="checkbox" :checked="selected.has(p.id)" @change="toggleRow(p.id)" />
            </td>
            <td class="mono text-muted">{{ p.id }}</td>
            <td class="col-name-cell"><strong>{{ p.name }}</strong></td>
            <td class="text-muted">
              {{ GENDER_MAP[p.gender] || '—' }} / {{ p.birth_date ? p.birth_date.slice(0, 10) : '—' }}
            </td>
            <td>
              <span
                v-if="p.empi_id"
                class="empi-badge mapped"
                title="该患者已关联外部系统ID，EMPI 映射完整"
              >
                ✓ 已归一
              </span>
              <span
                v-else
                class="empi-badge unmapped"
                title="该患者未关联外部系统ID，需在 EMPI 治理中手动配置映射"
              >
                ✗ 未归一
              </span>
            </td>
            <td>
              <div class="source-chips">
                <button
                  v-if="p.has_his"
                  class="source-chip his"
                  title="点击进入 HIS 映射治理"
                  @click="goEmpiSource(p.id, 'his')"
                >
                  🏥 HIS
                </button>
                <button
                  v-if="p.has_lis"
                  class="source-chip lis"
                  title="点击进入 LIS 映射治理"
                  @click="goEmpiSource(p.id, 'lis')"
                >
                  🧪 LIS
                </button>
                <button
                  v-if="p.has_pacs"
                  class="source-chip pacs"
                  title="点击进入 PACS 映射治理"
                  @click="goEmpiSource(p.id, 'pacs')"
                >
                  📸 PACS
                </button>
                <span v-if="!p.has_his && !p.has_lis && !p.has_pacs" class="no-source">暂无数据</span>
              </div>
            </td>
            <td>
              <div class="action-btns">
                <button class="action-btn" title="查看该患者的 AI 分析任务" @click="goTasks(p.id)">
                  <svg viewBox="0 0 16 16" fill="none"><circle cx="6.5" cy="6.5" r="4" stroke="currentColor" stroke-width="1.3"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
                  查看任务
                </button>
                <button class="action-btn empi-btn" title="管理该患者的 EMPI 跨系统映射关系" @click="goEmpi(p.id)">
                  <svg viewBox="0 0 16 16" fill="none"><path d="M8 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM3 14s-1 0-1-1 1-4 6-4 6 3 6 4-1 1-1 1H3z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M12 7l2 2-2 2M14 9H10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  EMPI 治理
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="filtered.length === 0">
            <td colspan="7" class="empty-row">无匹配患者</td>
          </tr>
        </tbody>
      </table>
    </div>

  </div>
</template>

<style scoped>
.patient-admin { padding: 24px; min-height: 100%; box-sizing: border-box; }

/* 页头 */
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 20px;
}
.header-left { display: flex; flex-direction: column; gap: 4px; }
.page-header h2 { margin: 0; font-size: 18px; font-weight: 700; color: #1e293b; }
.header-note { font-size: 12px; color: #94a3b8; }
.alert-pill {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px;
  background: #fff7ed; border: 1px solid #fed7aa;
  font-size: 12px; color: #c2410c; white-space: nowrap;
}
.alert-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #f97316;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .4; }
}

/* 工具栏 */
.toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.toolbar-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.toolbar-right { display: flex; align-items: center; gap: 10px; }

.search-wrap {
  position: relative; display: flex; align-items: center;
}
.search-icon {
  position: absolute; left: 10px; width: 15px; height: 15px; pointer-events: none;
}
.search-input {
  width: 260px; padding: 7px 12px 7px 32px;
  border: 1px solid #e2e8f0; border-radius: 6px;
  font-size: 13px; outline: none; background: #fff;
  transition: border-color .15s;
}
.search-input:focus { border-color: #93c5fd; }

.filter-tabs { display: flex; gap: 2px; background: #f1f5f9; border-radius: 7px; padding: 3px; }
.filter-tab {
  padding: 4px 12px; border-radius: 5px; border: none;
  font-size: 12px; color: #64748b; cursor: pointer; background: none;
  transition: all .15s;
}
.filter-tab:hover { background: #e2e8f0; }
.filter-tab.active { background: #fff; color: #1e293b; font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.filter-tab.warn.active { color: #c2410c; }
.tab-count {
  display: inline-block; margin-left: 4px; padding: 0 5px;
  border-radius: 8px; background: #e2e8f0; font-size: 10px; color: #475569;
}
.tab-count.warn { background: #fee2e2; color: #b91c1c; }

.batch-btn {
  padding: 6px 14px; border-radius: 6px; border: 1px solid #bfdbfe;
  background: #eff6ff; color: #1d4ed8; font-size: 12px;
  cursor: pointer; font-weight: 500; transition: all .15s;
}
.batch-btn:hover { background: #dbeafe; }

.result-count { font-size: 12px; color: #94a3b8; }

/* 状态 */
.state-msg {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 48px; color: #94a3b8; font-size: 14px;
}
.state-msg.error { color: #ef4444; }
.spinner {
  width: 16px; height: 16px; border-radius: 50%;
  border: 2px solid #e2e8f0; border-top-color: #3b82f6;
  animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* 表格 */
.table-wrap {
  background: #fff; border-radius: 10px; overflow: hidden;
  border: 1px solid #e8ecf2; box-shadow: 0 1px 4px rgba(0,0,0,.05);
}
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
.data-table th {
  background: #f8fafc; color: #64748b; font-weight: 600;
  padding: 11px 14px; text-align: left; border-bottom: 1px solid #e8ecf2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.data-table td {
  padding: 10px 14px; border-bottom: 1px solid #f1f5f9;
  color: #334155; vertical-align: middle;
  overflow: hidden; text-overflow: ellipsis;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover td { background: #f8fafc; }
.data-table tbody tr.row-selected td { background: #eff6ff; }

.col-check   { width: 40px; }
.col-id      { width: 60px; }
.col-name    { width: 110px; }
.col-info    { width: 148px; white-space: nowrap; }
.col-empi    { width: 96px; }
.col-sources { width: 190px; }
.col-actions { width: 188px; }

.col-name-cell strong { font-weight: 600; color: #1e293b; }
.mono { font-family: monospace; font-size: 12px; }
.text-muted { color: #64748b; }

/* EMPI 徽章 */
.empi-badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 600; cursor: default;
  transition: opacity .15s;
}
.empi-badge:hover { opacity: .85; }
.empi-badge.mapped   { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
.empi-badge.unmapped { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }

/* 数据源芯片 */
.source-chips { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }
.source-chip {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 7px; border-radius: 5px; border: 1px solid transparent;
  font-size: 11px; font-weight: 500; cursor: pointer;
  transition: all .15s;
}
.source-chip.his  { background: #f0fdf4; color: #166534; border-color: #bbf7d0; }
.source-chip.lis  { background: #fff7ed; color: #9a3412; border-color: #fed7aa; }
.source-chip.pacs { background: #eff6ff; color: #1e40af; border-color: #bfdbfe; }
.source-chip:hover { filter: brightness(.94); transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,.1); }
.no-source { font-size: 12px; color: #cbd5e1; }

/* 操作按钮 */
.action-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.action-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 9px; border-radius: 5px; border: 1px solid #e2e8f0;
  background: #f8fafc; color: #475569; font-size: 12px;
  cursor: pointer; transition: all .15s; white-space: nowrap;
}
.action-btn svg { width: 13px; height: 13px; flex-shrink: 0; }
.action-btn:hover { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.action-btn.empi-btn:hover { background: #f0fdf4; border-color: #86efac; color: #166534; }

.empty-row { text-align: center; color: #94a3b8; padding: 40px; font-size: 13px; }
</style>
