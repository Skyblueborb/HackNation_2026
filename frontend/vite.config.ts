import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Token jest czytany tylko przez proces dev-servera (Node), nigdy przez bundle.
const apiToken = process.env.O2J_API_TOKEN || '';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: apiToken ? { 'X-API-Token': apiToken } : {},
      },
    },
  },
})