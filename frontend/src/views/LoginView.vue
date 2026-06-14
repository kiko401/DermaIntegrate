<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

const router = useRouter()
const formState = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: formState.username, password: formState.password }),
    })
    const data = await res.json()
    if (!res.ok) {
      error.value = data.error || '登录失败'
      return
    }
    localStorage.setItem('doctor_info', JSON.stringify(data.doctor))
    message.success(`欢迎，${data.doctor.name}`)
    router.push('/')
  } catch {
    error.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height:100vh; display:flex; align-items:center; justify-content:center; background:#f0f2f5">
    <a-card style="width:380px">
      <div style="text-align:center; margin-bottom:24px">
        <h2 style="margin:0 0 4px; font-size:20px">皮肤病辅助诊断工作站</h2>
        <p style="margin:0; color:#8c8c8c; font-size:13px">DermaIntegrate</p>
      </div>

      <a-alert v-if="error" type="error" :message="error" show-icon style="margin-bottom:16px" />

      <a-form :model="formState" layout="vertical" @finish="handleLogin">
        <a-form-item label="用户名" name="username">
          <a-input v-model:value="formState.username" placeholder="请输入用户名" allow-clear />
        </a-form-item>
        <a-form-item label="密码" name="password">
          <a-input-password v-model:value="formState.password" placeholder="请输入密码" />
        </a-form-item>
        <a-form-item style="margin-bottom:0">
          <a-button type="primary" html-type="submit" :loading="loading" block>
            登录
          </a-button>
        </a-form-item>
      </a-form>
    </a-card>
  </div>
</template>
