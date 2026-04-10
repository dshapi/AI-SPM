import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function devTokenPlugin() {
  return {
    name: 'dev-token',
    configureServer(server) {
      server.middlewares.use('/api/dev-token', (_req, res) => {
        const enc = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url')
        const header  = enc({ alg: 'none', typ: 'JWT' })
        const payload = enc({ sub: 'dev_user', roles: ['admin'], groups: [], exp: Math.floor(Date.now() / 1000) + 86400 })
        const token   = `${header}.${payload}.fakesig`
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify({ token, expires_in: 86400 }))
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), devTokenPlugin()],
  server: {
    port: 3001,
    proxy: {
      // SSE streaming route — must come before the generic /api catch-all
      '/api/chat/stream': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers['cache-control'] = 'no-cache'
          })
        },
      },
      // Orchestrator service — must come before the generic /api catch-all.
      // No rewrite: orchestrator mounts all routes under /api/v1/...
      '/api/v1': {
        target: 'http://localhost:8094',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  preview: { port: 3001 },
})
