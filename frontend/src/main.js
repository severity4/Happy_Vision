import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

// Inject per-session auth token into every fetch() call and expose it globally
// so SSE/EventSource callers can append it as a query param.
const token = document.querySelector('meta[name="hv-token"]')?.content
if (token && token !== '__HV_TOKEN__') {
  window.__HV_TOKEN__ = token
  const originalFetch = window.fetch
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || {})
    headers.set('X-HV-Token', token)
    return originalFetch(input, { ...init, headers })
  }
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
