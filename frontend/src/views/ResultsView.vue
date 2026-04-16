<template>
  <div>
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-bold">Results</h2>
      <div class="flex gap-2">
        <button @click="writeMetadata" class="bg-green-600 text-white px-4 py-2 rounded text-sm">
          Write Metadata to Photos
        </button>
        <a href="/api/export/csv" class="bg-gray-600 text-white px-4 py-2 rounded text-sm">Export CSV</a>
        <a href="/api/export/json" class="bg-gray-600 text-white px-4 py-2 rounded text-sm">Export JSON</a>
      </div>
    </div>

    <div v-if="loading" class="text-gray-500">Loading results...</div>

    <div v-else-if="results.length === 0" class="text-gray-500">
      No results yet. <router-link to="/" class="text-blue-600">Run an analysis</router-link>.
    </div>

    <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <div v-for="r in results" :key="r.file_path"
           @click="selected = r"
           class="bg-white rounded-lg border p-3 cursor-pointer hover:border-blue-400 transition-colors"
           :class="{ 'border-blue-500': selected?.file_path === r.file_path }">
        <img :src="`/api/photo?path=${encodeURIComponent(r.file_path)}`"
             class="w-full h-32 object-cover rounded mb-2" loading="lazy"
             @error="$event.target.style.display='none'" />
        <p class="text-sm font-medium truncate">{{ r.title }}</p>
        <p class="text-xs text-gray-500 truncate">{{ r.category }}</p>
      </div>
    </div>

    <!-- Detail panel -->
    <div v-if="selected" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
         @click.self="selected = null">
      <div class="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto m-4">
        <div class="flex justify-between items-start mb-4">
          <h3 class="text-lg font-bold">{{ selected.title }}</h3>
          <button @click="selected = null" class="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        <p class="text-sm text-gray-700 mb-3">{{ selected.description }}</p>
        <div class="flex flex-wrap gap-1 mb-3">
          <span v-for="kw in selected.keywords" :key="kw"
                class="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded">{{ kw }}</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-sm text-gray-600">
          <div>Category: <strong>{{ selected.category }}</strong></div>
          <div>Scene: <strong>{{ selected.scene_type }}</strong></div>
          <div>Mood: <strong>{{ selected.mood }}</strong></div>
          <div>People: <strong>{{ selected.people_count }}</strong></div>
        </div>
        <div v-if="selected.identified_people?.length" class="mt-3">
          <p class="text-sm font-medium">Identified People:</p>
          <p class="text-sm text-gray-700">{{ selected.identified_people.join(', ') }}</p>
        </div>
        <div v-if="selected.ocr_text?.length" class="mt-3">
          <p class="text-sm font-medium">OCR Text:</p>
          <p class="text-sm text-gray-700">{{ selected.ocr_text.join(' | ') }}</p>
        </div>
        <p class="text-xs text-gray-400 mt-4 truncate">{{ selected.file_path }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const results = ref([])
const loading = ref(true)
const selected = ref(null)

onMounted(async () => {
  const res = await fetch('/api/results')
  const data = await res.json()
  results.value = data.results
  loading.value = false
})

async function writeMetadata() {
  if (!confirm('Write AI-generated metadata to all photos? Original metadata will be backed up.')) return
  const res = await fetch('/api/results/write-metadata', { method: 'POST' })
  const data = await res.json()
  alert(`Done: ${data.success} written, ${data.failed} failed`)
}
</script>
