<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const doctorName = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('doctor_info') || '{}').name || ''
  } catch { return '' }
})

const navs = [
  { label: '临床视图', to: '/integration' },
  { label: 'AI 诊断记录', to: '/tasks' },
]

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
  localStorage.removeItem('doctor_info')
  router.push('/login')
}
</script>

<template>
  <div style="display:flex; align-items:center; justify-content:space-between; padding:0 24px; height:56px; background:#fff; border-bottom:1px solid #f0f0f0">
    <span style="font-size:16px; font-weight:600; color:#1a1a1a">DermaIntegrate</span>
    <a-space v-if="doctorName">
      <router-link v-for="(nav, i) in navs" :key="i" :to="nav.to"
        :style="{fontSize:'13px', color: route.path===nav.to ? '#1677ff' : '#595959', textDecoration:'none'}">
        {{ nav.label }}
      </router-link>
      <span style="font-size:13px; color:#595959">{{ doctorName }} 医生</span>
      <a-button size="small" @click="logout">退出</a-button>
    </a-space>
  </div>
</template>
