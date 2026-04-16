<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">設定</h2>
      <p class="text-sm text-text-secondary mt-1">設定 API 金鑰、監控資料夾與分析選項</p>
    </div>

    <!-- Loading -->
    <div v-if="!store.loaded" class="flex items-center justify-center py-20">
      <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
    </div>

    <div v-else class="max-w-lg space-y-6">
      <!-- API Key -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
            </svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-text-primary">Gemini API Key</h3>
            <p v-if="store.settings.gemini_api_key_set" class="text-xs text-success mt-0.5">
              已啟用 ({{ store.settings.gemini_api_key }})
            </p>
            <p v-else class="text-xs text-text-tertiary mt-0.5">分析功能必須填寫</p>
          </div>
        </div>
        <div class="flex gap-2">
          <input
            v-model="apiKey"
            type="password"
            placeholder="輸入你的 Gemini API Key"
            class="flex-1 bg-surface-0 border border-border-default rounded-lg px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent-violet/40 focus:border-accent-violet/60 transition-all"
          />
          <button
            @click="saveApiKey"
            :disabled="!apiKey"
            class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-all"
          >
            儲存
          </button>
        </div>
      </div>

      <!-- Watch Folder -->
      <div class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
        <div class="flex items-center gap-2 p-5 pb-0">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-text-primary">監控資料夾</h3>
            <p class="text-xs text-text-tertiary mt-0.5">自動分析此資料夾中的新照片</p>
          </div>
        </div>

        <div class="p-5">
          <div v-if="watchFolder" class="flex items-center gap-3 bg-surface-0 border border-border-default rounded-lg px-3.5 py-2.5">
            <svg class="w-4 h-4 text-accent-violet flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
            <span class="text-sm text-text-primary font-mono truncate flex-1">{{ watchFolder }}</span>
            <button @click="showBrowser = !showBrowser" class="text-xs text-accent-violet hover:text-accent-violet-dim font-medium transition-colors">
              更換
            </button>
          </div>
          <button
            v-else
            @click="openBrowser"
            class="w-full bg-surface-0 border border-dashed border-border-default rounded-lg px-3.5 py-4 text-sm text-text-secondary hover:border-accent-violet/40 hover:text-text-primary transition-all text-center"
          >
            選擇要監控的資料夾
          </button>
        </div>

        <!-- Inline folder browser -->
        <div v-if="showBrowser" class="border-t border-border-default">
          <div class="flex items-center gap-2 px-4 py-3 border-b border-border-default bg-surface-2">
            <button v-if="browserData.parent" @click="navigateTo(browserData.parent)" class="p-1.5 rounded-md hover:bg-surface-3 text-text-secondary hover:text-text-primary transition-colors">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <div class="flex-1 text-xs text-text-secondary font-mono truncate">{{ browserData.current }}</div>
            <button @click="selectWatchFolder(browserData.current)" class="bg-accent-violet hover:bg-accent-violet-dim text-white px-3 py-1.5 rounded-md text-xs font-medium transition-all">
              選擇此資料夾
            </button>
          </div>
          <div class="max-h-60 overflow-y-auto">
            <div v-if="browserLoading" class="px-4 py-6 text-center text-text-tertiary text-sm">載入中...</div>
            <div v-else-if="browserFolders.length === 0" class="px-4 py-6 text-center text-text-tertiary text-sm">沒有子資料夾</div>
            <div v-else>
              <div
                v-for="item in browserFolders"
                :key="item.path"
                @click="navigateTo(item.path)"
                class="flex items-center gap-3 px-4 py-2.5 border-b border-border-subtle cursor-pointer hover:bg-surface-2 transition-colors"
              >
                <svg class="w-5 h-5 text-accent-violet flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
                </svg>
                <span class="text-sm text-text-primary truncate">{{ item.name }}</span>
                <svg class="w-4 h-4 text-text-tertiary ml-auto flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Model selection -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">模型</h3>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="model = 'lite'; save({ model: 'lite' })"
            class="relative rounded-lg border p-3 text-left transition-all"
            :class="model === 'lite'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <p class="text-sm font-medium text-text-primary">Flash Lite</p>
            <p class="text-xs text-text-tertiary mt-0.5">較快、較便宜</p>
            <div v-if="model === 'lite'" class="absolute top-2.5 right-2.5 w-2 h-2 rounded-full bg-accent-violet"></div>
          </button>
          <button
            @click="model = 'flash'; save({ model: 'flash' })"
            class="relative rounded-lg border p-3 text-left transition-all"
            :class="model === 'flash'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <p class="text-sm font-medium text-text-primary">Flash 2.5</p>
            <p class="text-xs text-text-tertiary mt-0.5">品質較好</p>
            <div v-if="model === 'flash'" class="absolute top-2.5 right-2.5 w-2 h-2 rounded-full bg-accent-violet"></div>
          </button>
        </div>
      </div>

      <!-- Concurrency (unified, range 1-10) -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">同時處理數量</h3>
        </div>
        <div class="flex items-center gap-3">
          <input
            v-model.number="concurrency"
            type="range"
            min="1"
            max="10"
            @change="saveConcurrency"
            class="flex-1 h-1.5 bg-surface-3 rounded-full appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-accent-violet/30"
          />
          <span class="text-sm font-mono font-semibold text-text-primary w-6 text-right tabular-nums">{{ concurrency }}</span>
        </div>
        <p class="text-xs text-text-tertiary mt-2">{{ concurrencyDescription }}</p>
      </div>

      <!-- Skip existing -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <label for="skip" class="flex items-center justify-between cursor-pointer">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
              <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 8.689c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062A1.125 1.125 0 013 16.811V8.69zM12.75 8.689c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062a1.125 1.125 0 01-1.683-.977V8.69z" />
              </svg>
            </div>
            <div>
              <p class="text-sm font-semibold text-text-primary">跳過已處理</p>
              <p class="text-xs text-text-tertiary mt-0.5">跳過已分析過的照片</p>
            </div>
          </div>
          <div class="relative">
            <input
              v-model="skipExisting"
              type="checkbox"
              @change="save({ skip_existing: skipExisting })"
              class="sr-only peer"
              id="skip"
            />
            <div class="w-10 h-6 bg-surface-4 peer-checked:bg-accent-violet rounded-full transition-colors"></div>
            <div class="absolute left-0.5 top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform peer-checked:translate-x-4"></div>
          </div>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useWatchStore } from '../stores/watch'

const store = useSettingsStore()
const watchStore = useWatchStore()

const apiKey = ref('')
const model = ref('lite')
const concurrency = ref(1)
const skipExisting = ref(false)

const watchFolder = ref('')
const showBrowser = ref(false)
const browserData = ref({ current: '', parent: null, items: [] })
const browserLoading = ref(false)

const browserFolders = computed(() =>
  browserData.value.items.filter(i => i.type === 'folder')
)

const concurrencyDescription = computed(() => {
  const n = concurrency.value
  if (n === 1) return `同時分析 ${n} 張照片，不影響其他工作`
  if (n <= 3) return `同時分析 ${n} 張照片，稍微增加網路使用`
  if (n <= 6) return `同時分析 ${n} 張照片，會佔用較多網路頻寬，可能影響 LucidLink 同步速度`
  return `同時分析 ${n} 張照片，大量佔用網路頻寬，建議在沒有其他人使用時才開啟`
})

onMounted(async () => {
  await store.fetchSettings()
  model.value = store.settings.model || 'lite'
  // Unified concurrency: prefer watch_concurrency (used by watcher), fall back to concurrency
  concurrency.value = Math.min(10, Math.max(1, store.settings.watch_concurrency || store.settings.concurrency || 1))
  skipExisting.value = store.settings.skip_existing || false
  watchFolder.value = store.settings.watch_folder || ''
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

async function saveConcurrency() {
  // Save to both backend config (watch_concurrency for watcher) and update live watcher
  await store.updateSettings({ concurrency: concurrency.value, watch_concurrency: concurrency.value })
  // Update running watcher's concurrency immediately
  try {
    await fetch('/api/watch/concurrency', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concurrency: concurrency.value }),
    })
  } catch {}
}

async function openBrowser() {
  showBrowser.value = true
  await navigateTo(watchFolder.value || '')
}

async function navigateTo(path) {
  browserLoading.value = true
  try {
    const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : '/api/browse'
    const res = await fetch(url)
    const data = await res.json()
    if (!data.error) browserData.value = data
  } catch {}
  browserLoading.value = false
}

async function selectWatchFolder(path) {
  watchFolder.value = path
  showBrowser.value = false
  await store.updateSettings({ watch_folder: path })
  // Reflect change in watchStore immediately (if watcher is stopped, just update UI;
  // if running, user needs to restart — surface by fetching status)
  await watchStore.fetchStatus()
}
</script>
