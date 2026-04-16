<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Settings</h2>

    <div v-if="!store.loaded" class="text-gray-500">Loading...</div>

    <div v-else class="bg-white rounded-lg border p-6 max-w-lg">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Gemini API Key</label>
          <div class="flex gap-2">
            <input v-model="apiKey" type="password" placeholder="Enter your Gemini API key"
                   class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm" />
            <button @click="saveApiKey" class="bg-blue-600 text-white px-4 py-2 rounded text-sm">Save</button>
          </div>
          <p v-if="store.settings.gemini_api_key_set" class="text-xs text-green-600 mt-1">
            Key is set ({{ store.settings.gemini_api_key }})
          </p>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <select v-model="model" @change="save({ model })"
                  class="border border-gray-300 rounded px-3 py-2 text-sm w-full">
            <option value="lite">Gemini 2.0 Flash Lite (faster, cheaper)</option>
            <option value="flash">Gemini 2.5 Flash (better quality)</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Concurrency</label>
          <input v-model.number="concurrency" type="number" min="1" max="20"
                 @change="save({ concurrency })"
                 class="border border-gray-300 rounded px-3 py-2 text-sm w-24" />
        </div>

        <div class="flex items-center gap-2">
          <input v-model="skipExisting" type="checkbox" @change="save({ skip_existing: skipExisting })"
                 class="rounded" id="skip" />
          <label for="skip" class="text-sm text-gray-700">Skip already processed photos</label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()
const apiKey = ref('')
const model = ref('lite')
const concurrency = ref(5)
const skipExisting = ref(false)

onMounted(async () => {
  await store.fetchSettings()
  model.value = store.settings.model || 'lite'
  concurrency.value = store.settings.concurrency || 5
  skipExisting.value = store.settings.skip_existing || false
})

async function saveApiKey() {
  if (apiKey.value) {
    await store.updateSettings({ gemini_api_key: apiKey.value })
    apiKey.value = ''
  }
}

async function save(updates) {
  await store.updateSettings(updates)
}
</script>
