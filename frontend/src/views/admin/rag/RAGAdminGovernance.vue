<script setup>
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { apiFetch } from '@/utils/api'

const activeTab = ref('rules')
const activeAuditTab = ref('rejection_hits')

// ── 共用工具 ─────────────────────────────────────────────────────────────────

async function apiGet(path) {
  const res = await apiFetch(path)
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}
async function apiPost(path, body) {
  const res = await apiFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.message || d.detail || `${res.status}`) }
  return res.json()
}
async function apiPut(path, body) {
  const res = await apiFetch(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.message || d.detail || `${res.status}`) }
  return res.json()
}
async function apiDelete(path) {
  const res = await apiFetch(path, { method: 'DELETE' })
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.message || d.detail || `${res.status}`) }
  return res.json()
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 1: 规则回答 (Rules)
// ══════════════════════════════════════════════════════════════════════════════

const rules = ref([])
const rulesLoading = ref(false)
const ruleModalVisible = ref(false)
const ruleModalLoading = ref(false)
const ruleForm = reactive({ rule_id: null, match_type: 'keyword', pattern: '', answer: '', priority: 0, enabled: true })

async function loadRules() {
  rulesLoading.value = true
  try {
    const data = await apiGet('/api/rag/admin/rules?include_disabled=true')
    rules.value = Array.isArray(data) ? data : []
  } catch (e) { message.error('加载规则失败: ' + e.message) }
  finally { rulesLoading.value = false }
}

function openRuleCreate() {
  Object.assign(ruleForm, { rule_id: null, match_type: 'keyword', pattern: '', answer: '', priority: 0, enabled: true })
  ruleModalVisible.value = true
}

function openRuleEdit(row) {
  Object.assign(ruleForm, { ...row })
  ruleModalVisible.value = true
}

async function saveRule() {
  if (!ruleForm.pattern || !ruleForm.answer) { message.warning('规则模式和回答不能为空'); return }
  ruleModalLoading.value = true
  try {
    const body = { match_type: ruleForm.match_type, pattern: ruleForm.pattern, answer: ruleForm.answer, priority: ruleForm.priority, enabled: ruleForm.enabled }
    if (ruleForm.rule_id) {
      await apiPut(`/api/rag/admin/rules/${ruleForm.rule_id}`, body)
      message.success('规则已更新')
    } else {
      await apiPost('/api/rag/admin/rules', body)
      message.success('规则已创建')
    }
    ruleModalVisible.value = false
    await loadRules()
  } catch (e) { message.error('保存失败: ' + e.message) }
  finally { ruleModalLoading.value = false }
}

async function deleteRule(ruleId) {
  try {
    await apiDelete(`/api/rag/admin/rules/${ruleId}`)
    message.success('规则已删除')
    await loadRules()
  } catch (e) { message.error('删除失败: ' + e.message) }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 2: 拒绝规则 (Rejections)
// ══════════════════════════════════════════════════════════════════════════════

const rejections = ref([])
const rejectionsLoading = ref(false)
const rejModalVisible = ref(false)
const rejModalLoading = ref(false)
const rejForm = reactive({ rule_id: null, match_type: 'keyword', pattern: '', reject_reason: '', log_only: false, enabled: true })

async function loadRejections() {
  rejectionsLoading.value = true
  try {
    const data = await apiGet('/api/rag/admin/rejections?include_disabled=true')
    rejections.value = Array.isArray(data) ? data : []
  } catch (e) { message.error('加载拒绝规则失败: ' + e.message) }
  finally { rejectionsLoading.value = false }
}

function openRejCreate() {
  Object.assign(rejForm, { rule_id: null, match_type: 'keyword', pattern: '', reject_reason: '', log_only: false, enabled: true })
  rejModalVisible.value = true
}

function openRejEdit(row) {
  Object.assign(rejForm, { ...row })
  rejModalVisible.value = true
}

async function saveRejection() {
  if (!rejForm.pattern || !rejForm.reject_reason) { message.warning('规则模式和拒绝原因不能为空'); return }
  rejModalLoading.value = true
  try {
    const body = { match_type: rejForm.match_type, pattern: rejForm.pattern, reject_reason: rejForm.reject_reason, log_only: rejForm.log_only, enabled: rejForm.enabled }
    if (rejForm.rule_id) {
      await apiPut(`/api/rag/admin/rejections/${rejForm.rule_id}`, body)
      message.success('拒绝规则已更新')
    } else {
      await apiPost('/api/rag/admin/rejections', body)
      message.success('拒绝规则已创建')
    }
    rejModalVisible.value = false
    await loadRejections()
  } catch (e) { message.error('保存失败: ' + e.message) }
  finally { rejModalLoading.value = false }
}

async function deleteRejection(ruleId) {
  try {
    await apiDelete(`/api/rag/admin/rejections/${ruleId}`)
    message.success('拒绝规则已删除')
    await loadRejections()
  } catch (e) { message.error('删除失败: ' + e.message) }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 3: 拒绝日志 (Rejection Logs) — 只读
// ══════════════════════════════════════════════════════════════════════════════

const rejectionLogs = ref([])
const rejLogsLoading = ref(false)
const rejLogsTotal = ref(0)
const rejLogsLimit = ref(100)
const rejLogsOffset = ref(0)

async function loadRejectionLogs() {
  rejLogsLoading.value = true
  try {
    const data = await apiGet(`/api/rag/admin/rejection-logs?limit=${rejLogsLimit.value}&offset=${rejLogsOffset.value}`)
    rejectionLogs.value = Array.isArray(data.logs) ? data.logs : []
    rejLogsTotal.value = data.total || 0
  } catch (e) { message.error('加载拒绝日志失败: ' + e.message) }
  finally { rejLogsLoading.value = false }
}

const sensitiveHitLogs = ref([])
const sensitiveHitLoading = ref(false)
const sensitiveHitTotal = ref(0)
const sensitiveHitLimit = ref(100)
const sensitiveHitOffset = ref(0)

async function loadSensitiveHitLogs() {
  sensitiveHitLoading.value = true
  try {
    const data = await apiGet(`/api/rag/admin/sensitive-hit-logs?limit=${sensitiveHitLimit.value}&offset=${sensitiveHitOffset.value}`)
    sensitiveHitLogs.value = Array.isArray(data.logs) ? data.logs : []
    sensitiveHitTotal.value = data.total || 0
  } catch (e) { message.error('加载敏感词命中失败: ' + e.message) }
  finally { sensitiveHitLoading.value = false }
}

const phiAuditLogs = ref([])
const phiAuditLoading = ref(false)
const phiAuditTotal = ref(0)
const phiAuditLimit = ref(100)
const phiAuditOffset = ref(0)

async function loadPhiAuditLogs() {
  phiAuditLoading.value = true
  try {
    const data = await apiGet(`/api/rag/admin/phi-audit-logs?limit=${phiAuditLimit.value}&offset=${phiAuditOffset.value}`)
    phiAuditLogs.value = Array.isArray(data.logs) ? data.logs : []
    phiAuditTotal.value = data.total || 0
  } catch (e) { message.error('加载 PHI 审计失败: ' + e.message) }
  finally { phiAuditLoading.value = false }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 4: 敏感词 (Sensitive Words)
// ══════════════════════════════════════════════════════════════════════════════

const sensitiveWords = ref([])
const swLoading = ref(false)
const swModalVisible = ref(false)
const swModalLoading = ref(false)
const swForm = reactive({ word_id: null, word: '', enabled: true })

async function loadSensitiveWords() {
  swLoading.value = true
  try {
    const data = await apiGet('/api/rag/admin/sensitive-words?include_disabled=true')
    sensitiveWords.value = Array.isArray(data) ? data : []
  } catch (e) { message.error('加载敏感词失败: ' + e.message) }
  finally { swLoading.value = false }
}

function openSwCreate() {
  Object.assign(swForm, { word_id: null, word: '', enabled: true })
  swModalVisible.value = true
}

function openSwEdit(row) {
  Object.assign(swForm, { ...row })
  swModalVisible.value = true
}

async function saveSensitiveWord() {
  if (!swForm.word) { message.warning('敏感词不能为空'); return }
  swModalLoading.value = true
  try {
    const body = { word: swForm.word, enabled: swForm.enabled }
    if (swForm.word_id) {
      await apiPut(`/api/rag/admin/sensitive-words/${swForm.word_id}`, body)
      message.success('敏感词已更新')
    } else {
      await apiPost('/api/rag/admin/sensitive-words', body)
      message.success('敏感词已添加')
    }
    swModalVisible.value = false
    await loadSensitiveWords()
  } catch (e) { message.error('保存失败: ' + e.message) }
  finally { swModalLoading.value = false }
}

async function deleteSensitiveWord(wordId) {
  try {
    await apiDelete(`/api/rag/admin/sensitive-words/${wordId}`)
    message.success('敏感词已删除')
    await loadSensitiveWords()
  } catch (e) { message.error('删除失败: ' + e.message) }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 5: 模型配置 (Model Configs)
// ══════════════════════════════════════════════════════════════════════════════

const modelConfigs = ref([])
const mcLoading = ref(false)
const mcEditingKey = ref(null)
const mcEditValue = ref('')
const mcSaving = ref(false)

async function loadModelConfigs() {
  mcLoading.value = true
  try {
    const data = await apiGet('/api/rag/admin/model-configs')
    modelConfigs.value = Array.isArray(data) ? data : []
  } catch (e) { message.error('加载模型配置失败: ' + e.message) }
  finally { mcLoading.value = false }
}

function startEditConfig(row) {
  mcEditingKey.value = row.config_key
  mcEditValue.value = row.config_value
}

function cancelEditConfig() {
  mcEditingKey.value = null
  mcEditValue.value = ''
}

async function saveModelConfig(configKey) {
  if (!mcEditValue.value) { message.warning('配置值不能为空'); return }
  mcSaving.value = true
  try {
    await apiPut(`/api/rag/admin/model-configs/${configKey}`, { config_value: mcEditValue.value })
    message.success('配置已更新')
    mcEditingKey.value = null
    await loadModelConfigs()
  } catch (e) { message.error('保存失败: ' + e.message) }
  finally { mcSaving.value = false }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab 切换懒加载
// ══════════════════════════════════════════════════════════════════════════════

const loaded = reactive({ rules: false, rejections: false, securityaudit: false, sensitive: false, modelconfigs: false })
const auditLoaded = reactive({ rejection_hits: false, sensitive_hits: false, phi_audit: false })

async function onTabChange(key) {
  activeTab.value = key
  if (key === 'rules' && !loaded.rules) { await loadRules(); loaded.rules = true }
  if (key === 'rejections' && !loaded.rejections) { await loadRejections(); loaded.rejections = true }
  if (key === 'securityaudit' && !loaded.securityaudit) {
    await loadRejectionLogs()
    auditLoaded.rejection_hits = true
    loaded.securityaudit = true
  }
  if (key === 'sensitive' && !loaded.sensitive) { await loadSensitiveWords(); loaded.sensitive = true }
  if (key === 'modelconfigs' && !loaded.modelconfigs) { await loadModelConfigs(); loaded.modelconfigs = true }
}

async function onAuditTabChange(key) {
  activeAuditTab.value = key
  if (key === 'rejection_hits' && !auditLoaded.rejection_hits) {
    await loadRejectionLogs()
    auditLoaded.rejection_hits = true
  }
  if (key === 'sensitive_hits' && !auditLoaded.sensitive_hits) {
    await loadSensitiveHitLogs()
    auditLoaded.sensitive_hits = true
  }
  if (key === 'phi_audit' && !auditLoaded.phi_audit) {
    await loadPhiAuditLogs()
    auditLoaded.phi_audit = true
  }
}

onMounted(async () => {
  await loadRules()
  loaded.rules = true
})
</script>

<template>
  <div class="governance-root rag-admin-page rag-admin-tight">
    <div class="gov-header">
      <h2 class="gov-title">RAG 治理管理</h2>
      <p class="gov-sub">规则回答 / 拒绝规则 / 敏感词 / 安全审计 / 模型配置</p>
    </div>

    <a-tabs :active-key="activeTab" @change="onTabChange" class="gov-tabs">

      <!-- ── Tab 1: 规则回答 ─────────────────────────────────────────────── -->
      <a-tab-pane key="rules" tab="规则回答">
        <div class="tab-toolbar">
          <a-button type="primary" size="small" @click="openRuleCreate">+ 新增规则</a-button>
          <a-button size="small" @click="loadRules" :loading="rulesLoading">刷新</a-button>
        </div>
        <a-table
          :data-source="rules"
          :loading="rulesLoading"
          row-key="rule_id"
          size="small"
          :pagination="{ pageSize: 20, showSizeChanger: false }"
        >
          <a-table-column title="ID" data-index="rule_id" width="60" />
          <a-table-column title="匹配类型" data-index="match_type" width="100">
            <template #default="{ record }">
              <a-tag :color="record.match_type === 'regex' ? 'orange' : (record.match_type === 'exact' ? 'blue' : 'default')">
                {{ record.match_type }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column title="模式" data-index="pattern" />
          <a-table-column title="回答" data-index="answer" :ellipsis="true" />
          <a-table-column title="优先级" data-index="priority" width="80" />
          <a-table-column title="状态" data-index="enabled" width="80">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'red'">{{ record.enabled ? '启用' : '禁用' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="操作" width="120">
            <template #default="{ record }">
              <a-space>
                <a-button type="link" size="small" @click="openRuleEdit(record)">编辑</a-button>
                <a-popconfirm title="确认删除此规则?" @confirm="deleteRule(record.rule_id)">
                  <a-button type="link" size="small" danger>删除</a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <!-- ── Tab 2: 拒绝规则 ───────────────────────────────────────────── -->
      <a-tab-pane key="rejections" tab="拒绝规则">
        <div class="tab-toolbar">
          <a-button type="primary" size="small" @click="openRejCreate">+ 新增拒绝规则</a-button>
          <a-button size="small" @click="loadRejections" :loading="rejectionsLoading">刷新</a-button>
        </div>
        <a-table
          :data-source="rejections"
          :loading="rejectionsLoading"
          row-key="rule_id"
          size="small"
          :pagination="{ pageSize: 20, showSizeChanger: false }"
        >
          <a-table-column title="ID" data-index="rule_id" width="60" />
          <a-table-column title="匹配类型" data-index="match_type" width="100">
            <template #default="{ record }">
              <a-tag :color="record.match_type === 'regex' ? 'orange' : (record.match_type === 'exact' ? 'blue' : 'default')">
                {{ record.match_type }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column title="模式" data-index="pattern" />
          <a-table-column title="拒绝原因" data-index="reject_reason" :ellipsis="true" />
          <a-table-column title="仅记录" data-index="log_only" width="80">
            <template #default="{ record }">
              <a-tag :color="record.log_only ? 'blue' : 'red'">{{ record.log_only ? '仅记录' : '拒绝' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="状态" data-index="enabled" width="80">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'red'">{{ record.enabled ? '启用' : '禁用' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="操作" width="120">
            <template #default="{ record }">
              <a-space>
                <a-button type="link" size="small" @click="openRejEdit(record)">编辑</a-button>
                <a-popconfirm title="确认删除此拒绝规则?" @confirm="deleteRejection(record.rule_id)">
                  <a-button type="link" size="small" danger>删除</a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <!-- ── Tab 4: 敏感词 ─────────────────────────────────────────────── -->
      <a-tab-pane key="sensitive" tab="敏感词">
        <div class="tab-toolbar">
          <a-button type="primary" size="small" @click="openSwCreate">+ 新增敏感词</a-button>
          <a-button size="small" @click="loadSensitiveWords" :loading="swLoading">刷新</a-button>
        </div>
        <a-table
          :data-source="sensitiveWords"
          :loading="swLoading"
          row-key="word_id"
          size="small"
          :pagination="{ pageSize: 20, showSizeChanger: false }"
        >
          <a-table-column title="ID" data-index="word_id" width="60" />
          <a-table-column title="敏感词" data-index="word" />
          <a-table-column title="状态" data-index="enabled" width="80">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'red'">{{ record.enabled ? '启用' : '禁用' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="创建时间" data-index="created_at" width="160" />
          <a-table-column title="操作" width="120">
            <template #default="{ record }">
              <a-space>
                <a-button type="link" size="small" @click="openSwEdit(record)">编辑</a-button>
                <a-popconfirm title="确认删除此敏感词?" @confirm="deleteSensitiveWord(record.word_id)">
                  <a-button type="link" size="small" danger>删除</a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <!-- ── Tab 4.5: 安全审计 ─────────────────────────────────────────── -->
      <a-tab-pane key="securityaudit" tab="安全审计">
        <a-tabs :active-key="activeAuditTab" @change="onAuditTabChange" size="small" class="audit-tabs">
          <a-tab-pane key="rejection_hits" tab="拒绝规则命中">
            <div class="tab-toolbar">
              <a-button size="small" @click="loadRejectionLogs" :loading="rejLogsLoading">刷新</a-button>
              <span class="total-badge">共 {{ rejLogsTotal }} 条</span>
            </div>
            <a-table
              :data-source="rejectionLogs"
              :loading="rejLogsLoading"
              row-key="log_id"
              size="small"
              :pagination="false"
            >
              <a-table-column title="ID" data-index="log_id" width="60" />
              <a-table-column title="规则ID" data-index="rule_id" width="80" />
              <a-table-column title="规则模式" data-index="rule_pattern" />
              <a-table-column title="用户问题" data-index="user_question" :ellipsis="true" />
              <a-table-column title="动作" data-index="action" width="80">
                <template #default="{ record }">
                  <a-tag :color="record.action === 'rejected' ? 'red' : 'blue'">{{ record.action }}</a-tag>
                </template>
              </a-table-column>
              <a-table-column title="会话ID" data-index="conversation_id" width="80" />
              <a-table-column title="时间" data-index="created_at" width="160" />
            </a-table>
            <div v-if="rejLogsTotal > rejLogsLimit" class="load-more">
              <a-button size="small" @click="rejLogsOffset += rejLogsLimit; loadRejectionLogs()">加载更多</a-button>
            </div>
          </a-tab-pane>

          <a-tab-pane key="sensitive_hits" tab="敏感词命中">
            <div class="tab-toolbar">
              <a-button size="small" @click="loadSensitiveHitLogs" :loading="sensitiveHitLoading">刷新</a-button>
              <span class="total-badge">共 {{ sensitiveHitTotal }} 条</span>
            </div>
            <a-table
              :data-source="sensitiveHitLogs"
              :loading="sensitiveHitLoading"
              row-key="log_id"
              size="small"
              :pagination="false"
            >
              <a-table-column title="ID" data-index="log_id" width="60" />
              <a-table-column title="命中词" data-index="hit_words">
                <template #default="{ record }">
                  {{ Array.isArray(record.hit_words) ? record.hit_words.join('、') : '' }}
                </template>
              </a-table-column>
              <a-table-column title="用户问题" data-index="user_question" :ellipsis="true" />
              <a-table-column title="动作" data-index="action" width="90">
                <template #default="{ record }">
                  <a-tag :color="record.action === 'blocked' ? 'red' : 'orange'">{{ record.action }}</a-tag>
                </template>
              </a-table-column>
              <a-table-column title="会话ID" data-index="conversation_id" width="80" />
              <a-table-column title="时间" data-index="created_at" width="160" />
            </a-table>
            <div v-if="sensitiveHitTotal > sensitiveHitLimit" class="load-more">
              <a-button size="small" @click="sensitiveHitOffset += sensitiveHitLimit; loadSensitiveHitLogs()">加载更多</a-button>
            </div>
          </a-tab-pane>

          <a-tab-pane key="phi_audit" tab="PHI 审计">
            <div class="tab-toolbar">
              <a-button size="small" @click="loadPhiAuditLogs" :loading="phiAuditLoading">刷新</a-button>
              <span class="total-badge">共 {{ phiAuditTotal }} 条</span>
            </div>
            <a-table
              :data-source="phiAuditLogs"
              :loading="phiAuditLoading"
              row-key="id"
              size="small"
              :pagination="false"
            >
              <a-table-column title="ID" data-index="id" width="60" />
              <a-table-column title="动作" data-index="action" width="120">
                <template #default="{ record }">
                  <a-tag :color="record.action === 'block' ? 'red' : (record.action === 'phi_check' ? 'orange' : 'blue')">
                    {{ record.action }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="命中字段" data-index="phi_fields">
                <template #default="{ record }">
                  {{ Array.isArray(record.phi_fields) ? record.phi_fields.join('、') : '' }}
                </template>
              </a-table-column>
              <a-table-column title="医生ID" data-index="doctor_id" width="80" />
              <a-table-column title="患者ID" data-index="patient_id" width="80" />
              <a-table-column title="会话ID" data-index="conversation_id" width="80" />
              <a-table-column title="时间" data-index="created_at" width="160" />
            </a-table>
            <div v-if="phiAuditTotal > phiAuditLimit" class="load-more">
              <a-button size="small" @click="phiAuditOffset += phiAuditLimit; loadPhiAuditLogs()">加载更多</a-button>
            </div>
          </a-tab-pane>
        </a-tabs>
      </a-tab-pane>

      <!-- ── Tab 5: 模型配置 ───────────────────────────────────────────── -->
      <a-tab-pane key="modelconfigs" tab="模型配置">
        <div class="tab-toolbar">
          <a-button size="small" @click="loadModelConfigs" :loading="mcLoading">刷新</a-button>
          <span class="tab-note">配置修改立即生效，AI 域下次调用时读取</span>
        </div>
        <a-table
          :data-source="modelConfigs"
          :loading="mcLoading"
          row-key="config_id"
          size="small"
          :pagination="false"
        >
          <a-table-column title="配置键" data-index="config_key" width="220" />
          <a-table-column title="配置值">
            <template #default="{ record }">
              <template v-if="mcEditingKey === record.config_key">
                <a-input v-model:value="mcEditValue" size="small" style="width: 240px" @press-enter="saveModelConfig(record.config_key)" />
              </template>
              <template v-else>
                {{ record.config_value }}
              </template>
            </template>
          </a-table-column>
          <a-table-column title="说明" data-index="description" :ellipsis="true" />
          <a-table-column title="更新时间" data-index="updated_at" width="160" />
          <a-table-column title="操作" width="130">
            <template #default="{ record }">
              <template v-if="mcEditingKey === record.config_key">
                <a-space>
                  <a-button type="link" size="small" :loading="mcSaving" @click="saveModelConfig(record.config_key)">保存</a-button>
                  <a-button type="link" size="small" @click="cancelEditConfig">取消</a-button>
                </a-space>
              </template>
              <template v-else>
                <a-button type="link" size="small" @click="startEditConfig(record)">编辑</a-button>
              </template>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

    </a-tabs>

    <!-- ── 规则回答 Modal ──────────────────────────────────────────────────── -->
    <a-modal
      v-model:open="ruleModalVisible"
      :title="ruleForm.rule_id ? '编辑规则回答' : '新增规则回答'"
      :confirm-loading="ruleModalLoading"
      @ok="saveRule"
    >
      <a-form layout="vertical" :model="ruleForm">
        <a-form-item label="匹配类型">
          <a-select v-model:value="ruleForm.match_type">
            <a-select-option value="keyword">keyword（关键词包含）</a-select-option>
            <a-select-option value="regex">regex（正则表达式）</a-select-option>
            <a-select-option value="exact">exact（完全匹配）</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="匹配模式" required>
          <a-input v-model:value="ruleForm.pattern" placeholder="输入关键词、正则或精确文本" />
        </a-form-item>
        <a-form-item label="标准回答" required>
          <a-textarea v-model:value="ruleForm.answer" :rows="4" placeholder="命中后返回的固定回答" />
        </a-form-item>
        <a-form-item label="优先级 (0-100)">
          <a-input-number v-model:value="ruleForm.priority" :min="0" :max="100" style="width: 100%" />
        </a-form-item>
        <a-form-item label="状态">
          <a-switch v-model:checked="ruleForm.enabled" checked-children="启用" un-checked-children="禁用" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ── 拒绝规则 Modal ──────────────────────────────────────────────────── -->
    <a-modal
      v-model:open="rejModalVisible"
      :title="rejForm.rule_id ? '编辑拒绝规则' : '新增拒绝规则'"
      :confirm-loading="rejModalLoading"
      @ok="saveRejection"
    >
      <a-form layout="vertical" :model="rejForm">
        <a-form-item label="匹配类型">
          <a-select v-model:value="rejForm.match_type">
            <a-select-option value="keyword">keyword（关键词包含）</a-select-option>
            <a-select-option value="regex">regex（正则表达式）</a-select-option>
            <a-select-option value="exact">exact（完全匹配）</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="匹配模式" required>
          <a-input v-model:value="rejForm.pattern" placeholder="输入关键词、正则或精确文本" />
        </a-form-item>
        <a-form-item label="拒绝原因" required>
          <a-textarea v-model:value="rejForm.reject_reason" :rows="3" placeholder="命中时返回给用户的提示" />
        </a-form-item>
        <a-form-item label="处理方式">
          <a-radio-group v-model:value="rejForm.log_only">
            <a-radio :value="false">拒绝回答</a-radio>
            <a-radio :value="true">仅记录日志（不阻断）</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="状态">
          <a-switch v-model:checked="rejForm.enabled" checked-children="启用" un-checked-children="禁用" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ── 敏感词 Modal ─────────────────────────────────────────────────────── -->
    <a-modal
      v-model:open="swModalVisible"
      :title="swForm.word_id ? '编辑敏感词' : '新增敏感词'"
      :confirm-loading="swModalLoading"
      @ok="saveSensitiveWord"
    >
      <a-form layout="vertical" :model="swForm">
        <a-form-item label="敏感词" required>
          <a-input v-model:value="swForm.word" placeholder="输入敏感词（最多100字符）" :maxlength="100" />
        </a-form-item>
        <a-form-item label="状态">
          <a-switch v-model:checked="swForm.enabled" checked-children="启用" un-checked-children="禁用" />
        </a-form-item>
      </a-form>
    </a-modal>

  </div>
</template>

<style scoped>
.governance-root {
  padding: 20px 24px;
  min-height: 100%;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
    radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
    linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
  min-height: 100%;
}

.gov-header {
  margin-bottom: 20px;
}

.gov-title {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px;
}

.gov-sub {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
}

.gov-tabs {
  min-height: 400px;
}

.audit-tabs {
  min-height: 360px;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.total-badge {
  font-size: 12px;
  color: #64748b;
}

.tab-note {
  font-size: 11px;
  color: #94a3b8;
}

.load-more {
  margin-top: 12px;
  text-align: center;
}

.audit-placeholder {
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.6);
  border: 1px dashed #dbe7f3;
  border-radius: 12px;
}
</style>
