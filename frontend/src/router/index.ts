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
        { path: 'videos', component: () => import('../views/VideoCenterView.vue'), meta: protectedRoute },
        { path: 'videos/:courseId', component: () => import('../views/VideoWorkspaceView.vue'), meta: protectedRoute },
        { path: 'courses/new', component: () => import('../views/CourseIntakeView.vue'), meta: protectedRoute },
        { path: 'courses/:id/project', component: () => import('../views/ProjectOverviewView.vue'), meta: protectedRoute },
        { path: 'courses/:id/tasks/video_generation', redirect: to => `/videos/${to.params.id}`, meta: protectedRoute },
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

import { useAuthStore } from '../stores/auth'

router.beforeEach(async to => {
  const auth = useAuthStore()
  if (!auth.initialized) {
    await auth.restore()
  }
  // 恢复登录态期间服务器暂不可达（retryPending 为真）时，不要强制跳到登录页
  if (to.meta.requiresAuth && !auth.user && !auth.retryPending) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.user) {
    return '/'
  }
})

export default router
