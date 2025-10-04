import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/batches': 'http://localhost:8000',
      '/system': 'http://localhost:8000',
      '/archive': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
    },
  },
})
