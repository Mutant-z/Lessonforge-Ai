import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({plugins:[vue()],server:{port:5173,proxy:{'/api':{target:apiProxyTarget,changeOrigin:true}}}})
