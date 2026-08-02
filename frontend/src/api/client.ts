import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('lessonforge_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401) {
    localStorage.removeItem('lessonforge_token')
    if (location.pathname !== '/' && location.pathname !== '/login') {
      const redirect = encodeURIComponent(location.pathname + location.search)
      location.href = `/login?redirect=${redirect}`
    }
  }
  return Promise.reject(error)
})

export const errorMessage = (error: any) => error.response?.data?.detail || error.message || '操作失败'
