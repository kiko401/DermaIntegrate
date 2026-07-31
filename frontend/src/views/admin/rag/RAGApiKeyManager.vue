<script setup>
import { ref, onMounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts })

const keys = ref([])
const loading = ref(false)
const err = ref('')

const createOpen = ref(false)
const creating = ref(false)
const createErr = ref('')
const createForm = ref({ name: '', rate_limit_per_min: 60, expires_at: '' })
const newRawKey = ref('')

const editId = ref(null)
const editForm = ref({ name: '', status: 'active', rate_limit_per_min: 60, expires_at: '' })
const editSaving = ref(false)
const editErr = ref('')

const statusLabels = { active: '启用', revoked: '已吊销' }

onMounted(fetchKeys)

async function fetchKeys() {
  loading.value = true
  err.value = ''
  try {
    const res = await API('/api/rag/api-keys')
    const data = await res.json()
    if (!res.ok) throw new Error(data.message || data.error || '加载失败')
    keys.value = Array.isArray(data) ? data : (data.data || [])
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.value = { name: '', rate_limit_per_min: 60, expires_at: '' }
  newRawKey.value = ''
  createErr.value = ''
  createOpen.value = true
}

function closeCreate() {
  createOpen.value = false
  newRawKey.value = ''
}

async function doCreate() {
  if (!createForm.value.name.trim()) { createErr.value = '名称不能为空'; return }
  creating.value = true
  createErr.value = ''
  try {
    const body = {
      name: createForm.value.name.trim(),
      rate_limit_per_min: Number(createForm.value.rate_limit_per_min) || 60,
    }
    if (createForm.value.expires_at) body.expires_at = createForm.value.expires_at
    const res = await API('/api/rag/api-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.message || data.error || '创建失败')
    newRawKey.value = data.key || ''
    await fetchKeys()
  } catch (e) {
    createErr.value = e.message
  } finally {
    creating.value = false
  }
}

function copyKey() {
  navigator.clipboard?.writeText(newRawKey.value).catch(() => {})
}

function startEdit(k) {
  editId.value = k.id
  editForm.value = {
    name: k.name,
    status: k.status,
    rate_limit_per_min: k.rate_limit_per_min || 60,
    expires_at: k.expires_at ? k.expires_at.slice(0, 10) : '',
  }
  editErr.value = ''
}

function cancelEdit() {
  editId.value = null
}

async function saveEdit(keyId) {
  editSaving.value = true
  editErr.value = ''
  try {
    const body = {
      name: editForm.value.name.trim(),
      status: editForm.value.status,
      rate_limit_per_min: Number(editForm.value.rate_limit_per_min) || 60,
    }
    if (editForm.value.expires_at) body.expires_at = editForm.value.expires_at
    const res = await API(`/api/rag/api-keys/${keyId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.message || data.error || '保存失败')
    editId.value = null
    await fetchKeys()
  } catch (e) {
    editErr.value = e.message
  } finally {
    editSaving.value = false
  }
}

async function deleteKey(k) {
  if (!confirm(`确认删除 API Key「${k.name}」？此操作不可恢复。`)) return
  err.value = ''
  const res = await API(`/api/rag/api-keys/${k.id}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    err.value = data.message || data.error || '删除失败'
    return
  }
  await fetchKeys()
}

function fmtDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleDateString('zh-CN')
}
</script>

<template>
  <div class="page rag-admin-page">
    <div class="page-header">
      <div class="title-block">
        <h2 class="page-title">API Key 管理</h2>
        <p class="page-subtitle">统一管理外部调用凭证、限速与有效期，页面铺满并保持简洁稳重。</p>
      </div>
      <button class="btn-primary" @click="openCreate">+ 新建 Key</button>
    </div>

    <div v-if="err" class="alert-err">{{ err }}</div>

    <!-- 新建弹窗 -->
    <div v-if="createOpen" class="modal-mask">
      <div class="modal">
        <div class="modal-header">
          <span>新建 API Key</span>
          <button class="btn-close" @click="closeCreate">✕</button>
        </div>
        <div class="modal-body">
          <template v-if="!newRawKey">
            <div class="field">
              <label>名称 *</label>
              <input v-model="createForm.name" class="input" placeholder="用途描述，便于识别" />
            </div>
            <div class="field">
              <label>每分钟限速</label>
              <input v-model.number="createForm.rate_limit_per_min" type="number" min="1" max="10000" class="input" />
            </div>
            <div class="field">
              <label>到期时间（可选）</label>
              <input v-model="createForm.expires_at" type="date" class="input" />
            </div>
            <div v-if="createErr" class="alert-err">{{ createErr }}</div>
          </template>
          <template v-else>
            <p class="key-notice">⚠️ 请立即复制此 Key，离开后将无法再次查看：</p>
            <div class="key-box">
              <code class="key-text">{{ newRawKey }}</code>
              <button class="btn-copy" @click="copyKey">复制</button>
            </div>
          </template>
        </div>
        <div class="modal-footer">
          <template v-if="!newRawKey">
            <button class="btn-secondary" @click="closeCreate">取消</button>
            <button class="btn-primary" :disabled="creating" @click="doCreate">
              {{ creating ? '创建中...' : '确认创建' }}
            </button>
          </template>
          <button v-else class="btn-primary" @click="closeCreate">已保存，关闭</button>
        </div>
      </div>
    </div>

    <!-- Key 列表 -->
    <div class="content-card">
      <div v-if="loading" class="hint">加载中...</div>
      <div v-else-if="!keys.length" class="hint hint-empty">暂无 API Key</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>前缀</th>
            <th>状态</th>
            <th>限速 / min</th>
            <th>到期时间</th>
            <th>最后使用</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="k in keys" :key="k.id">
            <tr v-if="editId !== k.id">
              <td>{{ k.name }}</td>
              <td><code class="prefix">{{ k.key_prefix }}…</code></td>
              <td>
                <span class="badge" :class="k.status === 'active' ? 'badge-ok' : 'badge-off'">
                  {{ statusLabels[k.status] || k.status }}
                </span>
              </td>
              <td>{{ k.rate_limit_per_min || k.rate_limit || '-' }}</td>
              <td>{{ fmtDate(k.expires_at) }}</td>
              <td>{{ fmtDate(k.last_used_at) }}</td>
              <td>{{ fmtDate(k.created_at) }}</td>
              <td class="actions">
                <button class="btn-sm" @click="startEdit(k)">编辑</button>
                <button class="btn-sm btn-danger" @click="deleteKey(k)">删除</button>
              </td>
            </tr>
            <tr v-else class="edit-row">
              <td>
                <input v-model="editForm.name" class="input-sm" placeholder="名称" />
              </td>
              <td><code class="prefix">{{ k.key_prefix }}…</code></td>
              <td>
                <select v-model="editForm.status" class="input-sm">
                  <option value="active">启用</option>
                  <option value="revoked">吊销</option>
                </select>
              </td>
              <td>
                <input v-model.number="editForm.rate_limit_per_min" type="number" min="1" class="input-sm" style="width:70px" />
              </td>
              <td>
                <input v-model="editForm.expires_at" type="date" class="input-sm" />
              </td>
              <td>{{ fmtDate(k.last_used_at) }}</td>
              <td>{{ fmtDate(k.created_at) }}</td>
              <td class="actions">
                <div v-if="editErr" class="err-inline">{{ editErr }}</div>
                <button class="btn-sm btn-ok" :disabled="editSaving" @click="saveEdit(k.id)">
                  {{ editSaving ? '保存中' : '保存' }}
                </button>
                <button class="btn-sm" @click="cancelEdit">取消</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
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
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.title-block { display: flex; flex-direction: column; gap: 6px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }
.page-subtitle { margin: 0; font-size: 13px; color: #64748b; }
.content-card { overflow: hidden; border: 1px solid rgba(226, 232, 240, 0.9); border-radius: 22px; background: rgba(255, 255, 255, 0.96); box-shadow: 0 18px 42px rgba(15, 23, 42, 0.06); }
.alert-err { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; padding: 10px 14px; border-radius: 12px; margin-bottom: 14px; font-size: 13px; }
.btn-primary { background: linear-gradient(135deg, #2563eb, #3b82f6); color: #fff; border: none; border-radius: 12px; padding: 10px 18px; font-size: 13px; cursor: pointer; font-weight: 600; box-shadow: 0 10px 24px rgba(37, 99, 235, 0.22); }
.btn-primary:hover:not(:disabled) { background: linear-gradient(135deg, #1d4ed8, #2563eb); }
.btn-primary:disabled { background: #93c5fd; cursor: not-allowed; box-shadow: none; }
.btn-secondary { background: #fff; color: #334155; border: 1px solid #cbd5e1; border-radius: 10px; padding: 9px 16px; font-size: 13px; cursor: pointer; }
.btn-secondary:hover { background: #f8fafc; }
.btn-sm { border: 1px solid #cbd5e1; background: #fff; color: #334155; border-radius: 10px; font-size: 12px; padding: 6px 10px; cursor: pointer; }
.btn-sm:hover:not(:disabled) { background: #eff6ff; }
.btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-danger { color: #dc2626; border-color: #fecaca; }
.btn-danger:hover:not(:disabled) { background: #fef2f2; }
.btn-ok { color: #16a34a; border-color: #bbf7d0; }
.btn-ok:hover:not(:disabled) { background: #f0fdf4; }
.btn-close { background: none; border: none; font-size: 16px; color: #64748b; cursor: pointer; line-height: 1; }
.btn-copy { margin-left: 8px; border: 1px solid #cbd5e1; background: #f8fafc; border-radius: 10px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
.hint { color: #94a3b8; font-size: 14px; padding: 54px 24px; text-align: center; }
.hint-empty { min-height: 220px; display: flex; align-items: center; justify-content: center; }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { text-align: left; padding: 14px 16px; border-bottom: 1px solid #e2e8f0; color: #64748b; font-weight: 700; white-space: nowrap; background: rgba(248, 250, 252, 0.9); }
.table td { padding: 14px 16px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
.table tr:hover td { background: #f8fbff; }
.edit-row td { background: #fffbeb; }
.prefix { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; background: #f1f5f9; padding: 3px 8px; border-radius: 999px; }
.badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; }
.badge-ok { background: #dcfce7; color: #16a34a; }
.badge-off { background: #f1f5f9; color: #64748b; }
.actions { display: flex; gap: 6px; align-items: center; white-space: nowrap; }
.err-inline { color: #dc2626; font-size: 11px; }
.input { width: 100%; box-sizing: border-box; border: 1px solid #dbe5f0; border-radius: 10px; padding: 9px 12px; font-size: 13px; outline: none; }
.input:focus, .input-sm:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
.input-sm { border: 1px solid #dbe5f0; border-radius: 10px; padding: 7px 10px; font-size: 12px; outline: none; width: 100%; box-sizing: border-box; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.36); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: #fff; border-radius: 22px; width: min(520px, calc(100vw - 32px)); box-shadow: 0 24px 60px rgba(0,0,0,0.18); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 18px 22px; border-bottom: 1px solid #f1f5f9; font-weight: 700; font-size: 15px; }
.modal-body { padding: 22px; display: flex; flex-direction: column; gap: 14px; }
.modal-footer { padding: 16px 22px; border-top: 1px solid #f1f5f9; display: flex; justify-content: flex-end; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 12px; color: #64748b; font-weight: 600; }
.key-notice { color: #b45309; font-size: 13px; background: #fffbeb; padding: 10px 12px; border-radius: 12px; border: 1px solid #fde68a; margin: 0; }
.key-box { display: flex; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px; padding: 12px 14px; }
.key-text { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; color: #1e293b; word-break: break-all; flex: 1; }
@media (max-width: 900px) {
  .page-header { flex-direction: column; align-items: stretch; }
  .actions { flex-wrap: wrap; }
}
</style>
