<script setup>
import { computed } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import {
  AppstoreOutlined,
  TeamOutlined,
  ApiOutlined,
  FileSearchOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
const router = useRouter()

const isAuthPage = computed(() => route.meta.requiresAuth === false)

const navItems = [
  { path: '/dashboard', label: '工作台', icon: AppstoreOutlined },
  { path: '/patients', label: '患者管理', icon: TeamOutlined },
  { path: '/integration', label: '数据集成', icon: ApiOutlined },
  { path: '/tasks', label: 'AI 分析记录', icon: FileSearchOutlined },
]

const doctorInfo = computed(() => {
  try { return JSON.parse(localStorage.getItem('doctor_info') || '{}') } catch { return {} }
})

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
  localStorage.removeItem('doctor_info')
  router.push('/login')
}
</script>

<template>
  <RouterView v-if="isAuthPage" />
  <div v-else class="layout">
    <aside class="sidebar">
      <div class="sidebar-logo">
        <div class="logo-title">DermaIntegrate</div>
        <div class="logo-sub">皮肤病辅助诊断平台</div>
      </div>
      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          custom
          v-slot="{ isActive, navigate }"
        >
          <div class="nav-item" :class="{ active: isActive }" @click="navigate">
            <component :is="item.icon" class="nav-icon" />
            <span>{{ item.label }}</span>
          </div>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <div class="doctor-name">
          <span class="status-dot"></span>
          {{ doctorInfo.name || 'doctor' }}
        </div>
        <span class="logout-link" @click="logout">退出登录</span>
      </div>
    </aside>
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; min-height: 100vh; background: #f1f5f9; }

.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: #ffffff;
  border-right: 1px solid #e8ecf2;
  display: flex;
  flex-direction: column;
}
.sidebar-logo {
  padding: 22px 20px 16px;
  border-bottom: 1px solid #f0f4f8;
}
.logo-title { color: #1e293b; font-size: 14px; font-weight: 700; letter-spacing: 0.3px; }
.logo-sub { color: #94a3b8; font-size: 11px; margin-top: 3px; }

.sidebar-nav { flex: 1; padding: 10px; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  margin-bottom: 2px;
  border-radius: 8px;
  border-left: 3px solid transparent;
  cursor: pointer;
  font-size: 14px;
  color: #64748b;
  transition: all 0.15s;
}
.nav-item:hover { color: #334155; background: #f8fafc; }
.nav-item.active {
  color: #2563EB;
  background: #eff6ff;
  border-left-color: #2563EB;
  font-weight: 500;
}
.nav-icon { font-size: 15px; }

.sidebar-footer {
  padding: 14px 20px 18px;
  border-top: 1px solid #f0f4f8;
}
.doctor-name {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #475569;
  font-size: 13px;
  margin-bottom: 8px;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #14B8A6;
  flex-shrink: 0;
}
.logout-link {
  font-size: 12px;
  color: #94a3b8;
  cursor: pointer;
  transition: color 0.15s;
}
.logout-link:hover { color: #64748b; }

.main-content { flex: 1; min-width: 0; overflow: auto; }
</style>
