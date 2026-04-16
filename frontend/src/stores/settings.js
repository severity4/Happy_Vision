import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref({})
  const loaded = ref(false)

  async function fetchSettings() {
    const res = await fetch('/api/settings')
    settings.value = await res.json()
    loaded.value = true
  }

  async function updateSettings(updates) {
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    await fetchSettings()
  }

  return { settings, loaded, fetchSettings, updateSettings }
})
