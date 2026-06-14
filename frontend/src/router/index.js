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
    { path: '/', redirect: '/dashboard' },
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
  ],
})

router.beforeEach((to) => {
  const loggedIn = !!localStorage.getItem('doctor_info')
  if (to.meta.requiresAuth === false) {
    if (loggedIn && to.name === 'login') return '/dashboard'
    return true
  }
  if (!loggedIn) return '/login'
  return true
})

export default router
