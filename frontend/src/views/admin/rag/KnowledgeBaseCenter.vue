<script setup>
import { ref, computed, onMounted } from 'vue'

const API = (path, opts = {}) =>
  fetch(path, { credentials: 'include', ...opts }).then(r => r.json())

const kbs       = ref([])
const loading   = ref(false)
const showForm  = ref(false)
const editTarget = ref(null)

// 筛选
const filterName   = ref('')
const filterScope  = ref('')
const filterStatus = ref('')

const form = ref({ name: '', description: '', scope_type: 'personal' })

// 成员管理
const showMembers   = ref(false)
const memberTarget  = ref(null)
const members       = ref([])
const membersLoading = ref(false)
const allDoctors    = ref([])
const newMember     = ref({ doctor_id: '', permission: 'view' })

const permissionLabels = { view: '查看', edit: '编辑', manage: '管理' }

onMounted(fetchKbs)

async function fetchKbs() {
  loading.value = true
  const data = await API('/api/rag/kbs')
  kbs.value = Array.isArray(data) ? data : []
  loading.value = false
}

function openCreate() {
  editTarget.value = null
  form.value = { name: '', description: '', scope_type: 'personal' }
  showForm.value = true
}

function openEdit(kb) {
  editTarget.value = kb
  form.value = { name: kb.name, description: kb.description || '', scope_type: kb.scope_type }
  showForm.value = true
}

async function submitForm() {
  if (!form.value.name.trim()) return
  if (editTarget.value) {
    await API(`/api/rag/kbs/${editTarget.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
  } else {
    await API('/api/rag/kbs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
  }
  showForm.value = false
  await fetchKbs()
}

async function deleteKb(kb) {
  if (!confirm(`确认删除知识库「${kb.name}」？`)) return
  await API(`/api/rag/kbs/${kb.id}`, { method: 'DELETE' })
  await fetchKbs()
}

async function cloneKb(kb) {
  await API(`/api/rag/kbs/${kb.id}/clone`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: `${kb.name} (副本)` }),
  })
  await fetchKbs()
}

const scopeLabels = { public: '公共', department: '科室', personal: '个人' }

async function openMembers(kb) {
  memberTarget.value = kb
  showMembers.value = true
  newMember.value = { doctor_id: '', permission: 'view' }
  await Promise.all([fetchMembers(), fetchAllDoctors()])
}

async function fetchMembers() {
  membersLoading.value = true
  const data = await API(`/api/rag/kbs/${memberTarget.value.id}/members`)
  members.value = Array.isArray(data) ? data : []
  membersLoading.value = false
}

async function fetchAllDoctors() {
  if (allDoctors.value.length) return
  const data = await API('/api/admin/users')
  allDoctors.value = Array.isArray(data) ? data : []
}

async function addMember() {
  if (!newMember.value.doctor_id) return
  await API(`/api/rag/kbs/${memberTarget.value.id}/members`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(newMember.value),
  })
  newMember.value = { doctor_id: '', permission: 'view' }
  await fetchMembers()
}

async function updateMemberPermission(member, permission) {
  await API(`/api/rag/kbs/${memberTarget.value.id}/members/${member.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ permission }),
  })
  await fetchMembers()
}

async function removeMember(member) {
  if (!confirm(`确认移除成员「${member.doctor_name}」？`)) return
  await API(`/api/rag/kbs/${memberTarget.value.id}/members/${member.id}`, { method: 'DELETE' })
  await fetchMembers()
}

const availableDoctors = computed(() =>
  allDoctors.value.filter(d => !members.value.some(m => m.doctor_id === d.id))
)

const filteredKbs = computed(() => {
  return kbs.value.filter(kb => {
    if (filterName.value && !kb.name.includes(filterName.value)) return false
    if (filterScope.value && kb.scope_type !== filterScope.value) return false
    if (filterStatus.value && kb.status !== filterStatus.value) return false
    return true
  })
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">知识库管理</h2>
      <button class="btn-primary" @click="openCreate">+ 新建知识库</button>
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
    <div v-else-if="!filteredKbs.length" class="empty-tip">没有符合筛选条件的知识库</div>

    <div class="kb-grid">
      <div v-for="kb in filteredKbs" :key="kb.id" class="kb-card">
        <div class="kb-card-header">
          <span class="kb-name">{{ kb.name }}</span>
          <span class="scope-badge" :class="kb.scope_type">{{ scopeLabels[kb.scope_type] || kb.scope_type }}</span>
        </div>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-meta">
          <span>模型：{{ kb.default_model }}</span>
          <span>状态：{{ kb.status }}</span>
        </div>
        <div class="kb-actions">
          <button class="btn-sm" @click="openEdit(kb)">编辑</button>
          <button class="btn-sm" @click="openMembers(kb)">成员</button>
          <button class="btn-sm" @click="cloneKb(kb)">克隆</button>
          <button class="btn-sm btn-danger" @click="deleteKb(kb)">删除</button>
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

        <div class="modal-footer">
          <button class="btn-ghost" @click="showForm = false">取消</button>
          <button class="btn-primary" @click="submitForm">确定</button>
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
          <select v-model="newMember.permission" class="field-input">
            <option value="view">查看</option>
            <option value="edit">编辑</option>
            <option value="manage">管理</option>
          </select>
          <button class="btn-primary" @click="addMember">添加</button>
        </div>

        <div v-if="membersLoading" class="empty-tip">加载中...</div>
        <div v-else-if="!members.length" class="empty-tip">暂无成员</div>
        <table v-else class="member-table">
          <thead>
            <tr><th>姓名</th><th>用户名</th><th>权限</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="m in members" :key="m.id">
              <td>{{ m.doctor_name }}</td>
              <td>{{ m.username }}</td>
              <td>
                <select :value="m.permission" @change="updateMemberPermission(m, $event.target.value)" class="field-input field-input-sm">
                  <option value="view">查看</option>
                  <option value="edit">编辑</option>
                  <option value="manage">管理</option>
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
  </div>
</template>

<style scoped>
.page { padding: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
.page-title { font-size: 18px; font-weight: 700; color: #1e293b; margin: 0; }

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

.kb-desc { font-size: 13px; color: #64748b; margin: 0 0 12px; line-height: 1.5; }
.kb-meta { display: flex; gap: 16px; font-size: 12px; color: #94a3b8; margin-bottom: 14px; }
.kb-actions { display: flex; gap: 8px; }

.btn-primary { padding: 7px 16px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-primary:hover { background: #1d4ed8; }
.btn-ghost { padding: 7px 16px; background: none; border: 1px solid #e2e8f0; color: #475569; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-ghost:hover { background: #f8fafc; }
.btn-sm { padding: 4px 10px; font-size: 12px; border: 1px solid #e2e8f0; background: #fff; color: #475569; border-radius: 5px; cursor: pointer; }
.btn-sm:hover { background: #f8fafc; }
.btn-danger { border-color: #fecaca; color: #dc2626; }
.btn-danger:hover { background: #fef2f2; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 10px; padding: 24px; width: 420px; max-width: 90vw; }
.modal-title { font-size: 16px; font-weight: 700; color: #1e293b; margin: 0 0 20px; }
.field-label { display: block; font-size: 13px; font-weight: 500; color: #475569; margin-bottom: 6px; margin-top: 14px; }
.req { color: #dc2626; }
.field-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; box-sizing: border-box; }
.field-input:focus { outline: none; border-color: #2563eb; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }

.modal-wide { width: 560px; }
.member-add-row { display: flex; gap: 10px; margin-top: 8px; }
.member-add-row .field-input { margin: 0; }

.member-table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 13px; }
.member-table th { text-align: left; color: #94a3b8; font-weight: 500; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }
.member-table td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; color: #334155; }
.field-input-sm { padding: 4px 8px; font-size: 12px; width: auto; }
</style>
