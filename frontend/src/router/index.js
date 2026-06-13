import { createRouter, createWebHistory } from 'vue-router'
import PatientList from '../views/PatientList.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      name: 'patients',
      component: PatientList,
    },
    {
      path: '/patients/:id',
      name: 'visit-detail',
      component: () => import('../views/VisitDetail.vue'),
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('auth_token')
  if (to.meta.requiresAuth === false) {
    if (token && to.name === 'login') return '/'
    return true
  }
  if (!token) return '/login'
  return true
})

export default router
