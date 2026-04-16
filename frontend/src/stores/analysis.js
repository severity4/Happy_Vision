import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAnalysisStore = defineStore('analysis', () => {
  const isRunning = ref(false)
  const isPaused = ref(false)
  const done = ref(0)
  const total = ref(0)
  const currentFile = ref('')
  const errors = ref([])
  let eventSource = null

  function connectSSE() {
    if (eventSource) eventSource.close()
    eventSource = new EventSource('/api/analysis/stream')

    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data)
      done.value = data.done
      total.value = data.total
      currentFile.value = data.file
    })

    eventSource.addEventListener('error', (e) => {
      const data = JSON.parse(e.data)
      errors.value.push(data)
    })

    eventSource.addEventListener('complete', (e) => {
      isRunning.value = false
      isPaused.value = false
    })
  }

  async function startAnalysis(folder, options = {}) {
    const res = await fetch('/api/analysis/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder, ...options }),
    })
    if (res.ok) {
      isRunning.value = true
      isPaused.value = false
      done.value = 0
      errors.value = []
      connectSSE()
    }
    return res.json()
  }

  async function pause() {
    await fetch('/api/analysis/pause', { method: 'POST' })
    isPaused.value = true
  }

  async function resume() {
    await fetch('/api/analysis/resume', { method: 'POST' })
    isPaused.value = false
  }

  async function cancel() {
    await fetch('/api/analysis/cancel', { method: 'POST' })
    isRunning.value = false
    isPaused.value = false
    if (eventSource) eventSource.close()
  }

  return { isRunning, isPaused, done, total, currentFile, errors, startAnalysis, pause, resume, cancel }
})
