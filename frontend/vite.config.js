import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式下 Vite 起在 5173 端口，/api 请求代理到 FastAPI（5000）。
// 生产构建（npm run build）产物输出到 dist/，由 FastAPI 直接托管，无需 Node。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },
})
