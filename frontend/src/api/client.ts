import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

export function getToken(): string | null {
  return localStorage.getItem('lessonforge_token') || sessionStorage.getItem('lessonforge_token')
}

export function clearToken(): void {
  localStorage.removeItem('lessonforge_token')
  sessionStorage.removeItem('lessonforge_token')
}

api.interceptors.request.use(config => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Request-ID'] = crypto.randomUUID()
  if (config.method?.toLowerCase() === 'get') {
    config.headers['Cache-Control'] = 'no-cache'
    config.headers.Pragma = 'no-cache'
  }
  return config
})

api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401) {
    clearToken()
    if (location.pathname !== '/' && location.pathname !== '/login') {
      const redirect = encodeURIComponent(location.pathname + location.search)
      location.href = `/login?redirect=${redirect}`
    }
  }
  return Promise.reject(error)
})

export const errorMessage = (error: any) => error.response?.data?.detail || error.message || '操作失败'
