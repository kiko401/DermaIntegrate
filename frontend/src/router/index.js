import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    { path: '/', redirect: '/patients' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/Dashboard.vue'),
    },
    {
      path: '/patients',
      name: 'patients',
      component: () => import('../views/PatientList.vue'),
    },
    {
      path: '/integration',
      name: 'integration',
      component: () => import('../views/Integration.vue'),
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('../views/Tasks.vue'),
    },
    {
      path: '/tasks/:taskId',
      name: 'task-detail',
      component: () => import('../views/TaskDetail.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const loggedIn = !!localStorage.getItem('doctor_info')
  if (to.meta.requiresAuth === false) {
    if (loggedIn && to.name === 'login') return '/patients'
    return true
  }
  if (!loggedIn) return '/login'

  // cookie 有效性验证（仅首次，后续依赖 apiFetch 401 兜底）
  if (!router._cookieVerified) {
    try {
      const res = await fetch('/api/auth/me', { credentials: 'include' })
      if (res.status === 401) {
        localStorage.removeItem('doctor_info')
        return '/login'
      }
    } catch {}
    router._cookieVerified = true
  }

  return true
})

export default router
