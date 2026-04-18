/**
 * Tiny toast store. Imported anywhere in the Vue tree to push a transient
 * notification. The <ToastHost/> component in App.vue renders the active
 * toasts. No external dependency; reactive via Vue 3 ref.
 *
 * Kinds: 'success' | 'error' | 'info'
 */
import { ref } from 'vue'

const _toasts = ref([])
let _nextId = 1

export function useToasts() {
  return _toasts
}

export function pushToast(message, { kind = 'success', ttl = 2500 } = {}) {
  const id = _nextId++
  _toasts.value.push({ id, message, kind })
  if (ttl > 0) {
    setTimeout(() => {
      _toasts.value = _toasts.value.filter(t => t.id !== id)
    }, ttl)
  }
  return id
}

export function dismissToast(id) {
  _toasts.value = _toasts.value.filter(t => t.id !== id)
}
