<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Import Photos</h2>

    <div class="bg-white rounded-lg border-2 border-dashed border-gray-300 p-12 text-center"
         @dragover.prevent @drop.prevent="onDrop">
      <div class="text-gray-500 mb-4">
        <p class="text-lg">Drag & drop a folder here</p>
        <p class="text-sm mt-2">or enter the path below</p>
      </div>

      <div class="flex gap-2 max-w-xl mx-auto mt-6">
        <input v-model="folderPath" type="text" placeholder="/path/to/photos"
               class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm" />
        <button @click="startAnalysis" :disabled="!folderPath || analysisStore.isRunning"
                class="bg-blue-600 text-white px-6 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          Analyze
        </button>
      </div>

      <div v-if="folderPath" class="mt-4 text-sm text-gray-600">
        <p>Model: {{ settingsStore.settings.model || 'lite' }} | Concurrency: {{ settingsStore.settings.concurrency || 5 }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '../stores/analysis'
import { useSettingsStore } from '../stores/settings'

const router = useRouter()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()
const folderPath = ref('')

onMounted(() => {
  settingsStore.fetchSettings()
})

function onDrop(e) {
  const items = e.dataTransfer?.items
  if (items?.[0]) {
    folderPath.value = e.dataTransfer.getData('text') || ''
  }
}

async function startAnalysis() {
  if (!folderPath.value) return
  const result = await analysisStore.startAnalysis(folderPath.value, {
    model: settingsStore.settings.model,
    concurrency: settingsStore.settings.concurrency,
    skip_existing: settingsStore.settings.skip_existing,
    write_metadata: settingsStore.settings.write_metadata,
  })
  if (!result.error) {
    router.push('/progress')
  }
}
</script>
