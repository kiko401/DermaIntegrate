<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const doctorName = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('doctor_info') || '{}').name || ''
  } catch { return '' }
})

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
      <span style="font-size:13px; color:#595959">{{ doctorName }} 医生</span>
      <a-button size="small" @click="logout">退出</a-button>
    </a-space>
  </div>
</template>
