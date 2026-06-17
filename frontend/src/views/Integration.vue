<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const route = useRoute()

const activeTab = ref('config')
const sources = ref([])
const aiHealthy = ref(null)
const hisHealthy = ref(null)
const aiResponseMs = ref(null)
const queuedTasks = ref(null)
const statusLoading = ref(false)
const lastCheck = ref('')
const dataLoadedAt = ref('')

function fmtTime(d) {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function fetchSources() {
  try {
    const res = await apiFetch('/api/empi/sources')
    if (res.ok) {
      sources.value = await res.json()
      dataLoadedAt.value = fmtTime(new Date())
    }
  } catch {}
}

async function fetchStatus() {
  statusLoading.value = true
  try {
    const [aiRes, hisRes, statsRes] = await Promise.allSettled([
      fetch('/api/health/ai'),
      fetch('/api/health/his'),
      apiFetch('/api/empi/stats'),
    ])
    if (aiRes.status === 'fulfilled' && aiRes.value.ok) {
      const h = await aiRes.value.json()
      aiHealthy.value = h.ok === true
      aiResponseMs.value = h.response_time_ms ?? null
    } else {
      aiHealthy.value = false
    }
    hisHealthy.value = hisRes.status === 'fulfilled' && hisRes.value.ok
    if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
      const s = await statsRes.value.json()
      queuedTasks.value = s.queued_tasks ?? null
    }
  } finally {
    statusLoading.value = false
    lastCheck.value = fmtTime(new Date())
  }
}

const totalMatched = computed(() => sources.value.filter(r => r.patient_id).length)
const sourceStats = computed(() => ({
  HIS: sources.value.filter(r => r.source_system === 'HIS').length,
  LIS: sources.value.filter(r => r.source_system === 'LIS').length,
  PACS: sources.value.filter(r => r.source_system === 'PACS').length,
}))

const alerts = computed(() => {
  const a = []
  if (aiHealthy.value === false) a.push('AI 推理服务不可用，无法发起新分析任务')
  if (hisHealthy.value === false) a.push('HIS 数据源连接断开，临床视图病历数据可能缺失')
  return a
})

function dotClass(val) {
  if (val === true) return 'dot green'
  if (val === false) return 'dot red'
  return 'dot gray'
}

function valClass(val) {
  if (val === true) return 'val green'
  if (val === false) return 'val red'
  return 'val gray'
}

// --- 抽屉/弹窗状态 ---
const mappingDrawerOpen = ref(false)
const syncLogDrawerOpen = ref(false)
const mappingFilter = ref('ALL')
const syncLoading = ref(false)

const filteredSources = computed(() => {
  if (mappingFilter.value === 'ALL') return sources.value
  return sources.value.filter(r => r.source_system === mappingFilter.value)
})

const syncStats = computed(() => ['HIS', 'LIS', 'PACS'].map(sys => {
  const rows = sources.value.filter(r => r.source_system === sys)
  return {
    system: sys,
    total: rows.length,
    matched: rows.filter(r => r.patient_id).length,
    unmatched: rows.filter(r => !r.patient_id).length,
  }
}))

const unmatchedSources = computed(() => sources.value.filter(r => !r.patient_id))

async function handleRefresh() {
  await Promise.all([fetchSources(), fetchStatus()])
}

async function handleManualSync() {
  syncLoading.value = true
  try {
    await fetchSources()
  } finally {
    syncLoading.value = false
  }
}

onMounted(async () => {
  if (route.query.tab === 'status') activeTab.value = 'status'
  await Promise.all([fetchSources(), fetchStatus()])
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">数据集成</div>
      <div class="page-sub">数据接入配置 · 系统状态监控</div>
    </div>

    <a-tabs v-model:activeKey="activeTab" class="main-tabs">

      <!-- Tab 1: 数据接入配置 -->
      <a-tab-pane key="config" tab="数据接入配置">
        <div class="config-grid">

          <!-- EMPI 患者主索引配置 -->
          <div class="card">
            <div class="card-title">EMPI 患者主索引配置</div>
            <div class="card-sub">跨系统患者身份归一映射</div>
            <div class="stat-row">
              <div class="stat-item">
                <span class="stat-n">{{ sourceStats.HIS }}</span>
                <span class="stat-l">HIS</span>
              </div>
              <div class="stat-item">
                <span class="stat-n lis">{{ sourceStats.LIS }}</span>
                <span class="stat-l">LIS</span>
              </div>
              <div class="stat-item">
                <span class="stat-n pacs">{{ sourceStats.PACS }}</span>
                <span class="stat-l">PACS</span>
              </div>
              <div class="stat-item">
                <span class="stat-n matched">{{ totalMatched }}/{{ sources.length }}</span>
                <span class="stat-l">已归一</span>
              </div>
            </div>
            <div class="info-rows">
              <div class="info-row"><span class="lbl">归一字段</span><span>HIS病历号、身份证、PACS影像ID、LIS流水号</span></div>
              <div class="info-row"><span class="lbl">同步方式</span><span>平台启动时自动同步</span></div>
              <div class="info-row"><span class="lbl">数据拉取</span><span class="gray">{{ dataLoadedAt || '—' }}（本次会话）</span></div>
            </div>
            <div class="card-actions">
              <a-button size="small" @click="syncLogDrawerOpen = true">查看同步快照</a-button>
            </div>
          </div>

          <!-- FHIR 归一化接口配置 -->
          <div class="card">
            <div class="card-title">FHIR 归一化接口配置</div>
            <div class="card-sub">多源接入与字段映射说明</div>
            <div class="info-rows">
              <div class="info-row">
                <span class="lbl">HIS 接入</span>
                <span class="dot green" style="margin-right:4px"></span>
                <span>内部 MySQL · 已接入</span>
              </div>
              <div class="info-row">
                <span class="lbl">LIS 接入</span>
                <span class="dot green" style="margin-right:4px"></span>
                <span>内部 MySQL · 已接入</span>
              </div>
              <div class="info-row">
                <span class="lbl">PACS 接入</span>
                <span class="dot green" style="margin-right:4px"></span>
                <span>本地文件系统 · 已接入</span>
              </div>
              <div class="info-row">
                <span class="lbl">FHIR 服务</span>
                <span class="dot gray" style="margin-right:4px"></span>
                <span class="gray">未启用（待 M4）</span>
              </div>
              <div class="info-row"><span class="lbl">归一策略</span><span>内置匹配（身份证 / 手机 / 姓名）</span></div>
              <div class="info-row"><span class="lbl">术语词表</span><span class="gray">ICD-10 / SNOMED（待扩展）</span></div>
            </div>
            <div class="card-actions">
              <a-button size="small" @click="mappingDrawerOpen = true">查看映射明细</a-button>
            </div>
          </div>

          <!-- DICOM 转码配置 -->
          <div class="card">
            <div class="card-title">DICOM 转码配置</div>
            <div class="card-sub">影像入库与格式转换策略（AI 推理域负责）</div>
            <div class="info-rows">
              <div class="info-row"><span class="lbl">转码策略</span><span>入库时自动转码</span></div>
              <div class="info-row"><span class="lbl">输出格式</span><span>JPEG + PNG（含缩略图）</span></div>
              <div class="info-row"><span class="lbl">色彩处理</span><span>防御性 YBR→RGB 还原；单通道按标签处理</span></div>
              <div class="info-row"><span class="lbl">容错规则</span><span>转码失败保留原文件，不中断流程</span></div>
              <div class="info-row"><span class="lbl">参数编辑</span><span class="gray">仅 AI 推理域可配置，本域无接口</span></div>
            </div>
            <div class="card-actions">
              <a-button size="small" disabled title="转码参数由 AI 推理域管理，应用域无配置接口">影像校验入口（无接口）</a-button>
            </div>
          </div>

          <!-- 数据同步任务管理 -->
          <div class="card">
            <div class="card-title">数据同步任务管理</div>
            <div class="card-sub">三库数据读取 · 手动重新拉取</div>
            <div class="info-rows">
              <div class="info-row"><span class="lbl">数据来源</span><span>HIS / LIS / PACS（三库）</span></div>
              <div class="info-row"><span class="lbl">同步模式</span><span class="gray">按需读取（无定时任务）</span></div>
              <div class="info-row"><span class="lbl">外部记录总数</span><span>{{ sources.length }} 条</span></div>
              <div class="info-row"><span class="lbl">未归一条数</span><span>{{ sources.length - totalMatched }} 条</span></div>
              <div class="info-row"><span class="lbl">数据拉取时间</span><span class="gray">{{ dataLoadedAt || '—' }}（本次会话）</span></div>
            </div>
            <div class="card-actions">
              <a-button size="small" :loading="syncLoading" @click="handleManualSync">重新读取数据源</a-button>
              <a-button size="small" style="margin-left:8px" @click="syncLogDrawerOpen = true">查看同步快照</a-button>
            </div>
          </div>

        </div>
      </a-tab-pane>

      <!-- Tab 2: 系统状态监控 -->
      <a-tab-pane key="status" tab="系统状态监控">
        <div v-if="statusLoading" class="loading-wrap">
          <a-spin />
        </div>
        <div v-else>
          <div class="status-grid">

            <!-- 数据接入服务状态 -->
            <div class="card status-card">
              <div class="card-title">数据接入服务</div>
              <div class="status-rows">
                <div class="status-row">
                  <span :class="dotClass(hisHealthy)"></span>
                  <span class="svc-label">HIS 内部数据库</span>
                  <span :class="valClass(hisHealthy)">
                    {{ hisHealthy === null ? '检测中' : hisHealthy ? '连通' : '断开' }}
                  </span>
                </div>
                <div class="status-row">
                  <span class="dot gray"></span>
                  <span class="svc-label">FHIR Mock Server</span>
                  <span class="val gray">未启用</span>
                </div>
                <div class="status-row">
                  <span class="dot green"></span>
                  <span class="svc-label">PACS 文件系统</span>
                  <span class="val green">可访问</span>
                </div>
                <div class="status-row">
                  <span class="dot green"></span>
                  <span class="svc-label">EMPI 主索引</span>
                  <span class="val green">{{ totalMatched }} / {{ sources.length }} 已归一</span>
                </div>
              </div>
              <div class="last-check">最近检测：{{ lastCheck || '—' }}</div>
            </div>

            <!-- AI 推理域服务状态 -->
            <div class="card status-card">
              <div class="card-title">AI 推理域服务</div>
              <div class="status-rows">
                <div class="status-row">
                  <span :class="dotClass(aiHealthy)"></span>
                  <span class="svc-label">FastAPI 推理后端</span>
                  <span :class="valClass(aiHealthy)">
                    {{ aiHealthy === null ? '检测中' : aiHealthy ? '在线' : '离线' }}
                  </span>
                </div>
                <div class="status-row">
                  <span :class="dotClass(aiHealthy)"></span>
                  <span class="svc-label">SSE 流式推送</span>
                  <span :class="valClass(aiHealthy)">
                    {{ aiHealthy === null ? '检测中' : aiHealthy ? '正常' : '异常' }}
                  </span>
                </div>
                <div class="status-row">
                  <span class="dot gray"></span>
                  <span class="svc-label">推理响应耗时</span>
                  <span class="val gray">{{ aiResponseMs !== null ? aiResponseMs + ' ms' : '—' }}</span>
                </div>
                <div class="status-row">
                  <span class="dot gray"></span>
                  <span class="svc-label">当前排队任务</span>
                  <span class="val gray">{{ queuedTasks !== null ? queuedTasks + ' 条' : '—' }}</span>
                </div>
              </div>
              <div class="last-check">断连自动回收：SSE 客户端关闭时释放</div>
            </div>

            <!-- 全局系统信息 -->
            <div class="card status-card">
              <div class="card-title">全局系统信息</div>
              <div class="status-rows">
                <div class="status-row">
                  <span class="svc-label">平台告警</span>
                  <span :class="['val', alerts.length ? 'red' : 'green']">
                    {{ alerts.length ? alerts.length + ' 条活跃告警' : '无告警' }}
                  </span>
                </div>
                <div class="status-row">
                  <span class="svc-label">数据拉取时间</span>
                  <span class="val gray">{{ dataLoadedAt || '—' }}</span>
                </div>
                <div class="status-row">
                  <span class="svc-label">今日活跃用户</span>
                  <span class="val gray no-iface">无接口支持</span>
                </div>
                <div class="status-row">
                  <span class="svc-label">系统日志导出</span>
                  <span class="val gray no-iface">无接口支持</span>
                </div>
              </div>
              <div v-if="alerts.length" class="alert-block">
                <div v-for="a in alerts" :key="a" class="alert-row">{{ a }}</div>
              </div>
              <div class="card-actions">
                <a-button size="small" disabled title="当前版本无日志导出接口">导出系统日志（无接口）</a-button>
              </div>
            </div>

          </div>

          <div class="status-footer">
            <a-button size="small" @click="router.push('/dashboard')">返回首页</a-button>
            <a-button size="small" :loading="statusLoading" @click="handleRefresh" style="margin-left:8px">刷新系统状态</a-button>
            <span class="footer-note">最近检测：{{ lastCheck || '—' }}</span>
          </div>
        </div>
      </a-tab-pane>

    </a-tabs>

    <!-- Modal：EMPI 归一映射明细 -->
    <a-modal v-model:open="mappingDrawerOpen" title="EMPI 归一映射明细" width="800" :footer="null">
      <div class="modal-filter">
        <a-radio-group v-model:value="mappingFilter" size="small" button-style="solid">
          <a-radio-button value="ALL">全部（{{ sources.length }}）</a-radio-button>
          <a-radio-button value="HIS">HIS（{{ sourceStats.HIS }}）</a-radio-button>
          <a-radio-button value="LIS">LIS（{{ sourceStats.LIS }}）</a-radio-button>
          <a-radio-button value="PACS">PACS（{{ sourceStats.PACS }}）</a-radio-button>
        </a-radio-group>
      </div>
      <div class="modal-table-wrap">
        <table class="map-table">
          <thead>
            <tr>
              <th>来源</th>
              <th>外部 ID</th>
              <th>姓名</th>
              <th>身份证</th>
              <th>手机</th>
              <th>内部患者 ID</th>
              <th>内部姓名</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in filteredSources" :key="r.source_system + r.source_id">
              <td><span class="sys-badge" :class="r.source_system.toLowerCase()">{{ r.source_system }}</span></td>
              <td class="mono">{{ r.source_id }}</td>
              <td>{{ r.name }}</td>
              <td class="mono text-dim">{{ r.id_card ? r.id_card.slice(0, 6) + '****' + r.id_card.slice(-4) : '—' }}</td>
              <td class="text-dim">{{ r.phone || '—' }}</td>
              <td class="mono">{{ r.patient_id || '—' }}</td>
              <td>{{ r.internal_name || '—' }}</td>
              <td>
                <span v-if="r.patient_id" class="match-ok">已归一</span>
                <span v-else class="match-no">未归一</span>
              </td>
            </tr>
            <tr v-if="filteredSources.length === 0">
              <td colspan="8" class="empty-cell">暂无数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-modal>

    <!-- Modal：同步快照 -->
    <a-modal v-model:open="syncLogDrawerOpen" title="数据同步快照" width="560" :footer="null">
      <p class="modal-note">当前系统为按需读取模式，无定时同步任务。以下为本次会话的数据快照（{{ dataLoadedAt || '—' }}）。</p>
      <div class="sync-summary">
        <div v-for="s in syncStats" :key="s.system" class="sync-stat-row">
          <span class="sys-badge" :class="s.system.toLowerCase()">{{ s.system }}</span>
          <span class="sync-col">{{ s.total }} 条记录</span>
          <span class="sync-col matched">{{ s.matched }} 已归一</span>
          <span v-if="s.unmatched > 0" class="sync-col unmatched">{{ s.unmatched }} 未归一</span>
          <span v-else class="sync-col all-ok">全部归一</span>
        </div>
      </div>
      <div v-if="unmatchedSources.length" class="unmatched-section">
        <div class="unmatched-title">未归一记录（{{ unmatchedSources.length }} 条）</div>
        <table class="map-table">
          <thead>
            <tr><th>来源</th><th>外部 ID</th><th>姓名</th><th>身份证</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in unmatchedSources" :key="r.source_system + r.source_id">
              <td><span class="sys-badge" :class="r.source_system.toLowerCase()">{{ r.source_system }}</span></td>
              <td class="mono">{{ r.source_id }}</td>
              <td>{{ r.name }}</td>
              <td class="mono text-dim">{{ r.id_card ? r.id_card.slice(0, 6) + '****' + r.id_card.slice(-4) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="all-matched-tip">全部外部记录已归一，无待处理项。</div>
    </a-modal>

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

/* Config grid: 2x2 */
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* Status grid: 3 columns */
.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.card {
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  padding: 18px 20px;
}

.status-card { display: flex; flex-direction: column; }

.card-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.card-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 14px;
}

/* EMPI stat row */
.stat-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 48px;
}

.stat-n {
  font-size: 22px;
  font-weight: 700;
  color: #10b981;
  line-height: 1;
}

.stat-n.lis   { color: #f59e0b; }
.stat-n.pacs  { color: #2563eb; }
.stat-n.matched { color: #059669; }

.stat-l {
  font-size: 11px;
  color: #64748b;
  margin-top: 4px;
}

/* Info rows */
.info-rows { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }

.info-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #475569;
}

.lbl {
  color: #94a3b8;
  min-width: 80px;
  font-size: 12px;
  flex-shrink: 0;
}

.gray { color: #94a3b8; }

.card-actions { margin-top: auto; padding-top: 4px; }

/* Status section rows */
.status-rows { display: flex; flex-direction: column; gap: 10px; flex: 1; margin-bottom: 12px; }

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.svc-label { flex: 1; color: #475569; }

.val { font-size: 12px; font-weight: 500; }
.val.green { color: #10b981; }
.val.red   { color: #ef4444; }
.val.gray  { color: #94a3b8; }

/* Dots */
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.dot.green { background: #10b981; }
.dot.red   { background: #ef4444; }
.dot.gray  { background: #cbd5e1; }

.last-check { font-size: 11px; color: #94a3b8; margin-top: auto; }

/* Alert block */
.alert-block {
  background: #fef2f2;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.alert-row {
  font-size: 12px;
  color: #dc2626;
  line-height: 1.7;
}

/* Footer */
.status-footer {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 12px 0 4px;
}

.footer-note {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 16px;
}

.loading-wrap {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}

/* Modal: filter bar */
.modal-filter { margin-bottom: 14px; }

/* Modal: table wrapper */
.modal-table-wrap {
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid #e8ecf2;
  border-radius: 8px;
}

/* Shared mapping table */
.map-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.map-table th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #e8ecf2;
  white-space: nowrap;
}
.map-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #475569;
  vertical-align: middle;
}
.map-table tr:last-child td { border-bottom: none; }
.map-table tr:hover td { background: #f8fafc; }

.mono { font-family: monospace; font-size: 11px; }
.text-dim { color: #94a3b8; }
.empty-cell { text-align: center; color: #94a3b8; padding: 20px; }

/* Source system badge */
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

/* Match status */
.match-ok { color: #10b981; font-size: 11px; font-weight: 600; }
.match-no { color: #f59e0b; font-size: 11px; font-weight: 600; }

/* no-iface inline label */
.no-iface { font-style: italic; }

/* Sync snapshot modal */
.modal-note {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 14px;
  line-height: 1.6;
}
.sync-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.sync-stat-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
}
.sync-col { color: #475569; }
.sync-col.matched { color: #10b981; font-weight: 500; }
.sync-col.unmatched { color: #f59e0b; font-weight: 500; }
.sync-col.all-ok { color: #10b981; font-weight: 500; }

.unmatched-section { margin-top: 16px; }
.unmatched-title {
  font-size: 12px;
  font-weight: 600;
  color: #f59e0b;
  margin-bottom: 8px;
}
.all-matched-tip {
  text-align: center;
  font-size: 12px;
  color: #10b981;
  padding: 12px 0;
}
</style>
