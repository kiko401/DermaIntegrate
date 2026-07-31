<script setup>
import { ref, computed, watch, onMounted } from 'vue'

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, { credentials: 'include', ...opts })
  const data = res.headers.get('content-type')?.includes('application/json') ? await res.json() : null
  return { ok: res.ok, status: res.status, data }
}

const kbs        = ref([])
const loading    = ref(false)
const showForm   = ref(false)
const editTarget = ref(null)
const formError  = ref('')

const filterName   = ref('')
const filterScope  = ref('')
const filterStatus = ref('')

const form = ref({
  name: '', description: '', scope_type: 'personal',
  scope_owner_id: '', manager_doctor_id: '', default_model: '', status: 'active',
})

// 克隆弹层
const showCloneDialog = ref(false)
const cloneTarget     = ref(null)
const cloneForm       = ref({ new_name: '', include_documents: false, clone_permissions: true })
const cloneResult     = ref(null)
const cloneError      = ref('')

// 删除弹层
const showDeleteDialog = ref(false)
const deleteTarget     = ref(null)
const deleteMode       = ref('logical')
const deleteError      = ref('')

// 成员管理
const showMembers    = ref(false)
const memberTarget   = ref(null)
const members        = ref([])
const membersLoading = ref(false)
const allDoctors     = ref([])
const newMember      = ref({ doctor_id: '', role: 'viewer' })
const memberError    = ref('')

// 升级申请
const showUpgradeList    = ref(false)
const showUpgradeCreate  = ref(false)
const upgradeRequests    = ref([])
const upgradeLoading     = ref(false)
const upgradeForm        = ref({ source_kb_id: '', target_kb_id: '', doc_ids: '', reason: '' })
const upgradeError       = ref('')
const allKbs             = ref([]) // 供升级申请选择目标库

const roleLabels  = { viewer: '查看', uploader: '上传', manager: '管理' }
const scopeLabels = { public: '公共', department: '科室', personal: '个人' }

onMounted(fetchKbs)
watch([filterName, filterScope, filterStatus], fetchKbs)

async function fetchKbs() {
  loading.value = true
  const params = new URLSearchParams()
  if (filterName.value)   params.set('name', filterName.value)
  if (filterScope.value)  params.set('scope_type', filterScope.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  const qs = params.toString()
  const { data } = await apiFetch(`/api/rag/kbs${qs ? '?' + qs : ''}`)
  kbs.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  loading.value = false
}

function openCreate() {
  editTarget.value = null
  form.value = { name: '', description: '', scope_type: 'personal', scope_owner_id: '', manager_doctor_id: '', default_model: '', status: 'active' }
  formError.value = ''
  showForm.value = true
}

function openEdit(kb) {
  editTarget.value = kb
  form.value = {
    name: kb.name, description: kb.description || '', scope_type: kb.scope_type,
    scope_owner_id: kb.scope_owner_id || '', manager_doctor_id: kb.manager_doctor_id || '',
    default_model: kb.default_model || '', status: kb.status || 'active',
  }
  formError.value = ''
  showForm.value = true
}

async function submitForm() {
  if (!form.value.name.trim()) { formError.value = '名称不能为空'; return }
  formError.value = ''
  const payload = {
    name: form.value.name,
    description: form.value.description,
    scope_type: form.value.scope_type,
  }
  if (form.value.default_model) payload.default_model = form.value.default_model
  if (form.value.manager_doctor_id) payload.manager_doctor_id = Number(form.value.manager_doctor_id)
  if (form.value.scope_type === 'department' && form.value.scope_owner_id)
    payload.scope_owner_id = Number(form.value.scope_owner_id)
  if (editTarget.value) {
    payload.status = form.value.status
    const { ok, status, data } = await apiFetch(`/api/rag/kbs/${editTarget.value.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    if (!ok) { formError.value = data?.message || `操作失败（${status}）`; return }
  } else {
    const { ok, status, data } = await apiFetch('/api/rag/kbs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    if (!ok) {
      if (status === 409) { formError.value = '知识库名称已存在'; return }
      formError.value = data?.message || `操作失败（${status}）`; return
    }
  }
  showForm.value = false
  await fetchKbs()
}

function openDelete(kb) {
  deleteTarget.value = kb
  deleteMode.value = 'logical'
  deleteError.value = ''
  showDeleteDialog.value = true
}

async function confirmDelete() {
  deleteError.value = ''
  const res = await fetch(
    `/api/rag/kbs/${deleteTarget.value.id}?mode=${deleteMode.value}`,
    { method: 'DELETE', credentials: 'include' }
  )
  if (res.status === 409) {
    const data = await res.json().catch(() => ({}))
    const msgMap = {
      KB_HAS_ACTIVE_TASKS: '存在进行中的任务，请等待完成后再删除',
      KB_HAS_DOCUMENTS: '知识库内还有文档，请先删除文档',
      KB_HAS_CONVERSATIONS: '知识库存在关联会话，请先清理会话',
    }
    deleteError.value = msgMap[data?.error] || '删除失败，存在关联数据'
    return
  }
  if (!res.ok) { deleteError.value = `删除失败（${res.status}）`; return }
  showDeleteDialog.value = false
  await fetchKbs()
}

function openClone(kb) {
  cloneTarget.value = kb
  cloneForm.value = { new_name: `${kb.name} (副本)`, include_documents: false, clone_permissions: true }
  cloneResult.value = null
  cloneError.value = ''
  showCloneDialog.value = true
}

async function submitClone() {
  if (!cloneForm.value.new_name.trim()) { cloneError.value = '新知识库名称不能为空'; return }
  cloneError.value = ''
  const { ok, status, data } = await apiFetch(`/api/rag/kbs/${cloneTarget.value.id}/clone`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cloneForm.value),
  })
  if (!ok) { cloneError.value = data?.message || `克隆失败（${status}）`; return }
  cloneResult.value = data?.clone_result || null
  showCloneDialog.value = false
  await fetchKbs()
}

async function openMembers(kb) {
  memberTarget.value = kb
  memberError.value = ''
  showMembers.value = true
  newMember.value = { doctor_id: '', role: 'viewer' }
  await Promise.all([fetchMembers(), fetchAllDoctors()])
}

async function fetchMembers() {
  membersLoading.value = true
  const { data } = await apiFetch(`/api/rag/kbs/${memberTarget.value.id}/members`)
  members.value = Array.isArray(data?.data) ? data.data : (Array.isArray(data) ? data : [])
  membersLoading.value = false
}

async function fetchAllDoctors() {
  if (allDoctors.value.length) return
  const { data } = await apiFetch('/api/admin/users')
  allDoctors.value = Array.isArray(data) ? data : []
}

async function addMember() {
  if (!newMember.value.doctor_id) return
  memberError.value = ''
  const { ok, status, data } = await apiFetch(`/api/rag/kbs/${memberTarget.value.id}/members`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newMember.value),
  })
  if (!ok) {
    if (status === 409) { memberError.value = '该用户已是成员'; return }
    if (status === 403) { memberError.value = '无操作权限'; return }
    memberError.value = data?.message || `操作失败（${status}）`; return
  }
  newMember.value = { doctor_id: '', role: 'viewer' }
  await fetchMembers()
}

async function updateMemberRole(member, role) {
  await apiFetch(`/api/rag/kbs/${memberTarget.value.id}/members/${member.id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }),
  })
  await fetchMembers()
}

async function removeMember(member) {
  if (!confirm(`确认移除成员「${member.doctor_name}」？`)) return
  await fetch(`/api/rag/kbs/${memberTarget.value.id}/members/${member.id}`, {
    method: 'DELETE', credentials: 'include',
  })
  await fetchMembers()
}

// 升级申请
async function openUpgradeList() {
  upgradeLoading.value = true
  showUpgradeList.value = true
  const { data } = await apiFetch('/api/rag/kbs/upgrade-requests')
  upgradeRequests.value = Array.isArray(data?.data) ? data.data : []
  upgradeLoading.value = false
}

function openUpgradeCreate(kb) {
  upgradeForm.value = { source_kb_id: kb ? kb.id : '', target_kb_id: '', doc_ids: '', reason: '' }
  upgradeError.value = ''
  allKbs.value = kbs.value
  showUpgradeCreate.value = true
}

async function submitUpgradeRequest() {
  if (!upgradeForm.value.source_kb_id || !upgradeForm.value.target_kb_id) {
    upgradeError.value = '请选择来源知识库和目标知识库'; return
  }
  upgradeError.value = ''
  const payload = {
    source_kb_id: Number(upgradeForm.value.source_kb_id),
    target_kb_id: Number(upgradeForm.value.target_kb_id),
    doc_ids: upgradeForm.value.doc_ids
      ? upgradeForm.value.doc_ids.split(',').map(s => Number(s.trim())).filter(n => Number.isInteger(n) && n > 0)
      : [],
    reason: upgradeForm.value.reason,
  }
  const { ok, status, data } = await apiFetch('/api/rag/kbs/upgrade-requests', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!ok) { upgradeError.value = data?.message || `提交失败（${status}）`; return }
  showUpgradeCreate.value = false
  alert('申请已提交，等待管理员审批')
}

async function reviewRequest(req, action) {
  const comment = action === 'reject' ? prompt('请输入拒绝原因（可选）') : null
  if (action === 'reject' && comment === null) return // 用户取消
  const { ok, status, data } = await apiFetch(`/api/rag/kbs/upgrade-requests/${req.id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, review_comment: comment || '' }),
  })
  if (!ok) { alert(data?.message || `操作失败（${status}）`); return }
  if (status === 207) {
    alert(`审批已完成，但 AI 域向量克隆失败：${data?.message || '请在文档管理中手动触发重建索引'}`)
  }
  await openUpgradeList()
}

const availableDoctors = computed(() =>
  allDoctors.value.filter(d => !members.value.some(m => m.doctor_id === d.id))
)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">知识库管理</h2>
      <div class="header-actions">
        <button class="btn-ghost" @click="openUpgradeList">升级申请</button>
        <button class="btn-primary" @click="openCreate">+ 新建知识库</button>
      </div>
    </div>

    <div class="filter-bar">
      <input v-model="filterName" class="field-input field-input-sm" placeholder="按名称搜索" />
      <select v-model="filterScope" class="field-input field-input-sm">
        <option value="">全部类型</option>
        <option value="personal">个人</option>
        <option value="department">科室</option>
        <option value="public">公共</option>
      </select>
      <select v-model="filterStatus" class="field-input field-input-sm">
        <option value="">全部状态</option>
        <option value="active">启用</option>
        <option value="disabled">停用</option>
      </select>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <div v-else-if="!kbs.length" class="empty-tip">暂无知识库，点击「新建知识库」创建第一个</div>

    <div class="kb-grid">
      <div v-for="kb in kbs" :key="kb.id" class="kb-card">
        <div class="kb-card-header">
          <span class="kb-name">{{ kb.name }}</span>
          <span class="scope-badge" :class="kb.scope_type">{{ scopeLabels[kb.scope_type] || kb.scope_type }}</span>
        </div>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-meta">
          <span>文档：{{ kb.doc_count ?? 0 }}</span>
          <span>模型：{{ kb.default_model || '默认' }}</span>
          <span class="status-tag" :class="kb.status">{{ kb.status === 'active' ? '启用' : '停用' }}</span>
        </div>
        <div class="kb-actions">
          <button class="btn-sm" @click="openEdit(kb)">编辑</button>
          <button class="btn-sm" @click="openMembers(kb)">成员</button>
          <button class="btn-sm" @click="openClone(kb)">克隆</button>
          <button class="btn-sm" @click="openUpgradeCreate(kb)">升级申请</button>
          <button class="btn-sm btn-danger" @click="openDelete(kb)">删除</button>
        </div>
      </div>
    </div>

    <!-- 创建/编辑表单弹层 -->
    <div v-if="showForm" class="modal-overlay" @click.self="showForm = false">
      <div class="modal">
        <h3 class="modal-title">{{ editTarget ? '编辑知识库' : '新建知识库' }}</h3>

        <label class="field-label">名称 <span class="req">*</span></label>
        <input v-model="form.name" class="field-input" placeholder="知识库名称" />

        <label class="field-label">描述</label>
        <textarea v-model="form.description" class="field-input" rows="2" placeholder="可选" />

        <label class="field-label">类型</label>
        <select v-model="form.scope_type" class="field-input">
          <option value="personal">个人</option>
          <option value="department">科室</option>
          <option value="public">公共</option>
        </select>

        <div v-if="form.scope_type === 'department'">
          <label class="field-label">所属科室 ID</label>
          <input v-model="form.scope_owner_id" class="field-input" placeholder="科室 ID" type="number" />
        </div>

        <label class="field-label">默认模型</label>
        <input v-model="form.default_model" class="field-input" placeholder="可选，留空使用全局默认" />

        <label class="field-label">管理医生 ID</label>
        <input v-model="form.manager_doctor_id" class="field-input" placeholder="可选，留空默认为当前用户" type="number" />

        <div v-if="editTarget">
          <label class="field-label">状态</label>
          <select v-model="form.status" class="field-input">
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </select>
        </div>

        <p v-if="formError" class="error-tip">{{ formError }}</p>
        <div class="modal-footer">
          <button class="btn-ghost" @click="showForm = false">取消</button>
          <button class="btn-primary" @click="submitForm">确定</button>
        </div>
      </div>
    </div>

    <!-- 删除弹层 -->
    <div v-if="showDeleteDialog" class="modal-overlay" @click.self="showDeleteDialog = false">
      <div class="modal">
        <h3 class="modal-title">删除知识库</h3>
        <p class="modal-desc">即将删除「<strong>{{ deleteTarget?.name }}</strong>」，此操作不可撤销。</p>
        <label class="field-label">删除模式</label>
        <select v-model="deleteMode" class="field-input">
          <option value="logical">逻辑删除（保留向量索引）</option>
          <option value="physical">物理删除（同步清除向量索引）</option>
        </select>
        <p v-if="deleteError" class="error-tip">{{ deleteError }}</p>
        <div class="modal-footer">
          <button class="btn-ghost" @click="showDeleteDialog = false">取消</button>
          <button class="btn-primary btn-danger-solid" @click="confirmDelete">确认删除</button>
        </div>
      </div>
    </div>

    <!-- 克隆弹层 -->
    <div v-if="showCloneDialog" class="modal-overlay" @click.self="showCloneDialog = false">
      <div class="modal">
        <h3 class="modal-title">克隆知识库 — {{ cloneTarget?.name }}</h3>
        <label class="field-label">新知识库名称 <span class="req">*</span></label>
        <input v-model="cloneForm.new_name" class="field-input" placeholder="新知识库名称" />
        <div class="checkbox-row">
          <input type="checkbox" id="includeDocuments" v-model="cloneForm.include_documents" />
          <label for="includeDocuments">同时克隆文档（含向量索引）</label>
        </div>
        <div class="checkbox-row">
          <input type="checkbox" id="clonePermissions" v-model="cloneForm.clone_permissions" />
          <label for="clonePermissions">复制成员权限</label>
        </div>
        <div v-if="cloneResult" class="clone-result">
          <p>克隆完成：共复制 {{ cloneResult.cloned_chunk_count ?? 0 }} 个向量块，涉及 {{ cloneResult.cloned_doc_ids?.length ?? 0 }} 个文档</p>
        </div>
        <p v-if="cloneError" class="error-tip">{{ cloneError }}</p>
        <div class="modal-footer">
          <button class="btn-ghost" @click="showCloneDialog = false">关闭</button>
          <button v-if="!cloneResult" class="btn-primary" @click="submitClone">确认克隆</button>
        </div>
      </div>
    </div>

    <!-- 成员管理弹层 -->
    <div v-if="showMembers" class="modal-overlay" @click.self="showMembers = false">
      <div class="modal modal-wide">
        <h3 class="modal-title">成员管理 — {{ memberTarget?.name }}</h3>

        <div class="member-add-row">
          <select v-model="newMember.doctor_id" class="field-input">
            <option value="">选择医生</option>
            <option v-for="d in availableDoctors" :key="d.id" :value="d.id">{{ d.name }}（{{ d.username }}）</option>
          </select>
          <select v-model="newMember.role" class="field-input">
            <option value="viewer">查看</option>
            <option value="uploader">上传</option>
            <option value="manager">管理</option>
          </select>
          <button class="btn-primary" @click="addMember">添加</button>
        </div>
        <p v-if="memberError" class="error-tip">{{ memberError }}</p>

        <div v-if="membersLoading" class="empty-tip">加载中...</div>
        <div v-else-if="!members.length" class="empty-tip">暂无成员</div>
        <table v-else class="member-table">
          <thead>
            <tr><th>姓名</th><th>用户名</th><th>角色</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="m in members" :key="m.id">
              <td>{{ m.doctor_name }}</td>
              <td>{{ m.username }}</td>
              <td>
                <select :value="m.role" @change="updateMemberRole(m, $event.target.value)" class="field-input field-input-sm">
                  <option value="viewer">查看</option>
                  <option value="uploader">上传</option>
                  <option value="manager">管理</option>
                </select>
              </td>
              <td><button class="btn-sm btn-danger" @click="removeMember(m)">移除</button></td>
            </tr>
          </tbody>
        </table>

        <div class="modal-footer">
          <button class="btn-ghost" @click="showMembers = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 升级申请列表弹层 -->
    <div v-if="showUpgradeList" class="modal-overlay" @click.self="showUpgradeList = false">
      <div class="modal modal-wide">
        <h3 class="modal-title">升级申请列表</h3>
        <div v-if="upgradeLoading" class="empty-tip">加载中...</div>
        <div v-else-if="!upgradeRequests.length" class="empty-tip">暂无申请</div>
        <table v-else class="member-table">
          <thead>
            <tr><th>申请人</th><th>来源库</th><th>目标库</th><th>状态</th><th>原因</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="req in upgradeRequests" :key="req.id">
              <td>{{ req.applicant_name }}</td>
              <td>{{ req.source_kb_id }}</td>
              <td>{{ req.target_kb_id }}</td>
              <td>{{ req.status }}</td>
              <td>{{ req.reason || '-' }}</td>
              <td>
                <template v-if="req.status === 'pending'">
                  <button class="btn-sm" @click="reviewRequest(req, 'approve')">批准</button>
                  <button class="btn-sm btn-danger" @click="reviewRequest(req, 'reject')">拒绝</button>
                </template>
                <span v-else class="text-muted">已处理</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="modal-footer">
          <button class="btn-ghost" @click="showUpgradeList = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 升级申请创建弹层 -->
    <div v-if="showUpgradeCreate" class="modal-overlay" @click.self="showUpgradeCreate = false">
      <div class="modal">
        <h3 class="modal-title">提交升级申请</h3>

        <label class="field-label">来源知识库 <span class="req">*</span></label>
        <select v-model="upgradeForm.source_kb_id" class="field-input">
          <option value="">请选择</option>
          <option v-for="kb in allKbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
        </select>

        <label class="field-label">目标知识库 <span class="req">*</span></label>
        <select v-model="upgradeForm.target_kb_id" class="field-input">
          <option value="">请选择</option>
          <option v-for="kb in allKbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
        </select>

        <label class="field-label">文档 ID（逗号分隔，可选）</label>
        <input v-model="upgradeForm.doc_ids" class="field-input" placeholder="如：1,2,3" />

        <label class="field-label">申请原因</label>
        <textarea v-model="upgradeForm.reason" class="field-input" rows="2" placeholder="可选" />

        <p v-if="upgradeError" class="error-tip">{{ upgradeError }}</p>
        <div class="modal-footer">
          <button class="btn-ghost" @click="showUpgradeCreate = false">取消</button>
          <button class="btn-primary" @click="submitUpgradeRequest">提交</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }
.header-actions { display: flex; gap: 10px; }

.empty-tip { text-align: center; padding: 60px; color: #94a3b8; font-size: 14px; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; }
.filter-bar .field-input { width: auto; min-width: 160px; }

.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }

.kb-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; }
.kb-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.kb-name { font-size: 15px; font-weight: 600; color: #1e293b; }
.scope-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.scope-badge.public { background: #fef3c7; color: #92400e; }
.scope-badge.department { background: #e0f2fe; color: #0369a1; }
.scope-badge.personal { background: #f0fdf4; color: #166534; }

.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-tag.active { background: #dcfce7; color: #166534; }
.status-tag.disabled { background: #f1f5f9; color: #94a3b8; }

.kb-desc { font-size: 13px; color: #64748b; margin: 0 0 12px; line-height: 1.5; }
.kb-meta { display: flex; gap: 12px; font-size: 12px; color: #94a3b8; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
.kb-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-primary:hover { background: #1d4ed8; }
.btn-ghost { padding: 7px 16px; background: none; border: 1px solid #e2e8f0; color: #475569; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-ghost:hover { background: #f8fafc; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; }
.btn-sm:hover { background: #f8fafc; }
.btn-danger { border-color: #fecaca; color: #dc2626; }
.btn-danger:hover { background: #fef2f2; }
.btn-danger-solid { background: #dc2626; color: #fff; border-color: #dc2626; }
.btn-danger-solid:hover { background: #b91c1c; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 10px; padding: 24px; width: 420px; max-width: 90vw; max-height: 90vh; overflow-y: auto; }
.modal-title { font-size: 16px; font-weight: 700; color: #1e293b; margin: 0 0 20px; }
.modal-desc { font-size: 14px; color: #475569; margin-bottom: 16px; }
.field-label { display: block; font-size: 13px; font-weight: 500; color: #475569; margin-bottom: 6px; margin-top: 14px; }
.req { color: #dc2626; }
.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }

.error-tip { color: #dc2626; font-size: 13px; margin-top: 8px; }
.clone-result { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 10px 14px; font-size: 13px; color: #166534; margin-top: 14px; }
.text-muted { color: #94a3b8; font-size: 12px; }

.checkbox-row { display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 13px; color: #475569; }
.checkbox-row input { width: auto; }

.modal-wide { width: 680px; }
.member-add-row { display: flex; gap: 10px; margin-top: 8px; }
.member-add-row .field-input { margin: 0; }

.member-table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 13px; }
.member-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }
.member-table td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; color: #334155; }
.field-input-sm { padding: 4px 8px; font-size: 12px; width: auto; }
</style>
