import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The dev server proxies /api to FastAPI so the browser sees one origin (no CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
  },
})
