<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">Watch Folder</h2>
      <p class="text-sm text-text-secondary mt-1">自動監控資料夾，新照片出現即自動分析並寫入 metadata</p>
    </div>

    <div class="max-w-2xl space-y-6">
      <!-- Error: API key not set -->
      <div v-if="!hasApiKey" class="rounded-xl border border-yellow-500/30 bg-yellow-500/5 p-5">
        <div class="flex items-center gap-3">
          <svg class="w-5 h-5 text-yellow-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div>
            <p class="text-sm font-medium text-text-primary">尚未設定 Gemini API Key</p>
            <p class="text-xs text-text-secondary mt-0.5">請先到「設定」頁面填寫 API Key 才能使用監控功能</p>
          </div>
        </div>
      </div>

      <!-- Folder Selection -->
      <div class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
        <div class="flex items-center gap-2 p-5 pb-0">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">監控資料夾</h3>
        </div>

        <!-- Folder Browser (reused pattern from ImportView) -->
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
          <button v-else @click="showBrowser = true" class="w-full bg-surface-0 border border-dashed border-border-default rounded-lg px-3.5 py-4 text-sm text-text-secondary hover:border-accent-violet/40 hover:text-text-primary transition-all text-center">
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
            <button @click="selectFolder(browserData.current)" class="bg-accent-violet hover:bg-accent-violet-dim text-white px-3 py-1.5 rounded-md text-xs font-medium transition-all">
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

      <!-- Watch Controls + Status -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-3">
            <!-- State indicator -->
            <div class="flex items-center gap-2">
              <span
                class="w-2.5 h-2.5 rounded-full"
                :class="{
                  'bg-green-500 animate-pulse': status.status === 'watching',
                  'bg-yellow-500': status.status === 'paused',
                  'bg-surface-4': status.status === 'stopped',
                }"
              ></span>
              <span class="text-sm font-medium text-text-primary">
                {{ status.status === 'watching' ? '監控中' : status.status === 'paused' ? '已暫停' : '已停止' }}
              </span>
            </div>
          </div>

          <!-- Control buttons -->
          <div class="flex items-center gap-2">
            <button
              v-if="status.status === 'stopped'"
              @click="startWatch"
              :disabled="!watchFolder || !hasApiKey"
              class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-medium transition-all"
            >
              開始監控
            </button>
            <template v-else>
              <button
                v-if="status.status === 'watching'"
                @click="pauseWatch"
                class="bg-surface-3 hover:bg-surface-4 text-text-primary px-4 py-2 rounded-lg text-xs font-medium transition-all"
              >
                暫停
              </button>
              <button
                v-if="status.status === 'paused'"
                @click="resumeWatch"
                class="bg-accent-violet hover:bg-accent-violet-dim text-white px-4 py-2 rounded-lg text-xs font-medium transition-all"
              >
                繼續
              </button>
              <button
                @click="stopWatch"
                class="bg-surface-3 hover:bg-red-500/10 hover:text-red-500 text-text-secondary px-4 py-2 rounded-lg text-xs font-medium transition-all"
              >
                停止
              </button>
            </template>
          </div>
        </div>

        <!-- Stats -->
        <div v-if="status.status !== 'stopped'" class="grid grid-cols-4 gap-3">
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-text-primary tabular-nums">{{ status.queue_size || 0 }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">等待中</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-text-primary tabular-nums">{{ status.processing || 0 }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">處理中</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-accent-violet tabular-nums">{{ status.completed_today || 0 }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">今日完成</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold tabular-nums" :class="status.failed_today ? 'text-red-500' : 'text-text-primary'">{{ status.failed_today || 0 }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">今日失敗</p>
          </div>
        </div>

        <!-- Idle message -->
        <div v-if="status.status === 'watching' && !status.queue_size && !status.processing" class="mt-3 text-center text-xs text-text-tertiary py-2">
          監控中，等待新照片...
        </div>

        <!-- Folder not accessible warning -->
        <div v-if="folderError" class="mt-3 rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2">
          <p class="text-xs text-red-400">{{ folderError }}</p>
        </div>
      </div>

      <!-- Concurrency Slider -->
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
            @change="updateConcurrency"
            class="flex-1 h-1.5 bg-surface-3 rounded-full appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-accent-violet/30"
          />
          <span class="text-sm font-mono font-semibold text-text-primary w-6 text-right tabular-nums">{{ concurrency }}</span>
        </div>
        <p class="text-xs text-text-tertiary mt-2">{{ concurrencyDescription }}</p>
      </div>

      <!-- Recent Activity -->
      <div class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
        <div class="flex items-center gap-2 p-5 pb-3">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">最近處理</h3>
        </div>

        <div v-if="recentItems.length === 0" class="px-5 pb-5 text-center text-xs text-text-tertiary py-4">
          尚無處理記錄
        </div>
        <div v-else class="max-h-72 overflow-y-auto">
          <div
            v-for="item in recentItems"
            :key="item.file_path"
            class="flex items-center gap-3 px-5 py-2.5 border-t border-border-subtle"
          >
            <!-- Status icon -->
            <svg v-if="item.status === 'completed'" class="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            <svg v-else class="w-4 h-4 text-red-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>

            <!-- File path (relative) -->
            <span class="text-xs text-text-primary truncate flex-1 font-mono">{{ relativePath(item.file_path) }}</span>

            <!-- Time -->
            <span class="text-[10px] text-text-tertiary flex-shrink-0">{{ formatTime(item.updated_at) }}</span>

            <!-- Retry button for failed -->
            <button
              v-if="item.status === 'failed'"
              @click="retryFile(item.file_path)"
              class="text-[10px] text-accent-violet hover:text-accent-violet-dim font-medium flex-shrink-0 transition-colors"
            >
              重試
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const watchFolder = ref('')
const status = ref({ status: 'stopped', queue_size: 0, processing: 0, completed_today: 0, failed_today: 0 })
const concurrency = ref(1)
const recentItems = ref([])
const hasApiKey = ref(false)
const folderError = ref('')
const showBrowser = ref(false)
const browserData = ref({ current: '', parent: null, items: [] })
const browserLoading = ref(false)

let eventSource = null

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

function relativePath(fullPath) {
  if (watchFolder.value && fullPath.startsWith(watchFolder.value)) {
    return fullPath.slice(watchFolder.value.length + 1)
  }
  return fullPath
}

function formatTime(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  const now = new Date()
  const diffSec = Math.floor((now - d) / 1000)
  if (diffSec < 60) return `${diffSec} 秒前`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分鐘前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小時前`
  return d.toLocaleDateString('zh-TW')
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/watch/status')
    status.value = await res.json()
    watchFolder.value = status.value.folder || watchFolder.value
    folderError.value = ''
  } catch {
    folderError.value = '無法連線到伺服器'
  }
}

async function fetchRecent() {
  try {
    const res = await fetch('/api/watch/recent?limit=20')
    recentItems.value = await res.json()
  } catch {}
}

async function fetchSettings() {
  try {
    const res = await fetch('/api/settings')
    const data = await res.json()
    hasApiKey.value = !!data.gemini_api_key_set
    concurrency.value = data.watch_concurrency || 1
    if (!watchFolder.value) {
      watchFolder.value = data.watch_folder || ''
    }
  } catch {}
}

function connectSSE() {
  if (eventSource) eventSource.close()
  eventSource = new EventSource('/api/watch/events')

  eventSource.addEventListener('watch_progress', (e) => {
    const data = JSON.parse(e.data)
    status.value.queue_size = data.queue_size
    status.value.completed_today = data.completed_today
    status.value.failed_today = data.failed_today
    fetchRecent()
  })

  eventSource.addEventListener('watch_error', (e) => {
    const data = JSON.parse(e.data)
    status.value.failed_today = data.failed_today
    fetchRecent()
  })

  eventSource.addEventListener('watch_state', (e) => {
    const data = JSON.parse(e.data)
    status.value.status = data.status
  })
}

async function navigateTo(path) {
  browserLoading.value = true
  try {
    const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`)
    browserData.value = await res.json()
  } catch {}
  browserLoading.value = false
}

function selectFolder(path) {
  watchFolder.value = path
  showBrowser.value = false
}

async function startWatch() {
  folderError.value = ''
  try {
    const res = await fetch('/api/watch/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: watchFolder.value }),
    })
    const data = await res.json()
    if (!res.ok) {
      folderError.value = data.error || '啟動失敗'
      return
    }
    status.value.status = data.status
  } catch (e) {
    folderError.value = '啟動失敗：' + e.message
  }
}

async function pauseWatch() {
  const res = await fetch('/api/watch/pause', { method: 'POST' })
  const data = await res.json()
  status.value.status = data.status
}

async function resumeWatch() {
  const res = await fetch('/api/watch/resume', { method: 'POST' })
  const data = await res.json()
  status.value.status = data.status
}

async function stopWatch() {
  const res = await fetch('/api/watch/stop', { method: 'POST' })
  const data = await res.json()
  status.value.status = data.status
}

async function updateConcurrency() {
  await fetch('/api/watch/concurrency', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ concurrency: concurrency.value }),
  })
}

async function retryFile(filePath) {
  // Remove from failed in DB, watcher will pick it up on next poll
  // For now, just trigger a status refresh
  await fetchRecent()
}

onMounted(async () => {
  await Promise.all([fetchSettings(), fetchStatus(), fetchRecent()])
  if (!showBrowser.value && !watchFolder.value) {
    showBrowser.value = true
    navigateTo(watchFolder.value || '/Users')
  }
  connectSSE()
})

onUnmounted(() => {
  if (eventSource) eventSource.close()
})
</script>
