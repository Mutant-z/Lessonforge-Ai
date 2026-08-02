import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import AppLayout from '../layouts/AppLayout.vue'

const protectedRoute = { requiresAuth: true }

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    {
      path: '/', component: AppLayout, children: [
        { path: '', component: () => import('../views/DashboardView.vue') },
        { path: 'courses/new', component: () => import('../views/CourseIntakeView.vue'), meta: protectedRoute },
        { path: 'courses/:id/project', component: () => import('../views/ProjectOverviewView.vue'), meta: protectedRoute },
        { path: 'courses/:id/tasks/:taskType', component: () => import('../views/TaskWorkspaceView.vue'), meta: protectedRoute },
        { path: 'courses/:id/blueprint', redirect: to => `/courses/${to.params.id}/project`, meta: protectedRoute },
        { path: 'courses/:id/generation/:runId', redirect: to => `/courses/${to.params.id}/project`, meta: protectedRoute },
        { path: 'courses/:id/workspace', redirect: to => `/courses/${to.params.id}/tasks/${String(to.query.module || 'lesson_plan')}`, meta: protectedRoute },
        { path: 'courses/:id/export', component: () => import('../views/ExportView.vue'), meta: protectedRoute },
        { path: 'settings', component: () => import('../views/SettingsView.vue'), meta: protectedRoute },
      ],
    },
  ],
})

router.beforeEach(to => {
  const hasToken = Boolean(localStorage.getItem('lessonforge_token'))
  if (to.meta.requiresAuth && !hasToken) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && hasToken) return '/'
})

export default router
