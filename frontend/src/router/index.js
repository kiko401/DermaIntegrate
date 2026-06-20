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
      path: '/patients',
      name: 'patients',
      component: () => import('../views/PatientList.vue'),
    },
    {
      path: '/clinical/:patientId',
      name: 'clinical',
      component: () => import('../views/ClinicalView.vue'),
    },
    {
      path: '/tasks/:taskId',
      name: 'task-detail',
      component: () => import('../views/TaskDetail.vue'),
    },
    {
      path: '/admin/patients',
      name: 'admin-patients',
      component: () => import('../views/admin/PatientAdmin.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/admin/tasks',
      name: 'admin-tasks',
      component: () => import('../views/admin/Tasks.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/admin/integration',
      name: 'admin-integration',
      component: () => import('../views/admin/Integration.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('../views/admin/Users.vue'),
      meta: { requiresAdmin: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const loggedIn = !!localStorage.getItem('doctor_info')

  if (to.meta.requiresAuth === false) {
    if (loggedIn && to.name === 'login') {
      const info = JSON.parse(localStorage.getItem('doctor_info') || '{}')
      return info.role === 'admin' ? '/admin/patients' : '/patients'
    }
    return true
  }

  if (!loggedIn) return '/login'

  const info = JSON.parse(localStorage.getItem('doctor_info') || '{}')
  const isAdmin = info.role === 'admin'

  if (to.meta.requiresAdmin && !isAdmin) return '/patients'

  // 临床视图和患者列表仅医生可访问，admin 跳转到自己的患者管理页
  const doctorOnlyRoutes = ['patients', 'clinical', 'task-detail']
  if (doctorOnlyRoutes.includes(to.name) && isAdmin) return '/admin/patients'

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
