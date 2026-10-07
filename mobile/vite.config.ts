import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Relative paths are required so the same build works both when served at
  // https://api.pqxqxy.xyz/mobile/ and when bundled by Capacitor (served from
  // the WebView root https://localhost/ inside the APK).
  base: './',
  server: {
    host: '0.0.0.0',
    port: 5174,
  },
})
