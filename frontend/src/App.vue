<script setup>
import { computed, ref, watch } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const isAuthPage = computed(() => route.meta.requiresAuth === false)

function getDoctorInfo() {
  try { return JSON.parse(localStorage.getItem('doctor_info') || '{}') } catch { return {} }
}
const doctorInfo = ref(getDoctorInfo())
watch(() => route.path, () => { doctorInfo.value = getDoctorInfo() })

const isAdmin = computed(() => doctorInfo.value.role === 'admin')

const doctorNavItems = [
  { path: '/patients', label: '患者管理' },
]
const adminNavItems = [
  { path: '/admin/patients',    label: '患者管理' },
  { path: '/admin/tasks',       label: '任务监控' },
  { path: '/admin/integration', label: '数据集成' },
  { path: '/admin/users',       label: '用户管理' },
]

const navItems = computed(() => isAdmin.value ? adminNavItems : doctorNavItems)

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
  localStorage.removeItem('doctor_info')
  router.push('/login')
}
</script>

<template>
  <RouterView v-if="isAuthPage" />
  <div v-else class="layout">
    <header class="topbar">
      <div class="topbar-brand">
        <span class="brand-title">DermaIntegrate</span>
        <span class="brand-sub">皮肤病辅助诊断平台</span>
      </div>
      <nav class="topbar-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          custom
          v-slot="{ isActive, navigate }"
        >
          <span class="nav-link" :class="{ active: isActive }" @click="navigate">
            {{ item.label }}
          </span>
        </RouterLink>
      </nav>
      <div class="topbar-user">
        <span class="user-name">{{ doctorInfo.name || '—' }}</span>
        <span v-if="isAdmin" class="role-badge">管理员</span>
        <span class="logout-btn" @click="logout">退出</span>
      </div>
    </header>
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; flex-direction: column; min-height: 100vh; background: #f1f5f9; }

.topbar {
  display: flex;
  align-items: center;
  height: 52px;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid #e8ecf2;
  flex-shrink: 0;
  gap: 32px;
}

.topbar-brand { display: flex; align-items: baseline; gap: 8px; }
.brand-title { font-size: 15px; font-weight: 700; color: #1e293b; white-space: nowrap; }
.brand-sub { font-size: 11px; color: #94a3b8; white-space: nowrap; }

.topbar-nav { display: flex; align-items: center; gap: 4px; flex: 1; }
.nav-link {
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 14px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.nav-link:hover { color: #334155; background: #f8fafc; }
.nav-link.active { color: #2563eb; background: #eff6ff; font-weight: 500; }

.topbar-user { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.user-name { font-size: 13px; color: #475569; }
.role-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: #fef3c7;
  color: #92400e;
}
.logout-btn {
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  transition: color 0.15s;
}
.logout-btn:hover { color: #64748b; }

.main-content { flex: 1; min-width: 0; overflow: auto; }
</style>
