<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">匯入照片</h2>
      <p class="text-sm text-text-secondary mt-1">使用 Gemini AI 分析活動照片，自動產生描述與標籤</p>
    </div>

    <!-- Folder Browser -->
    <div class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
      <!-- Breadcrumb / Path bar -->
      <div class="flex items-center gap-2 px-4 py-3 border-b border-border-default bg-surface-2">
        <button
          v-if="browserData.parent"
          @click="navigateTo(browserData.parent)"
          class="p-1.5 rounded-md hover:bg-surface-3 text-text-secondary hover:text-text-primary transition-colors"
          title="上一層"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
        <div class="flex-1 min-w-0">
          <input
            v-model="pathInput"
            @keydown.enter="navigateTo(pathInput)"
            type="text"
            class="w-full bg-surface-0 border border-border-default rounded-md px-3 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-accent-violet/40 font-mono"
            placeholder="/path/to/photos"
          />
        </div>
        <button
          @click="navigateTo(pathInput)"
          class="p-1.5 rounded-md hover:bg-surface-3 text-text-secondary hover:text-text-primary transition-colors"
          title="前往路徑"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </button>
      </div>

      <!-- File list -->
      <div class="max-h-80 overflow-y-auto">
        <div v-if="loading" class="px-4 py-8 text-center text-text-tertiary text-sm">載入中...</div>
        <div v-else-if="browserData.items.length === 0" class="px-4 py-8 text-center text-text-tertiary text-sm">空資料夾</div>
        <div v-else>
          <div
            v-for="item in browserData.items"
            :key="item.path"
            @click="item.type === 'folder' ? navigateTo(item.path) : null"
            class="flex items-center gap-3 px-4 py-2.5 border-b border-border-subtle transition-colors"
            :class="item.type === 'folder' ? 'cursor-pointer hover:bg-surface-2' : 'opacity-60'"
          >
            <!-- Folder icon -->
            <svg v-if="item.type === 'folder'" class="w-5 h-5 text-accent-violet flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
            <!-- Photo icon -->
            <svg v-else class="w-5 h-5 text-text-tertiary flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M6.75 7.5a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
            </svg>
            <span class="text-sm text-text-primary truncate">{{ item.name }}</span>
            <svg v-if="item.type === 'folder'" class="w-4 h-4 text-text-tertiary ml-auto flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
          </div>
        </div>
      </div>

      <!-- Footer: photo count + analyze button -->
      <div class="flex items-center justify-between px-4 py-3 border-t border-border-default bg-surface-2">
        <div class="text-xs text-text-secondary">
          <span v-if="browserData.photo_count > 0" class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            {{ browserData.photo_count }} 張照片
          </span>
          <span v-else class="text-text-tertiary">此資料夾沒有照片</span>
        </div>
        <button
          @click="startAnalysis"
          :disabled="browserData.photo_count === 0 || analysisStore.isRunning"
          class="inline-flex items-center gap-2 bg-accent-violet hover:bg-accent-violet-dim text-white px-5 py-2 rounded-lg text-sm font-medium transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed shadow-lg shadow-accent-violet/20 hover:shadow-accent-violet/30 active:scale-[0.98]"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
          </svg>
          開始分析 {{ browserData.photo_count }} 張照片
        </button>
      </div>
    </div>

    <!-- Settings summary -->
    <div class="mt-4 flex items-center justify-center gap-4 text-xs text-text-tertiary">
      <span class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-accent-violet"></span>
        模型：{{ settingsStore.settings.model === 'flash' ? 'Flash 2.5' : 'Flash Lite' }}
      </span>
      <span class="w-px h-3 bg-border-default"></span>
      <span class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-accent-violet"></span>
        並行數量：{{ settingsStore.settings.concurrency || 5 }}
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
const pathInput = ref('')
const loading = ref(true)
const browserData = ref({
  current: '',
  parent: null,
  items: [],
  photo_count: 0,
})

onMounted(async () => {
  settingsStore.fetchSettings()
  await navigateTo('')  // Start at home directory
})

async function navigateTo(path) {
  loading.value = true
  try {
    const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : '/api/browse'
    const res = await fetch(url)
    const data = await res.json()
    if (!data.error) {
      browserData.value = data
      pathInput.value = data.current
    }
  } catch (e) {
    console.error('Browse error:', e)
  }
  loading.value = false
}

async function startAnalysis() {
  if (browserData.value.photo_count === 0) return
  const result = await analysisStore.startAnalysis(browserData.value.current, {
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
