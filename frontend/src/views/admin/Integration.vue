<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { apiFetch } from '@/utils/api'

const route = useRoute()
const activeTab = ref('empi')

// ── EMPI 数据 ──────────────────────────────────────────────────
const sources = ref([])
const sourcesLoading = ref(false)
const mappingFilter = ref('ALL')
const dataLoadedAt = ref('')

function fmtTime(d) {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function fmtDate(val) {
  if (!val) return '—'
  const d = new Date(val)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function fetchSources() {
  sourcesLoading.value = true
  try {
    const res = await apiFetch('/api/empi/sources')
    if (res.ok) {
      sources.value = await res.json()
      dataLoadedAt.value = fmtTime(new Date())
    }
  } catch {
    sources.value = []
  } finally {
    sourcesLoading.value = false
  }
}

const totalMatched = computed(() => sources.value.filter(r => r.patient_id).length)
const sourceStats = computed(() => ({
  HIS:  sources.value.filter(r => r.source_system === 'HIS').length,
  LIS:  sources.value.filter(r => r.source_system === 'LIS').length,
  PACS: sources.value.filter(r => r.source_system === 'PACS').length,
}))

const searchText = ref('')
const patientIdFilter = ref('')
const editOpen = ref(false)
const editLoading = ref(false)
const editForm = ref({
  empi_id: null,
  source_system: '',
  source_id: '',
  name: '',
  patient_id: '',
})

// ── 扫描冲突 ───────────────────────────────────────────────────
const conflictIds = ref(new Set())
const scanLoading = ref(false)

async function scanConflicts() {
  scanLoading.value = true
  try {
    const res = await apiFetch('/api/empi/conflicts')
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || '扫描失败')
    conflictIds.value = new Set(data.conflict_empi_ids || [])
    if (conflictIds.value.size === 0) {
      message.success('未检测到冲突映射')
    } else {
      message.warning(`检测到 ${conflictIds.value.size} 条冲突映射，已高亮显示`)
    }
  } catch (e) {
    message.error(e.message || '扫描失败')
  } finally {
    scanLoading.value = false
  }
}

// ── 新增映射 ───────────────────────────────────────────────────
const addOpen = ref(false)
const addLoading = ref(false)
const addForm = ref({ source_system: 'HIS', source_id: '', patient_id: '' })

function openAdd() {
  addForm.value = { source_system: 'HIS', source_id: '', patient_id: '' }
  addOpen.value = true
}

async function submitAdd() {
  if (!addForm.value.source_id.trim()) {
    message.warning('请输入外部 ID')
    return
  }
  if (!addForm.value.patient_id) {
    message.warning('请输入内部患者 ID')
    return
  }
  addLoading.value = true
  try {
    const res = await apiFetch('/api/empi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_system: addForm.value.source_system,
        source_id: addForm.value.source_id.trim(),
        patient_id: Number(addForm.value.patient_id),
      }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      if (data.error === 'EMPI_DUPLICATE_KEY') return message.error('该外部 ID 映射已存在')
      if (data.error === 'PATIENT_NOT_FOUND')  return message.error('内部患者 ID 不存在')
      throw new Error(data.error || '新增失败')
    }
    message.success('映射已新增')
    addOpen.value = false
    await fetchSources()
  } catch (e) {
    message.error(e.message || '新增失败')
  } finally {
    addLoading.value = false
  }
}

function initFromQuery() {
  patientIdFilter.value = route.query.patient_id ? String(route.query.patient_id) : ''
  mappingFilter.value = route.query.source ? String(route.query.source).toUpperCase() : 'ALL'
}

function openEdit(record) {
  editForm.value = {
    empi_id: record.empi_id,
    source_system: record.source_system,
    source_id: record.source_id,
    name: record.name || '',
    patient_id: record.patient_id ? String(record.patient_id) : '',
  }
  editOpen.value = true
}

async function submitEdit() {
  if (!editForm.value.patient_id) {
    message.warning('请输入内部患者 ID')
    return
  }

  editLoading.value = true
  try {
    const res = await apiFetch(`/api/empi/${editForm.value.empi_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patient_id: Number(editForm.value.patient_id) }),
    })

    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      if (data.error === 'PATIENT_NOT_FOUND') {
        return message.error('内部患者 ID 不存在')
      }
      if (data.error === 'MAPPING_NOT_FOUND') {
        return message.error('映射记录不存在')
      }
      throw new Error(data.error || '修改失败')
    }

    message.success('映射已更新')
    editOpen.value = false
    await fetchSources()
  } catch (e) {
    message.error(e.message || '修改失败')
  } finally {
    editLoading.value = false
  }
}

async function deleteMapping(record) {
  try {
    const res = await apiFetch('/api/empi', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [record.empi_id] }),
    })

    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || '删除失败')

    message.success('映射已删除')
    await fetchSources()
  } catch (e) {
    message.error(e.message || '删除失败')
  }
}


const filteredSources = computed(() => {
  let list = sources.value
  if (patientIdFilter.value) {
    list = list.filter(r => String(r.patient_id || '') === patientIdFilter.value)
  }
  if (mappingFilter.value !== 'ALL') {
    list = list.filter(r => r.source_system === mappingFilter.value)
  }
  const q = searchText.value.trim().toLowerCase()
  if (!q) return list
  return list.filter(r =>
    (r.name        || '').toLowerCase().includes(q) ||
    (r.internal_name || '').toLowerCase().includes(q) ||
    (r.source_id   || '').toLowerCase().includes(q) ||
    (r.id_card     || '').toLowerCase().includes(q) ||
    (r.phone       || '').toLowerCase().includes(q) ||
    (r.patient_id  || '').toString().includes(q)
  )
})

// ── SSE 会话治理 ───────────────────────────────────────────────
const sessions = ref([])
const sessionsLoading = ref(false)
const sessionSelected = ref([])
const sessionReleasingLoading = ref(false)

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const res = await apiFetch('/api/admin/sessions')
    if (res.ok) sessions.value = await res.json()
  } catch {
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

function toggleSession(id) {
  const idx = sessionSelected.value.indexOf(id)
  if (idx >= 0) sessionSelected.value.splice(idx, 1)
  else sessionSelected.value.push(id)
}

function isOvertime(durationSeconds) {
  return typeof durationSeconds === 'number' && durationSeconds >= 3600
}

function fmtDuration(seconds) {
  if (typeof seconds !== 'number') return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return h > 0
    ? `${h}h ${String(m).padStart(2,'0')}m`
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}

function fmtDatetime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${fmtDate(d)} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

async function forceReleaseSessions() {
  if (!sessionSelected.value.length) return
  sessionReleasingLoading.value = true
  try {
    const res = await apiFetch('/api/admin/sessions', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_ids: sessionSelected.value }),
    })
    if (res.ok) {
      sessionSelected.value = []
      await fetchSessions()
    }
  } finally {
    sessionReleasingLoading.value = false
  }
}

onMounted(() => {
  fetchSources()
  fetchSessions()
})

watch(() => route.query, initFromQuery, { immediate: true })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">数据集成治理</div>
      <div class="page-sub">EMPI 映射治理 · SSE 会话治理</div>
    </div>

    <a-tabs v-model:activeKey="activeTab" class="main-tabs">

      <!-- Tab 1: EMPI 映射治理 -->
      <a-tab-pane key="empi" tab="EMPI 映射治理">
        <div class="toolbar">
          <div class="toolbar-left">
            <a-radio-group v-model:value="mappingFilter" size="small" button-style="solid">
              <a-radio-button value="ALL">全部（{{ sources.length }}）</a-radio-button>
              <a-radio-button value="HIS">HIS（{{ sourceStats.HIS }}）</a-radio-button>
              <a-radio-button value="LIS">LIS（{{ sourceStats.LIS }}）</a-radio-button>
              <a-radio-button value="PACS">PACS（{{ sourceStats.PACS }}）</a-radio-button>
            </a-radio-group>
            <a-input
              v-model:value="searchText"
              size="small"
              placeholder="搜姓名 / 外部ID / 身份证 / 手机"
              allow-clear
              style="width: 220px;"
            />
          </div>
          <div class="toolbar-right">
            <span class="stat-pill matched">已归一 {{ totalMatched }}</span>
            <span class="stat-pill unmatched">未归一 {{ sources.length - totalMatched }}</span>
            <a-button size="small" :loading="sourcesLoading" @click="fetchSources">重新拉取</a-button>
            <a-button size="small" :loading="scanLoading" @click="scanConflicts">扫描冲突</a-button>
            <a-button size="small" type="primary" @click="openAdd">新增映射</a-button>
            <span class="load-time">{{ dataLoadedAt ? '拉取于 ' + dataLoadedAt : '未拉取' }}</span>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>来源</th>
                <th>外部 ID</th>
                <th>姓名</th>
                <th>身份证</th>
                <th>手机</th>
                <th>内部患者 ID</th>
                <th>内部姓名</th>
                <th>更新时间</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="sourcesLoading">
                <td colspan="11" class="empty-cell"><a-spin size="small" /></td>
              </tr>
              <tr v-else-if="filteredSources.length === 0">
                <td colspan="11" class="empty-cell">暂无数据</td>
              </tr>
              <tr
                v-for="r in filteredSources"
                :key="r.source_system + r.source_id"
                :class="{ 'row-unmatched': !r.patient_id, 'row-conflict': conflictIds.has(r.empi_id) }"
              >
                <td class="mono text-dim">{{ r.empi_id || '—' }}</td>
                <td><span class="sys-badge" :class="r.source_system.toLowerCase()">{{ r.source_system }}</span></td>
                <td class="mono">{{ r.source_id }}</td>
                <td>{{ r.name }}</td>
                <td class="mono text-dim">{{ r.id_card ? r.id_card.slice(0, 6) + '****' + r.id_card.slice(-4) : '—' }}</td>
                <td class="text-dim">{{ r.phone || '—' }}</td>
                <td class="mono">{{ r.patient_id || '—' }}</td>
                <td>{{ r.internal_name || '—' }}</td>
                <td class="text-dim">{{ fmtDate(r.linked_at) }}</td>
                <td>
                  <span v-if="conflictIds.has(r.empi_id)" class="match-conflict">冲突</span>
                  <span v-else-if="r.patient_id" class="match-ok">已归一</span>
                  <span v-else class="match-no">未归一</span>
                </td>
                <td>
                  <a-button
                      type="link"
                      size="small"
                      style="padding:0 4px;font-size:12px"
                      @click="openEdit(r)"
                  >
                    修改
                  </a-button>

                  <a-popconfirm
                      title="确认删除该映射关系吗？"
                      ok-text="删除"
                      cancel-text="取消"
                      @confirm="deleteMapping(r)"
                  >
                    <a-button
                        type="link"
                        size="small"
                        danger
                        style="padding:0 4px;font-size:12px"
                    >
                      删除
                    </a-button>
                  </a-popconfirm>
                </td>

              </tr>
            </tbody>
          </table>
        </div>
      </a-tab-pane>

      <!-- Tab 2: SSE 会话治理 -->
      <a-tab-pane key="sse" tab="SSE 会话治理">
        <div class="toolbar">
          <div class="toolbar-left">
            <span class="stat-pill">已选 {{ sessionSelected.length }} 条</span>
            <span class="stat-pill">活跃 {{ sessions.length }} 条</span>
          </div>
          <div class="toolbar-right">
            <a-button size="small" :loading="sessionsLoading" @click="fetchSessions">刷新</a-button>
            <a-button
              size="small"
              danger
              :disabled="sessionSelected.length === 0"
              :loading="sessionReleasingLoading"
              @click="forceReleaseSessions"
            >
              强制释放选中会话
            </a-button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 36px;"></th>
                <th>Task ID</th>
                <th>医生</th>
                <th>患者 ID</th>
                <th>连接时长</th>
                <th>最后心跳</th>
                <th>连接时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="sessionsLoading">
                <td colspan="7" class="empty-cell"><a-spin size="small" /></td>
              </tr>
              <tr v-else-if="sessions.length === 0">
                <td colspan="7" class="empty-cell">暂无活跃 SSE 会话</td>
              </tr>
              <tr
                v-for="s in sessions"
                :key="s.task_id"
                :class="{ 'row-overtime': isOvertime(s.duration_seconds) }"
              >
                <td style="width: 36px;">
                  <a-checkbox
                    :checked="sessionSelected.includes(s.task_id)"
                    @change="() => toggleSession(s.task_id)"
                  />
                </td>
                <td class="mono">{{ s.task_id }}</td>
                <td>{{ s.doctor_name || '—' }}</td>
                <td class="mono">{{ s.patient_id || '—' }}</td>
                <td :class="{ 'text-overtime': isOvertime(s.duration_seconds) }">{{ fmtDuration(s.duration_seconds) }}</td>
                <td class="text-dim">{{ fmtDatetime(s.last_heartbeat) }}</td>
                <td class="text-dim">{{ fmtDatetime(s.connected_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </a-tab-pane>

    </a-tabs>
    <a-modal
        v-model:open="editOpen"
        title="修改 EMPI 映射"
        :footer="null"
        width="420"
    >
      <div class="form-row">
        <label>来源系统</label>
        <a-input :value="editForm.source_system" disabled />
      </div>

      <div class="form-row">
        <label>外部 ID</label>
        <a-input :value="editForm.source_id" disabled />
      </div>

      <div class="form-row">
        <label>外部姓名</label>
        <a-input :value="editForm.name" disabled />
      </div>

      <div class="form-row">
        <label>内部患者 ID</label>
        <a-input
            v-model:value="editForm.patient_id"
            placeholder="请输入内部患者 ID"
        />
      </div>

      <div class="form-footer">
        <a-button @click="editOpen = false">取消</a-button>
        <a-button
            type="primary"
            :loading="editLoading"
            style="margin-left:8px"
            @click="submitEdit"
        >
          保存
        </a-button>
      </div>
    </a-modal>

    <!-- 新增映射弹窗 -->
    <a-modal
        v-model:open="addOpen"
        title="新增 EMPI 映射"
        :footer="null"
        width="420"
    >
      <div class="form-row">
        <label>来源系统</label>
        <a-select v-model:value="addForm.source_system" style="width: 100%;">
          <a-select-option value="HIS">HIS</a-select-option>
          <a-select-option value="LIS">LIS</a-select-option>
          <a-select-option value="PACS">PACS</a-select-option>
        </a-select>
      </div>

      <div class="form-row">
        <label>外部 ID</label>
        <a-input v-model:value="addForm.source_id" placeholder="请输入外部系统 ID" />
      </div>

      <div class="form-row">
        <label>内部患者 ID</label>
        <a-input v-model:value="addForm.patient_id" placeholder="请输入内部患者 ID" />
      </div>

      <div class="form-footer">
        <a-button @click="addOpen = false">取消</a-button>
        <a-button
            type="primary"
            :loading="addLoading"
            style="margin-left:8px"
            @click="submitAdd"
        >
          保存
        </a-button>
      </div>
    </a-modal>

  </div>
</template>

<style scoped>
.page {
  padding: 20px 24px;
  min-height: 100%;
  box-sizing: border-box;
  background:
      radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
      radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
      linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}

.page-title {
  font-size: 18px;
  font-weight: 800;
  color: #16324f;
  border-left: 3px solid #19c6d0;
  padding-left: 10px;
  line-height: 1.3;
}

.page-sub {
  font-size: 12px;
  color: #8aa0b8;
  margin-top: 4px;
  padding-left: 13px;
}

.page-header {
  margin-bottom: 16px;
}

.main-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 16px;
}

.main-tabs :deep(.ant-tabs-tab) {
  border-radius: 12px;
  transition: none !important;
}

.main-tabs :deep(.ant-tabs-tab .ant-tabs-tab-btn) {
  color: #5f7894;
  font-weight: 600;
}

.main-tabs :deep(.ant-tabs-tab-active .ant-tabs-tab-btn) {
  color: #2f6fed !important;
  font-weight: 700;
}

.main-tabs :deep(.ant-tabs-ink-bar) {
  background: linear-gradient(90deg, #2f6fed 0%, #19c6d0 100%) !important;
  height: 3px !important;
  border-radius: 999px;
  transition: none !important;
}

/* toolbar */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(109, 145, 186, 0.12);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.stat-pill {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  color: #64748b;
  font-weight: 600;
  border: 1px solid rgba(116, 152, 193, 0.08);
}

.stat-pill.matched {
  background: rgba(16,185,129,0.1);
  color: #059669;
  border-color: rgba(16,185,129,0.16);
}

.stat-pill.unmatched {
  background: rgba(245,158,11,0.12);
  color: #b45309;
  border-color: rgba(245,158,11,0.18);
}

.load-time {
  font-size: 12px;
  color: #8aa0b8;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.form-row label {
  font-size: 12px;
  color: #5f7894;
  font-weight: 600;
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

/* table */
.table-wrap {
  border: 1px solid rgba(109, 145, 186, 0.12);
  border-radius: 18px;
  overflow: hidden;
  max-height: 560px;
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 18px 38px rgba(95, 130, 171, 0.08);
  backdrop-filter: blur(14px);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  position: sticky;
  top: 0;
  background: rgba(244, 249, 255, 0.94);
  color: #5c7692;
  font-weight: 700;
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid rgba(116, 152, 193, 0.12);
  white-space: nowrap;
  z-index: 1;
}

.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(116, 152, 193, 0.08);
  color: #35506f;
  vertical-align: middle;
  background: rgba(255,255,255,0.32);
}

.data-table tr:last-child td {
  border-bottom: none;
}

.data-table tr:hover td {
  background: rgba(237,245,255,0.88);
}

.row-unmatched td {
  background: rgba(255, 251, 235, 0.72);
}

.row-unmatched:hover td {
  background: rgba(255, 247, 237, 0.92);
}

.mono {
  font-family: monospace;
  font-size: 11px;
}

.text-dim {
  color: #8aa0b8;
}

.empty-cell {
  text-align: center;
  color: #8aa0b8;
  padding: 28px;
}

/* badges */
.sys-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.sys-badge.his {
  background: rgba(16,185,129,0.1);
  color: #059669;
  border: 1px solid rgba(16,185,129,0.16);
}

.sys-badge.lis {
  background: rgba(245,158,11,0.12);
  color: #b45309;
  border: 1px solid rgba(245,158,11,0.18);
}

.sys-badge.pacs {
  background: rgba(47,111,237,0.08);
  color: #2563eb;
  border: 1px solid rgba(47,111,237,0.16);
}

.match-ok {
  color: #059669;
  font-size: 11px;
  font-weight: 700;
}

.match-conflict {
  color: #dc2626;
  font-size: 11px;
  font-weight: 700;
}

.row-conflict td {
  background: rgba(239, 68, 68, 0.08);
}

.row-conflict:hover td {
  background: rgba(239, 68, 68, 0.14);
}

:deep(.ant-select .ant-select-selector) {
  border-radius: 12px !important;
  border-color: rgba(116,152,193,0.14) !important;
  background: rgba(248,251,255,0.8) !important;
}


.row-overtime td {
  background: rgba(255, 247, 237, 0.76);
}

.row-overtime:hover td {
  background: rgba(255, 237, 213, 0.96);
}

.text-overtime {
  color: #ea580c;
  font-weight: 700;
}

:deep(.ant-btn) {
  border-radius: 12px;
}

:deep(.ant-btn-primary) {
  border: none !important;
  background: #2f9fe2 !important;
  box-shadow: 0 14px 28px rgba(47, 159, 226, 0.18);
  font-weight: 700;
}

:deep(.ant-btn-primary:hover),
:deep(.ant-btn-primary:focus) {
  background: #2f9fe2 !important;
}

:deep(.ant-btn-default) {
  border-color: rgba(92,128,170,0.18) !important;
  color: #52708e !important;
  background: rgba(255,255,255,0.82) !important;
}

:deep(.ant-btn-link) {
  color: #2f6fed;
}

:deep(.ant-btn-link:hover) {
  color: #19c6d0;
}

:deep(.ant-input) {
  border-radius: 12px !important;
  border-color: rgba(116,152,193,0.14) !important;
  background: rgba(248,251,255,0.8) !important;
}

:deep(.ant-input:focus),
:deep(.ant-input-focused) {
  border-color: rgba(47,111,237,0.24) !important;
  box-shadow: 0 0 0 4px rgba(47,111,237,0.08) !important;
}

:deep(.ant-radio-group) {
  border-radius: 12px;
  overflow: hidden;
}

:deep(.ant-radio-button-wrapper) {
  border-radius: 0 !important;
  color: #5f7894;
  border-color: rgba(116,152,193,0.14) !important;
  background: rgba(255,255,255,0.86);
}

:deep(.ant-radio-button-wrapper-checked) {
  color: #2f6fed !important;
  background: rgba(47,111,237,0.08) !important;
  border-color: rgba(47,111,237,0.18) !important;
  box-shadow: none !important;
}

:deep(.ant-checkbox-inner) {
  border-radius: 6px;
}

:deep(.ant-spin-dot-item) {
  background-color: #2f6fed;
}

:deep(.ant-modal-content) {
  border-radius: 20px;
  overflow: hidden;
  background: rgba(255,255,255,0.96);
}

:deep(.ant-modal-header) {
  border-bottom: 1px solid rgba(116,152,193,0.1);
  background: transparent;
}

:deep(.ant-modal-title) {
  color: #18395e;
  font-weight: 800;
}
</style>
