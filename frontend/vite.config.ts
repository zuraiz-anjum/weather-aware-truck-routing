import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development Vite serves the app and hands /api to Django on its usual
// port; in production Django serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    // MapLibre alone is most of a megabyte; it is loaded on its own, after the form.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
