import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

// In Docker the code is mounted from the Windows filesystem and inotify
// events don't cross the bind mount: without polling, editing a .tsx doesn't
// trigger HMR. Locally (without the variable) the native watcher is used.
const polling = process.env.VITE_POLLING === 'true'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // shadcn/ui generates its components importing from '@/'.
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
    ...(polling ? { watch: { usePolling: true, interval: 400 } } : {}),
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/healthz': { target: apiTarget, changeOrigin: true },
      '/openapi.json': { target: apiTarget, changeOrigin: true },
    },
  },
})
