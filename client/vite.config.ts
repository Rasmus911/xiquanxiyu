import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: './',
  build: { target: 'chrome108', cssTarget: 'chrome108' },
  define: {
    __XIQUAN_BUILD_ID__: JSON.stringify(process.env.VITE_BUILD_ID || 'dev'),
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
  test: {
    environment: 'jsdom',
  },
})

