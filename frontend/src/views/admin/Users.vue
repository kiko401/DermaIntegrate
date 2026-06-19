<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'

const users = ref([])
const loading = ref(true)

const addOpen = ref(false)
const addForm = ref({ name: '', username: '', password: '', role: 'doctor' })
const addLoading = ref(false)

const pwdOpen = ref(false)
const pwdTarget = ref(null)
const pwdValue = ref('')
const pwdLoading = ref(false)

onMounted(fetchUsers)

async function fetchUsers() {
  loading.value = true
  try {
    const res = await fetch('/api/admin/users', { credentials: 'include' })
    if (!res.ok) throw new Error('请求失败')
    users.value = await res.json()
  } catch (e) {
    message.error('加载账号列表失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function openAdd() {
  addForm.value = { name: '', username: '', password: '', role: 'doctor' }
  addOpen.value = true
}

async function submitAdd() {
  const { name, username, password, role } = addForm.value
  if (!name.trim() || !username.trim() || !password.trim()) {
    return message.warning('请填写所有必填项')
  }
  addLoading.value = true
  try {
    const res = await fetch('/api/admin/users', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, username, password, role }),
    })
    const data = await res.json()
    if (!res.ok) {
      if (data.error === 'USERNAME_EXISTS') return message.error('用户名已存在')
      throw new Error(data.error || '创建失败')
    }
    message.success('账号已创建')
    addOpen.value = false
    fetchUsers()
  } catch (e) {
    message.error(e.message)
  } finally {
    addLoading.value = false
  }
}

async function toggleActive(user) {
  try {
    const res = await fetch(`/api/admin/users/${user.id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !user.is_active }),
    })
    if (!res.ok) {
      const d = await res.json()
      if (d.error === 'SELF_MODIFY_FORBIDDEN') return message.error('不能修改自己的账号')
      throw new Error(d.error)
    }
    user.is_active = !user.is_active
    message.success(user.is_active ? '账号已启用' : '账号已禁用')
  } catch (e) {
    message.error(e.message)
  }
}

function openResetPwd(user) {
  pwdTarget.value = user
  pwdValue.value = ''
  pwdOpen.value = true
}

async function submitResetPwd() {
  if (!pwdValue.value || pwdValue.value.length < 6) {
    return message.warning('密码不能少于6位')
  }
  pwdLoading.value = true
  try {
    const res = await fetch(`/api/admin/users/${pwdTarget.value.id}/password`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwdValue.value }),
    })
    if (!res.ok) throw new Error((await res.json()).error)
    message.success('密码已重置')
    pwdOpen.value = false
  } catch (e) {
    message.error(e.message)
  } finally {
    pwdLoading.value = false
  }
}

async function deleteUser(user) {
  try {
    const res = await fetch(`/api/admin/users/${user.id}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    const data = await res.json()
    if (!res.ok) {
      if (data.error === 'SELF_MODIFY_FORBIDDEN') return message.error('不能删除自己的账号')
      if (data.error === 'LAST_ADMIN_FORBIDDEN') return message.error('至少保留一个管理员账号')
      throw new Error(data.error)
    }
    message.success('账号已删除')
    fetchUsers()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">医生账号管理</div>
    </div>

    <div class="toolbar">
      <span class="count">共 {{ users.length }} 个账号</span>
      <a-button size="small" type="primary" @click="openAdd">新增账号</a-button>
    </div>

    <div v-if="loading" class="state-msg">加载中...</div>
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>姓名</th>
            <th>用户名</th>
            <th>角色</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td class="mono">{{ u.id }}</td>
            <td>{{ u.name }}</td>
            <td class="mono">{{ u.username }}</td>
            <td>
              <span class="role-badge" :class="u.role">
                {{ u.role === 'admin' ? '管理员' : '医生' }}
              </span>
            </td>
            <td>
              <span class="status-badge" :class="u.is_active ? 'active' : 'inactive'">
                {{ u.is_active ? '启用' : '禁用' }}
              </span>
            </td>
            <td class="text-dim">{{ u.created_at ? u.created_at.slice(0, 10) : '—' }}</td>
            <td class="actions">
              <button class="btn-link" @click="toggleActive(u)">
                {{ u.is_active ? '禁用' : '启用' }}
              </button>
              <button class="btn-link" @click="openResetPwd(u)">重置密码</button>
              <a-popconfirm
                title="确认删除该账号？此操作不可恢复。"
                ok-text="删除"
                cancel-text="取消"
                @confirm="deleteUser(u)"
              >
                <button class="btn-link danger">删除</button>
              </a-popconfirm>
            </td>
          </tr>
          <tr v-if="!users.length">
            <td colspan="7" class="empty-row">暂无账号</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新增账号弹窗 -->
    <a-modal v-model:open="addOpen" title="新增账号" :footer="null" width="400">
      <div class="form-row">
        <label>姓名 *</label>
        <a-input v-model:value="addForm.name" placeholder="真实姓名" />
      </div>
      <div class="form-row">
        <label>用户名 *</label>
        <a-input v-model:value="addForm.username" placeholder="登录用户名" />
      </div>
      <div class="form-row">
        <label>初始密码 *</label>
        <a-input-password v-model:value="addForm.password" placeholder="至少6位" />
      </div>
      <div class="form-row">
        <label>角色</label>
        <a-select v-model:value="addForm.role" style="width:100%">
          <a-select-option value="doctor">医生</a-select-option>
          <a-select-option value="admin">管理员</a-select-option>
        </a-select>
      </div>
      <div class="form-footer">
        <a-button @click="addOpen = false">取消</a-button>
        <a-button type="primary" :loading="addLoading" style="margin-left:8px" @click="submitAdd">创建</a-button>
      </div>
    </a-modal>

    <!-- 重置密码弹窗 -->
    <a-modal v-model:open="pwdOpen" :title="`重置密码 — ${pwdTarget?.name}`" :footer="null" width="360">
      <div class="form-row">
        <label>新密码（至少6位）</label>
        <a-input-password v-model:value="pwdValue" placeholder="新密码" />
      </div>
      <div class="form-footer">
        <a-button @click="pwdOpen = false">取消</a-button>
        <a-button type="primary" :loading="pwdLoading" style="margin-left:8px" @click="submitResetPwd">确认重置</a-button>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; min-height: 100%; box-sizing: border-box; }
.page-header { margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 700; color: #0f172a; border-left: 3px solid #14b8a6; padding-left: 10px; }

.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.count { font-size: 13px; color: #64748b; }

.state-msg { padding: 40px; text-align: center; color: #94a3b8; }

.table-wrap { border: 1px solid #e8ecf2; border-radius: 10px; overflow: hidden; background: #fff; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { background: #f8fafc; color: #64748b; font-weight: 600; padding: 9px 14px; text-align: left; border-bottom: 1px solid #e8ecf2; }
.data-table td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; color: #475569; vertical-align: middle; }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: #f8fafc; }

.mono { font-family: monospace; font-size: 12px; }
.text-dim { color: #94a3b8; font-size: 12px; }

.role-badge { display: inline-block; padding: 2px 9px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.role-badge.admin  { background: #fef3c7; color: #d97706; }
.role-badge.doctor { background: #ecfdf5; color: #059669; }

.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.status-badge.active   { background: #dcfce7; color: #166534; }
.status-badge.inactive { background: #fee2e2; color: #991b1b; }

.actions { display: flex; gap: 10px; align-items: center; }
.btn-link { background: none; border: none; padding: 0; font-size: 12px; color: #2563eb; cursor: pointer; }
.btn-link:hover { text-decoration: underline; }
.btn-link.danger { color: #dc2626; }

.empty-row { text-align: center; color: #94a3b8; padding: 32px; }

.form-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 14px; }
.form-row label { font-size: 12px; color: #64748b; font-weight: 500; }
.form-footer { display: flex; justify-content: flex-end; padding-top: 4px; }
</style>
