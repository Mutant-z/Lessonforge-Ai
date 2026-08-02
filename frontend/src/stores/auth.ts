import { defineStore } from 'pinia'
import { api } from '../api/client'

interface CurrentUser { id: string; username: string; role: string }

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null as CurrentUser | null, initialized: false }),
  actions: {
    async restore() {
      if (!localStorage.getItem('lessonforge_token')) {
        this.user = null
        this.initialized = true
        return
      }
      try { await this.me() }
      catch {
        localStorage.removeItem('lessonforge_token')
        this.user = null
      } finally { this.initialized = true }
    },
    async login(username: string, password: string) {
      const form = new URLSearchParams({ username, password })
      const { data } = await api.post('/auth/login', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
      localStorage.setItem('lessonforge_token', data.access_token)
      await this.me()
      this.initialized = true
    },
    async register(username: string, password: string, email?: string) {
      await api.post('/auth/register', { username, password, email: email || null })
      await this.login(username, password)
    },
    async me() {
      const { data } = await api.get('/auth/me')
      this.user = data
    },
    logout() {
      localStorage.removeItem('lessonforge_token')
      this.user = null
      location.href = '/'
    },
  },
})
