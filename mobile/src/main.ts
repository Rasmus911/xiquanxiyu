import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import { isNativeApp } from './native'

const app = createApp(App)
app.use(createPinia())
app.use(router)
if (location.pathname.replace(/\/$/, '').endsWith('/download')) {
  void router.replace({ name: 'download' })
}
app.mount('#app')

// Service worker only for the hosted web version; Capacitor serves assets
// locally and must not register the web service worker.
if ('serviceWorker' in navigator && import.meta.env.PROD && !isNativeApp()) {
  window.addEventListener('load', () =>
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`),
  )
}
