import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const projectEnvDir = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectEnvDir, 'VITE_')
  // Keep browser requests same-origin in development while allowing the proxy
  // target to be overridden if the local API port changes.
  const apiTarget = (env.VITE_API_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

  const base - env.VITE_BASE_PATH || '/'

  return {
    base,
    envDir: projectEnvDir,
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/health': { target: apiTarget, changeOrigin: true },
      },
    },
  }
})
