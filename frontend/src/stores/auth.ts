import { defineStore } from 'pinia'
import { api, getToken, clearToken } from '../api/client'

interface CurrentUser { id: string; username: string; role: string }

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as CurrentUser | null,
    initialized: false,
    retryPending: false,
  }),
  actions: {
    async restore() {
      if (!getToken()) {
        this.user = null
        this.retryPending = false
        this.initialized = true
        return
      }
      // 后端可能正处于重启启动中，短暂失联不应触发强制登出。
      // 带退避地重试 /auth/me，直到服务器恢复、或确认 Token 已失效。
      const delays = [0, 500, 1000, 1500, 2000, 2500, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000]
      for (const delay of delays) {
        if (delay > 0) {
          await new Promise(r => setTimeout(r, delay))
        }
        try {
          await this.me()
          this.retryPending = false
          this.initialized = true
          return
        } catch (err: any) {
          // 明确收到 401 才判定会话失效，清除 Token
          if (err?.response?.status === 401) {
            clearToken()
            this.user = null
            this.retryPending = false
            this.initialized = true
            return
          }
          // 其余错误（网络断开 / 服务器未就绪 / 5xx）保留 Token 继续重试
          console.warn('恢复登录态中服务器未响应，稍后重试', err)
        }
      }
      // 重试耗尽后服务器仍不可达：保留 Token，进入离线待重试状态
      this.user = null
      this.retryPending = true
      this.initialized = true
    },
    async login(username: string, password: string, rememberMe = true) {
      const form = new URLSearchParams({ 
        username, 
        password,
        remember_me: rememberMe ? 'true' : 'false'
      })
      const { data } = await api.post('/auth/login', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
      
      clearToken()
      if (rememberMe) {
        localStorage.setItem('lessonforge_token', data.access_token)
      } else {
        sessionStorage.setItem('lessonforge_token', data.access_token)
      }
      await this.me()
      this.initialized = true
    },
    async register(username: string, password: string, email?: string) {
      await api.post('/auth/register', { username, password, email: email || null })
      await this.login(username, password, true)
    },
    async me() {
      const { data } = await api.get('/auth/me')
      this.user = data
    },
    logout() {
      clearToken()
      this.user = null
      location.href = '/'
    },
  },
})
