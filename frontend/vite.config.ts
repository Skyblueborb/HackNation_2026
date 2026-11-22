import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Values are read by the dev-server process (Node), never by the JS bundle.
const apiToken = process.env.O2J_API_TOKEN || '';
const apiTarget = process.env.O2J_API_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        headers: apiToken ? { 'X-API-Token': apiToken } : {},
      },
    },
  },
})