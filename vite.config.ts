import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],

  server: {
    proxy: {
      '/api': process.env.KNEURA_API_TARGET || process.env.KNEURA_API_PROXY || 'http://127.0.0.1:8001',
    },
  },

  preview: {
    proxy: {
      '/api': process.env.KNEURA_API_PROXY || 'http://127.0.0.1:8001',
    },
  },
})
