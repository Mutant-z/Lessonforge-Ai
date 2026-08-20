import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  // Vite may be launched from the repository root, the frontend directory, or
  // launchd. Resolve the shared .env from this config file instead of cwd so
  // the API proxy always follows the backend port selected by start.sh.
  const env = loadEnv(mode, projectRoot, '')
  const frontendPort = parseInt(process.env.FRONTEND_PORT || env.FRONTEND_PORT || '5173', 10)
  const backendPort = process.env.BACKEND_PORT || env.BACKEND_PORT || '8000'
  const backendHost = process.env.BACKEND_HOST || env.BACKEND_HOST || '127.0.0.1'
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || `http://${backendHost === '0.0.0.0' ? '127.0.0.1' : backendHost}:${backendPort}`

  return {
    plugins: [vue()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
