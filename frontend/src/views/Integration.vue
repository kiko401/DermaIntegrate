<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFetch } from '@/utils/api'

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

const filteredSources = computed(() => {
  let list = sources.value
  if (mappingFilter.value !== 'ALL') {
    list = list.filter(r => r.source_system === mappingFilter.value)
  }
  const q = searchText.value.trim().toLowerCase()
  if (!q) return list
  return list.filter(r =>
    (r.name        || '').toLowerCase().includes(q) ||
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
            <a-tooltip title="扫描冲突功能待实现：需后端提供冲突检测接口">
              <a-button size="small" disabled>扫描冲突</a-button>
            </a-tooltip>
            <a-tooltip title="新增映射功能待实现：需后端提供写入接口">
              <a-button size="small" disabled>新增映射</a-button>
            </a-tooltip>
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
                :class="{ 'row-unmatched': !r.patient_id }"
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
                  <span v-if="r.patient_id" class="match-ok">已归一</span>
                  <span v-else class="match-no">未归一</span>
                </td>
                <td>
                  <a-tooltip title="修改接口待实现">
                    <a-button type="link" size="small" disabled style="padding:0 4px;font-size:12px">修改</a-button>
                  </a-tooltip>
                  <a-tooltip title="删除接口待实现">
                    <a-button type="link" size="small" disabled danger style="padding:0 4px;font-size:12px">删除</a-button>
                  </a-tooltip>
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
  </div>
</template>

<style scoped>
.page {
  padding: 20px 24px;
  background: #f5f7fb;
  min-height: 100%;
  box-sizing: border-box;
}

.page-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  border-left: 3px solid #14b8a6;
  padding-left: 10px;
  line-height: 1.3;
}
.page-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  padding-left: 13px;
}
.page-header { margin-bottom: 16px; }
.main-tabs :deep(.ant-tabs-nav) { margin-bottom: 16px; }

/* toolbar */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.toolbar-left  { display: flex; align-items: center; gap: 8px; }
.toolbar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.stat-pill {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 12px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 500;
}
.stat-pill.matched   { background: #ecfdf5; color: #059669; }
.stat-pill.unmatched { background: #fffbeb; color: #d97706; }

.load-time { font-size: 12px; color: #94a3b8; }

/* table */
.table-wrap {
  border: 1px solid #e8ecf2;
  border-radius: 10px;
  overflow: hidden;
  max-height: 560px;
  overflow-y: auto;
  background: #fff;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
  padding: 9px 12px;
  text-align: left;
  border-bottom: 1px solid #e8ecf2;
  white-space: nowrap;
}
.data-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #475569;
  vertical-align: middle;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: #f8fafc; }
.row-unmatched td { background: #fffdf0; }
.row-unmatched:hover td { background: #fef9e0; }

.mono { font-family: monospace; font-size: 11px; }
.text-dim { color: #94a3b8; }
.empty-cell { text-align: center; color: #94a3b8; padding: 28px; }

/* badges */
.sys-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.sys-badge.his  { background: #ecfdf5; color: #059669; }
.sys-badge.lis  { background: #fffbeb; color: #d97706; }
.sys-badge.pacs { background: #eff6ff; color: #2563eb; }

.match-ok { color: #10b981; font-size: 11px; font-weight: 600; }
.match-no { color: #f59e0b; font-size: 11px; font-weight: 600; }

.row-overtime td { background: #fff7ed; }
.row-overtime:hover td { background: #ffedd5; }
.text-overtime { color: #ea580c; font-weight: 600; }
</style>
