import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

// Inject per-session auth token into every fetch() call and expose it globally
// so SSE/EventSource callers can append it as a query param.
const DEFAULT_FETCH_TIMEOUT_MS = 30_000
const token = document.querySelector('meta[name="hv-token"]')?.content
if (token && token !== '__HV_TOKEN__') {
  window.__HV_TOKEN__ = token
  const originalFetch = window.fetch
  window.fetch = (input, init = {}) => {
    const headers = new Headers(init.headers || {})
    headers.set('X-HV-Token', token)

    // Honor caller-supplied signal; otherwise impose default timeout.
    if (init.signal) {
      return originalFetch(input, { ...init, headers })
    }
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), DEFAULT_FETCH_TIMEOUT_MS)
    return originalFetch(input, { ...init, headers, signal: ctrl.signal })
      .finally(() => clearTimeout(timer))
  }
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
