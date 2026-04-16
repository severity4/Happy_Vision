<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">Import Photos</h2>
      <p class="text-sm text-text-secondary mt-1">Analyze event photos with Gemini AI to generate metadata</p>
    </div>

    <!-- Drop zone -->
    <div
      class="relative rounded-xl border-2 border-dashed transition-all duration-300 overflow-hidden"
      :class="isDragging
        ? 'border-accent-violet bg-accent-violet-glow scale-[1.01]'
        : folderPath
          ? 'border-accent-violet/40 bg-accent-violet-subtle'
          : 'border-border-strong bg-surface-1 hover:border-border-strong hover:bg-surface-2'"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="onDrop"
    >
      <div class="px-8 py-16 text-center">
        <!-- Icon -->
        <div class="mx-auto w-16 h-16 rounded-2xl bg-surface-3 flex items-center justify-center mb-6 transition-colors"
             :class="isDragging ? 'bg-accent-violet/20' : ''">
          <svg v-if="!folderPath" class="w-8 h-8 transition-colors" :class="isDragging ? 'text-accent-violet' : 'text-text-tertiary'" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          <svg v-else class="w-8 h-8 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
          </svg>
        </div>

        <!-- Text -->
        <div v-if="!folderPath">
          <p class="text-sm font-medium text-text-primary mb-1">
            {{ isDragging ? 'Drop folder here' : 'Drag and drop a folder' }}
          </p>
          <p class="text-xs text-text-tertiary">or enter the path manually below</p>
        </div>
        <div v-else>
          <p class="text-sm font-medium text-text-primary mb-1">Folder selected</p>
          <p class="text-xs text-text-secondary font-mono truncate max-w-md mx-auto">{{ folderPath }}</p>
        </div>

        <!-- Input row -->
        <div class="flex gap-2 max-w-lg mx-auto mt-8">
          <div class="relative flex-1">
            <input
              v-model="folderPath"
              type="text"
              placeholder="/path/to/photos"
              class="w-full bg-surface-0 border border-border-default rounded-lg px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent-violet/40 focus:border-accent-violet/60 transition-all font-mono"
            />
          </div>
          <button
            @click="startAnalysis"
            :disabled="!folderPath || analysisStore.isRunning"
            class="inline-flex items-center gap-2 bg-accent-violet hover:bg-accent-violet-dim text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed shadow-lg shadow-accent-violet/20 hover:shadow-accent-violet/30 active:scale-[0.98]"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
            </svg>
            Analyze
          </button>
        </div>
      </div>
    </div>

    <!-- Settings summary -->
    <div v-if="folderPath" class="mt-4 flex items-center justify-center gap-4 text-xs text-text-tertiary">
      <span class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-accent-violet"></span>
        Model: {{ settingsStore.settings.model === 'flash' ? 'Gemini 2.5 Flash' : 'Gemini 2.0 Flash Lite' }}
      </span>
      <span class="w-px h-3 bg-border-default"></span>
      <span class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-accent-violet"></span>
        Concurrency: {{ settingsStore.settings.concurrency || 5 }}
      </span>
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
const isDragging = ref(false)

onMounted(() => {
  settingsStore.fetchSettings()
})

function onDrop(e) {
  isDragging.value = false
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
