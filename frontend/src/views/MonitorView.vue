<template>
  <div>
    <!-- Header -->
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">監控</h2>
      <p class="text-sm text-text-secondary mt-1">自動分析監控資料夾中的新照片，或手動加入其他資料夾一起處理</p>
    </div>

    <!-- Guidance: API key not configured -->
    <div v-if="!hasApiKey && settingsStore.loaded" class="mb-6 rounded-xl border border-yellow-500/30 bg-yellow-500/5 p-5">
      <div class="flex items-center gap-3">
        <svg class="w-5 h-5 text-yellow-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <div class="flex-1">
          <p class="text-sm font-medium text-text-primary">尚未設定 Gemini API Key</p>
          <p class="text-xs text-text-secondary mt-0.5">請先到「設定」頁面填寫 API Key 才能使用監控功能</p>
        </div>
        <router-link to="/settings" class="bg-accent-violet hover:bg-accent-violet-dim text-white px-3 py-1.5 rounded-md text-xs font-medium transition-all">
          前往設定
        </router-link>
      </div>
    </div>

    <!-- Guidance: Watch folder not configured (only when API key ok) -->
    <div v-else-if="!configuredFolder && settingsStore.loaded" class="mb-6 rounded-xl border border-border-default bg-surface-1 p-5">
      <div class="flex items-center gap-3">
        <svg class="w-5 h-5 text-accent-violet flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
        </svg>
        <div class="flex-1">
          <p class="text-sm font-medium text-text-primary">尚未設定監控資料夾</p>
          <p class="text-xs text-text-secondary mt-0.5">到「設定」選擇資料夾後會自動監控新照片；或直接手動加入下方資料夾分析</p>
        </div>
        <router-link to="/settings" class="bg-surface-3 hover:bg-surface-4 text-text-primary px-3 py-1.5 rounded-md text-xs font-medium transition-all">
          前往設定
        </router-link>
      </div>
    </div>

    <!-- Status Panel (sticky) -->
    <div class="sticky top-14 z-30 -mx-6 px-6 py-3 bg-surface-0/90 backdrop-blur-xl border-b border-border-default mb-6">
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center justify-between gap-4 flex-wrap">
          <!-- State + folder -->
          <div class="flex items-center gap-3 min-w-0 flex-1">
            <span
              class="w-2.5 h-2.5 rounded-full flex-shrink-0"
              :class="{
                'bg-green-500 animate-pulse': watchStore.status === 'watching',
                'bg-yellow-500': watchStore.status === 'paused',
                'bg-surface-4': watchStore.status === 'stopped',
              }"
            ></span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-text-primary leading-tight flex items-center">
                <span>{{ watchStore.status === 'watching' ? '監控中' : watchStore.status === 'paused' ? '已暫停' : '已停止' }}</span>
                <span v-if="!watchStore.sseConnected" class="inline-flex items-center gap-1 text-[10px] text-amber-500 ml-2">
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  連線中斷
                </span>
              </p>
              <p v-if="displayFolder" class="text-[11px] text-text-tertiary font-mono truncate mt-0.5">{{ displayFolder }}</p>
              <p v-else class="text-[11px] text-text-tertiary mt-0.5">尚未設定資料夾</p>
            </div>
          </div>

          <!-- Control buttons -->
          <div class="flex items-center gap-2 flex-shrink-0">
            <button
              v-if="watchStore.status === 'stopped'"
              @click="onStartWatch"
              :disabled="!configuredFolder || !hasApiKey"
              class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white px-3.5 py-1.5 rounded-md text-xs font-medium transition-all"
            >
              開始監控
            </button>
            <template v-else>
              <button
                v-if="watchStore.status === 'watching'"
                @click="watchStore.pauseWatch()"
                class="bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-1.5 rounded-md text-xs font-medium transition-all"
              >
                暫停
              </button>
              <button
                v-if="watchStore.status === 'paused'"
                @click="watchStore.resumeWatch()"
                class="bg-accent-violet hover:bg-accent-violet-dim text-white px-3.5 py-1.5 rounded-md text-xs font-medium transition-all"
              >
                繼續
              </button>
              <button
                @click="watchStore.stopWatch()"
                class="bg-surface-3 hover:bg-red-500/10 hover:text-red-500 text-text-secondary px-3.5 py-1.5 rounded-md text-xs font-medium transition-all"
              >
                停止
              </button>
            </template>
          </div>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-4 gap-3 mt-4">
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-text-primary tabular-nums">{{ watchStore.queueSize }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">等待中</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-text-primary tabular-nums">{{ watchStore.processing }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">處理中</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold text-accent-violet tabular-nums">{{ watchStore.completedToday }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">今日完成</p>
          </div>
          <div class="bg-surface-0 rounded-lg p-3 text-center">
            <p class="text-lg font-semibold tabular-nums" :class="watchStore.failedToday ? 'text-red-500' : 'text-text-primary'">{{ watchStore.failedToday }}</p>
            <p class="text-[10px] text-text-tertiary mt-0.5">今日失敗</p>
          </div>
        </div>

        <!-- Error message -->
        <div v-if="errorMsg" class="mt-3 rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2">
          <p class="text-xs text-red-400">{{ errorMsg }}</p>
        </div>
      </div>
    </div>

    <!-- Add folder section -->
    <div class="mb-6">
      <div v-if="!browserOpen" class="flex items-center justify-between gap-3">
        <button
          @click="openBrowser"
          :disabled="!hasApiKey"
          class="flex-1 flex items-center justify-center gap-2 bg-surface-1 border border-dashed border-border-default hover:border-accent-violet/40 hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed text-text-primary px-4 py-3 rounded-xl text-sm font-medium transition-all"
        >
          <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          加入資料夾分析
        </button>

        <!-- Export buttons -->
        <a
          href="/api/export/csv"
          class="inline-flex items-center gap-1.5 bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-2.5 rounded-lg text-xs font-medium transition-colors"
        >
          匯出 CSV
        </a>
        <a
          href="/api/export/json"
          class="inline-flex items-center gap-1.5 bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-2.5 rounded-lg text-xs font-medium transition-colors"
        >
          匯出 JSON
        </a>
      </div>

      <!-- Inline folder browser -->
      <div v-else class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
        <div class="flex items-center gap-2 px-4 py-3 border-b border-border-default bg-surface-2">
          <button v-if="browserData.parent" @click="navigateTo(browserData.parent)" class="p-1.5 rounded-md hover:bg-surface-3 text-text-secondary hover:text-text-primary transition-colors">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <div class="flex-1 text-xs text-text-secondary font-mono truncate">{{ browserData.current }}</div>
          <button
            @click="onEnqueueFolder(browserData.current)"
            :disabled="enqueuing"
            class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-40 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-md text-xs font-medium transition-all"
          >
            {{ enqueuing ? '加入中...' : '加入此資料夾' }}
          </button>
          <button @click="browserOpen = false" class="p-1.5 rounded-md hover:bg-surface-3 text-text-secondary hover:text-text-primary transition-colors">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="max-h-72 overflow-y-auto">
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
              <span v-if="item.photo_count !== undefined" class="ml-auto text-[11px] text-text-tertiary">{{ item.photo_count }} 張</span>
              <svg class="w-4 h-4 text-text-tertiary flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </div>
          </div>
        </div>
        <div v-if="browserData.photo_count > 0" class="flex items-center justify-between px-4 py-2.5 border-t border-border-default bg-surface-2 text-xs">
          <span class="flex items-center gap-1.5 text-text-secondary">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            目前資料夾有 {{ browserData.photo_count }} 張照片
          </span>
        </div>
      </div>
    </div>

    <!-- Enqueue result toast -->
    <div v-if="enqueueResult" class="mb-4 rounded-lg bg-accent-violet/5 border border-accent-violet/20 px-4 py-2.5">
      <p class="text-xs text-accent-violet">
        已加入 <strong>{{ enqueueResult.enqueued }}</strong> 張照片到處理佇列（跳過 {{ enqueueResult.skipped }} 張已處理）
      </p>
    </div>

    <!-- Result list -->
    <div class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
      <div class="flex items-center justify-between gap-2 p-5 pb-3">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">最近處理</h3>
        </div>
        <span v-if="watchStore.recentItems.length" class="text-xs text-text-tertiary tabular-nums">{{ watchStore.recentItems.length }} 筆</span>
      </div>

      <div v-if="watchStore.recentItems.length === 0" class="px-5 pb-8 text-center">
        <p class="text-xs text-text-tertiary py-4">尚無處理記錄</p>
      </div>
      <div v-else>
        <div
          v-for="item in watchStore.recentItems"
          :key="item.file_path"
          @click="openDetail(item)"
          class="flex items-center gap-3 px-5 py-2.5 border-t border-border-subtle cursor-pointer hover:bg-surface-2 transition-colors"
        >
          <!-- Status icon -->
          <svg v-if="item.status === 'completed'" class="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <svg v-else class="w-4 h-4 text-red-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>

          <!-- File path -->
          <span class="text-xs text-text-primary truncate flex-1 font-mono">{{ relativePath(item.file_path) }}</span>

          <!-- Error tooltip for failed -->
          <span v-if="item.status === 'failed' && item.error_message" class="text-[10px] text-red-400 truncate max-w-[30%]" :title="item.error_message">
            {{ item.error_message }}
          </span>

          <!-- Time -->
          <span class="text-[10px] text-text-tertiary flex-shrink-0">{{ formatTime(item.updated_at) }}</span>
        </div>
      </div>
    </div>

    <!-- Detail modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="selected"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="closeDetail"
        >
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="closeDetail"></div>

          <div class="relative bg-surface-1 border border-border-default rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden shadow-2xl">
            <!-- Loading -->
            <div v-if="detailLoading" class="flex items-center justify-center py-20">
              <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
            </div>

            <template v-else-if="detailData">
              <!-- Header -->
              <div class="flex items-start justify-between p-6 pb-0">
                <div class="flex-1 min-w-0 pr-4">
                  <h3 class="text-lg font-semibold text-text-primary leading-tight">{{ detailData.title || '(無標題)' }}</h3>
                  <p v-if="detailData.description" class="text-sm text-text-secondary mt-2 leading-relaxed">{{ detailData.description }}</p>
                </div>
                <button
                  @click="closeDetail"
                  class="shrink-0 w-8 h-8 rounded-lg bg-surface-3 hover:bg-surface-4 flex items-center justify-center text-text-secondary hover:text-text-primary transition-colors"
                >
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <!-- Content -->
              <div class="p-6 overflow-y-auto max-h-[calc(85vh-100px)]">
                <!-- Keywords -->
                <div v-if="detailData.keywords?.length" class="mb-5">
                  <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">關鍵字</p>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="kw in detailData.keywords"
                      :key="kw"
                      class="bg-accent-violet/10 text-accent-violet text-xs font-medium px-2.5 py-1 rounded-md"
                    >
                      {{ kw }}
                    </span>
                  </div>
                </div>

                <!-- Metadata grid -->
                <div class="grid grid-cols-2 gap-3 mb-5">
                  <div class="bg-surface-2 rounded-lg p-3">
                    <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">分類</p>
                    <p class="text-sm font-medium text-text-primary">{{ detailData.category || '--' }}</p>
                  </div>
                  <div class="bg-surface-2 rounded-lg p-3">
                    <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">場景</p>
                    <p class="text-sm font-medium text-text-primary">{{ detailData.scene_type || '--' }}</p>
                  </div>
                  <div class="bg-surface-2 rounded-lg p-3">
                    <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">氛圍</p>
                    <p class="text-sm font-medium text-text-primary">{{ detailData.mood || '--' }}</p>
                  </div>
                  <div class="bg-surface-2 rounded-lg p-3">
                    <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">人數</p>
                    <p class="text-sm font-medium text-text-primary">{{ detailData.people_count ?? '--' }}</p>
                  </div>
                </div>

                <!-- Identified people -->
                <div v-if="detailData.identified_people?.length" class="mb-5">
                  <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">辨識出的人物</p>
                  <p class="text-sm text-text-secondary">{{ detailData.identified_people.join(', ') }}</p>
                </div>

                <!-- OCR -->
                <div v-if="detailData.ocr_text?.length" class="mb-5">
                  <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">辨識文字</p>
                  <p class="text-sm text-text-secondary font-mono bg-surface-2 rounded-lg p-3">{{ detailData.ocr_text.join(' | ') }}</p>
                </div>

                <!-- Error (for failed items) -->
                <div v-if="selected?.status === 'failed'" class="mb-5 rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2.5">
                  <p class="text-[10px] font-medium text-red-400 uppercase tracking-wider mb-1">處理失敗</p>
                  <p class="text-xs text-red-400">{{ selected?.error_message || '(未記錄原因)' }}</p>
                </div>

                <!-- File path -->
                <div class="pt-4 border-t border-border-default">
                  <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">檔案路徑</p>
                  <p class="text-xs text-text-tertiary font-mono break-all">{{ selected?.file_path }}</p>
                </div>
              </div>
            </template>

            <!-- No data for failed items with no result -->
            <template v-else>
              <div class="p-6">
                <div class="flex items-start justify-between mb-4">
                  <h3 class="text-lg font-semibold text-text-primary">處理失敗</h3>
                  <button
                    @click="closeDetail"
                    class="shrink-0 w-8 h-8 rounded-lg bg-surface-3 hover:bg-surface-4 flex items-center justify-center text-text-secondary hover:text-text-primary transition-colors"
                  >
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div v-if="selected?.error_message" class="rounded-lg bg-red-500/5 border border-red-500/20 px-3 py-2.5 mb-4">
                  <p class="text-xs text-red-400">{{ selected.error_message }}</p>
                </div>
                <div class="pt-4 border-t border-border-default">
                  <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">檔案路徑</p>
                  <p class="text-xs text-text-tertiary font-mono break-all">{{ selected?.file_path }}</p>
                </div>
              </div>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useWatchStore } from '../stores/watch'
import { useSettingsStore } from '../stores/settings'

const watchStore = useWatchStore()
const settingsStore = useSettingsStore()

const errorMsg = ref('')
const browserOpen = ref(false)
const browserData = ref({ current: '', parent: null, items: [], photo_count: 0 })
const browserLoading = ref(false)
const enqueuing = ref(false)
const enqueueResult = ref(null)

const selected = ref(null)
const detailData = ref(null)
const detailLoading = ref(false)

const hasApiKey = computed(() => !!settingsStore.settings.gemini_api_key_set)
const configuredFolder = computed(() => settingsStore.settings.watch_folder || '')
const displayFolder = computed(() => watchStore.folder || configuredFolder.value)

const browserFolders = computed(() =>
  browserData.value.items.filter(i => i.type === 'folder')
)

function relativePath(fullPath) {
  const base = displayFolder.value
  if (base && fullPath.startsWith(base)) {
    return fullPath.slice(base.length + 1) || fullPath.split('/').pop()
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

async function onStartWatch() {
  errorMsg.value = ''
  const folderToUse = configuredFolder.value || watchStore.folder
  if (!folderToUse) {
    errorMsg.value = '請先到設定頁選擇監控資料夾'
    return
  }
  const { ok, data } = await watchStore.startWatch(folderToUse)
  if (!ok) errorMsg.value = data.error || '啟動失敗'
}

async function openBrowser() {
  browserOpen.value = true
  enqueueResult.value = null
  const start = configuredFolder.value || watchStore.folder || ''
  await navigateTo(start)
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

async function onEnqueueFolder(path) {
  if (!path) return
  errorMsg.value = ''
  enqueuing.value = true
  try {
    const { ok, data } = await watchStore.enqueueFolder(path)
    if (ok) {
      enqueueResult.value = data
      browserOpen.value = false
      setTimeout(() => { enqueueResult.value = null }, 6000)
    } else {
      errorMsg.value = data.error || '加入失敗'
    }
  } finally {
    enqueuing.value = false
  }
}

async function openDetail(item) {
  selected.value = item
  detailData.value = null
  if (item.status !== 'completed') return
  detailLoading.value = true
  try {
    const res = await fetch(`/api/results/${encodeURIComponent(item.file_path)}`)
    if (res.ok) {
      detailData.value = await res.json()
    }
  } catch {}
  detailLoading.value = false
}

function closeDetail() {
  selected.value = null
  detailData.value = null
}

onMounted(async () => {
  await settingsStore.fetchSettings()
})
</script>

<style scoped>
.modal-enter-active {
  transition: opacity 0.2s ease;
}
.modal-enter-active > div:last-child {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.modal-leave-active {
  transition: opacity 0.15s ease;
}
.modal-leave-active > div:last-child {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.modal-enter-from {
  opacity: 0;
}
.modal-enter-from > div:last-child {
  transform: scale(0.96) translateY(8px);
  opacity: 0;
}
.modal-leave-to {
  opacity: 0;
}
.modal-leave-to > div:last-child {
  transform: scale(0.96);
  opacity: 0;
}
</style>
