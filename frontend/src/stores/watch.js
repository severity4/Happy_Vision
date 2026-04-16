import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useWatchStore = defineStore('watch', () => {
  const status = ref('stopped')          // watching | paused | stopped
  const folder = ref('')
  const queueSize = ref(0)
  const processing = ref(0)
  const completedToday = ref(0)
  const failedToday = ref(0)
  const recentItems = ref([])

  let eventSource = null
  let reconnectTimer = null
  let sseConnected = false

  async function fetchStatus() {
    try {
      const res = await fetch('/api/watch/status')
      const data = await res.json()
      status.value = data.status
      folder.value = data.folder || ''
      queueSize.value = data.queue_size || 0
      processing.value = data.processing || 0
      completedToday.value = data.completed_today || 0
      failedToday.value = data.failed_today || 0
    } catch {}
  }

  async function fetchRecent(limit = 50) {
    try {
      const res = await fetch(`/api/watch/recent?limit=${limit}`)
      recentItems.value = await res.json()
    } catch {}
  }

  function connectSSE() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }

    eventSource = new EventSource('/api/watch/events')

    eventSource.onopen = () => {
      sseConnected = true
    }

    eventSource.addEventListener('watch_progress', (e) => {
      const data = JSON.parse(e.data)
      queueSize.value = data.queue_size
      completedToday.value = data.completed_today
      failedToday.value = data.failed_today
      fetchRecent()
    })

    eventSource.addEventListener('watch_error', (e) => {
      const data = JSON.parse(e.data)
      failedToday.value = data.failed_today
      fetchRecent()
    })

    eventSource.addEventListener('watch_state', (e) => {
      const data = JSON.parse(e.data)
      status.value = data.status
    })

    eventSource.onerror = () => {
      sseConnected = false
      if (eventSource) {
        eventSource.close()
        eventSource = null
      }
      // Attempt reconnect after 3s
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = setTimeout(() => {
        connectSSE()
        // Refresh state in case events were missed
        fetchStatus()
        fetchRecent()
      }, 3000)
    }
  }

  function disconnectSSE() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    sseConnected = false
  }

  async function init() {
    await Promise.all([fetchStatus(), fetchRecent()])
    connectSSE()
  }

  async function startWatch(folderPath) {
    const res = await fetch('/api/watch/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folderPath || folder.value }),
    })
    const data = await res.json()
    if (res.ok) {
      status.value = data.status
      folder.value = data.folder || folder.value
    }
    return { ok: res.ok, data }
  }

  async function pauseWatch() {
    const res = await fetch('/api/watch/pause', { method: 'POST' })
    const data = await res.json()
    if (res.ok) status.value = data.status
    return { ok: res.ok, data }
  }

  async function resumeWatch() {
    const res = await fetch('/api/watch/resume', { method: 'POST' })
    const data = await res.json()
    if (res.ok) status.value = data.status
    return { ok: res.ok, data }
  }

  async function stopWatch() {
    const res = await fetch('/api/watch/stop', { method: 'POST' })
    const data = await res.json()
    if (res.ok) status.value = data.status
    return { ok: res.ok, data }
  }

  async function enqueueFolder(folderPath) {
    const res = await fetch('/api/watch/enqueue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folderPath }),
    })
    const data = await res.json()
    if (res.ok) {
      await Promise.all([fetchStatus(), fetchRecent()])
    }
    return { ok: res.ok, data }
  }

  return {
    status, folder, queueSize, processing, completedToday, failedToday, recentItems,
    init, connectSSE, disconnectSSE, fetchStatus, fetchRecent,
    startWatch, pauseWatch, resumeWatch, stopWatch, enqueueFolder,
  }
})
