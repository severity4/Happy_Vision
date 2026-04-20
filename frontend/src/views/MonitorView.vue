<template>
  <div class="space-y-5">
    <!-- Guidance: API key not configured -->
    <div v-if="!hasApiKey && settingsStore.loaded" class="border border-warning/30 bg-warning/[0.04] rounded-md p-4">
      <div class="flex items-center gap-3">
        <span class="led led-warn"></span>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-text-primary">尚未設定 Gemini API Key</p>
          <p class="kicker mt-1" style="color: var(--color-text-secondary)">請先到「設定」頁面填寫 API Key 才能使用監控功能</p>
        </div>
        <router-link to="/settings" class="bg-accent-violet hover:bg-accent-violet-dim text-white font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">前往設定</router-link>
      </div>
    </div>

    <!-- Guidance: Watch folder not configured -->
    <div v-else-if="!configuredFolder && settingsStore.loaded" class="border border-border-default bg-surface-1 rounded-md p-4">
      <div class="flex items-center gap-3">
        <span class="led led-accent"></span>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-text-primary">尚未設定監控資料夾</p>
          <p class="kicker mt-1" style="color: var(--color-text-secondary)">到「設定」選擇資料夾後會自動監控；或手動加入下方資料夾分析</p>
        </div>
        <router-link to="/settings" class="bg-surface-3 hover:bg-surface-4 text-text-primary font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">前往設定</router-link>
      </div>
    </div>

    <!-- ACTION BAR -->
    <section class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-2">
        <button
          v-if="watchStore.status === 'stopped'"
          @click="onStartWatch"
          :disabled="!configuredFolder || !hasApiKey"
          :title="startWatchTooltip"
          class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-25 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-4 py-1.5 rounded transition-colors"
        >
          ▶ 開始監控
        </button>
        <template v-else>
          <button
            v-if="watchStore.status === 'watching'"
            @click="watchStore.pauseWatch()"
            class="bg-surface-3 hover:bg-surface-4 text-text-primary font-mono text-[11px] tracking-wider px-4 py-1.5 rounded transition-colors"
          >
            ⏸ 暫停
          </button>
          <button
            v-if="watchStore.status === 'paused'"
            @click="watchStore.resumeWatch()"
            class="bg-accent-violet hover:bg-accent-violet-dim text-white font-mono text-[11px] tracking-wider px-4 py-1.5 rounded transition-colors"
          >
            ▶ 繼續
          </button>
          <button
            @click="watchStore.stopWatch()"
            class="bg-surface-2 hover:bg-error/10 hover:text-error text-text-secondary font-mono text-[11px] tracking-wider px-4 py-1.5 rounded transition-colors"
          >
            ■ 停止
          </button>
        </template>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="openBrowser"
          :disabled="!hasApiKey"
          :title="!hasApiKey ? '請先到設定頁填寫 Gemini API Key' : '瀏覽資料夾並加入佇列分析'"
          class="bg-surface-2 hover:bg-surface-3 disabled:opacity-25 disabled:cursor-not-allowed text-text-primary border border-border-default hover:border-accent-violet/40 font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors"
        >
          + 加入資料夾
        </button>
        <button @click="downloadExport('pdf')" :disabled="exportBusy" class="bg-accent-violet/10 hover:bg-accent-violet/20 border border-accent-violet/30 text-accent-violet disabled:opacity-40 disabled:cursor-not-allowed font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">PDF 報告</button>
        <button @click="downloadExport('csv')" :disabled="exportBusy" class="bg-surface-2 hover:bg-surface-3 text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">CSV</button>
        <button @click="downloadExport('json')" :disabled="exportBusy" class="bg-surface-2 hover:bg-surface-3 text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">JSON</button>
        <button @click="downloadExport('diagnostics')" :disabled="exportBusy" class="bg-surface-2 hover:bg-surface-3 text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed font-mono text-[11px] tracking-wider px-3 py-1.5 rounded transition-colors">診斷</button>
      </div>
    </section>

    <!-- Error toast -->
    <div v-if="errorMsg" class="border border-error/30 bg-error/[0.05] rounded-md px-4 py-2">
      <p class="text-xs text-error">{{ humanizeError(errorMsg) }}</p>
    </div>

    <!-- Enqueue result toast -->
    <div v-if="enqueueResult" class="border border-accent-violet/30 bg-accent-violet/[0.05] rounded-md px-4 py-2">
      <p class="font-mono text-xs text-accent-violet">
        已加入 <strong>{{ enqueueResult.enqueued }}</strong> 張照片到處理佇列 · 跳過 {{ enqueueResult.skipped }} 張已處理
      </p>
    </div>

    <!-- Export success toast -->
    <div v-if="exportMsg" class="border border-accent-violet/30 bg-accent-violet/[0.05] rounded-md px-4 py-2">
      <p class="font-mono text-xs text-accent-violet">{{ exportMsg }}</p>
    </div>

    <!-- Inline folder browser -->
    <section v-if="browserOpen" class="border border-border-default bg-surface-1 rounded-md overflow-hidden">
      <div class="flex items-center gap-2 px-3 py-2 border-b border-border-default bg-surface-2">
        <button
          v-if="browserData.parent"
          @click="navigateTo(browserData.parent)"
          class="px-2 py-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-3 font-mono text-xs"
        >← 上一層</button>
        <div class="flex-1 text-xs text-text-secondary font-mono truncate">{{ browserData.current || '—' }}</div>
        <button
          @click="onEnqueueFolder(browserData.current)"
          :disabled="enqueuing"
          class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-25 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-3 py-1 rounded transition-colors"
        >{{ enqueuing ? '加入中…' : '加入此資料夾' }}</button>
        <button
          @click="browserOpen = false"
          class="px-2 py-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-3 font-mono text-xs"
        >✕</button>
      </div>
      <div class="max-h-72 overflow-y-auto">
        <div v-if="browserLoading" class="px-4 py-6 text-center text-text-tertiary text-sm font-mono">載入中…</div>
        <div v-else-if="browserFolders.length === 0" class="px-4 py-6 text-center text-text-tertiary text-sm">沒有子資料夾</div>
        <div
          v-for="item in browserFolders"
          :key="item.path"
          @click="navigateTo(item.path)"
          class="flex items-center gap-3 px-4 py-2 border-b border-border-subtle cursor-pointer hover:bg-surface-2 transition-colors"
        >
          <span class="text-accent-violet font-mono text-xs flex-shrink-0">▸</span>
          <span class="text-sm text-text-primary font-mono truncate flex-1">{{ item.name }}</span>
          <span v-if="item.photo_count !== undefined" class="text-[11px] text-text-tertiary font-mono flex-shrink-0">{{ item.photo_count }} 張</span>
        </div>
      </div>
      <div v-if="browserData.photo_count > 0" class="flex items-center justify-between px-4 py-2 border-t border-border-default bg-surface-2">
        <span class="flex items-center gap-2 text-xs text-text-secondary">
          <span class="led led-ok"></span>
          <span class="font-mono">目前資料夾有 {{ browserData.photo_count }} 張照片</span>
        </span>
      </div>
    </section>

    <!-- 5 STAT GAUGE TILES -->
    <section class="grid grid-cols-5 gap-3">
      <div class="border border-border-default bg-surface-1 rounded-md p-3">
        <div class="flex items-center justify-between">
          <span class="kicker">QUEUE · 等待</span>
          <span class="led" :class="watchStore.queueSize > 0 ? 'led-warn' : ''"></span>
        </div>
        <div class="font-mono text-2xl font-semibold mt-1" :class="watchStore.queueSize > 0 ? 'text-warning' : 'text-text-primary'">{{ watchStore.queueSize }}</div>
        <div class="h-0.5 bg-surface-3 mt-2 rounded overflow-hidden">
          <div class="h-full bg-warning transition-all duration-500" :style="{ width: queueWidth + '%' }"></div>
        </div>
      </div>
      <div class="border border-border-default bg-surface-1 rounded-md p-3">
        <div class="flex items-center justify-between">
          <span class="kicker">PROC · 處理中</span>
          <span class="led" :class="watchStore.processing > 0 ? 'led-accent led-pulse' : ''"></span>
        </div>
        <div class="font-mono text-2xl font-semibold mt-1" :class="watchStore.processing > 0 ? 'text-accent-violet' : 'text-text-primary'">{{ watchStore.processing }}</div>
        <div class="h-0.5 bg-surface-3 mt-2 rounded overflow-hidden">
          <div class="h-full bg-accent-violet transition-all duration-500" :style="{ width: (watchStore.processing > 0 ? 100 : 0) + '%' }"></div>
        </div>
      </div>
      <div class="border border-border-default bg-surface-1 rounded-md p-3">
        <div class="flex items-center justify-between">
          <span class="kicker">DONE · 今日完成</span>
          <span class="led" :class="watchStore.completedToday > 0 ? 'led-ok' : ''"></span>
        </div>
        <div class="font-mono text-2xl font-semibold text-success mt-1">{{ watchStore.completedToday }}</div>
        <div class="h-0.5 bg-surface-3 mt-2 rounded overflow-hidden">
          <div class="h-full bg-success transition-all duration-500" :style="{ width: doneWidth + '%' }"></div>
        </div>
      </div>
      <button
        type="button"
        @click="openFailedModal"
        :disabled="watchStore.failedToday === 0"
        class="text-left w-full border border-border-default bg-surface-1 rounded-md p-3 transition-colors hover:border-warning/50 disabled:cursor-default disabled:hover:border-border-default"
        :title="watchStore.failedToday > 0 ? '點擊查看 / 重試失敗的照片' : '目前沒有失敗的照片'"
      >
        <div class="flex items-center justify-between">
          <span class="kicker">FAIL · 今日失敗</span>
          <span class="led" :class="watchStore.failedToday > 0 ? 'led-error' : ''"></span>
        </div>
        <div class="font-mono text-2xl font-semibold mt-1" :class="watchStore.failedToday > 0 ? 'text-error' : 'text-text-primary'">{{ watchStore.failedToday }}</div>
        <div class="h-0.5 bg-surface-3 mt-2 rounded overflow-hidden">
          <div class="h-full bg-error transition-all duration-500" :style="{ width: failRatio + '%' }"></div>
        </div>
        <div v-if="watchStore.failedToday > 0" class="font-mono text-[10px] text-warning mt-1">
          點擊查看 / 重試 →
        </div>
      </button>
      <div class="border border-border-default bg-surface-1 rounded-md p-3">
        <div class="flex items-center justify-between">
          <span class="kicker">COST · 今日花費</span>
          <span class="led" :class="watchStore.costUsdToday > 0 ? 'led-accent' : ''"></span>
        </div>
        <div class="font-mono text-2xl font-semibold mt-1" :class="watchStore.costUsdToday > 0 ? 'text-accent-violet' : 'text-text-primary'">{{ formatUsd(watchStore.costUsdToday) }}</div>
        <div class="font-mono text-[10px] text-text-tertiary mt-1">≈ NT${{ formatTwdShort(watchStore.costUsdToday) }}</div>
      </div>
    </section>

    <!-- RESULTS TABLE -->
    <section class="border border-border-default bg-surface-1 rounded-md overflow-hidden">
      <!-- header -->
      <div class="h-10 px-4 flex items-center justify-between border-b border-border-default bg-surface-2">
        <div class="flex items-center gap-2">
          <span class="led" :class="watchStore.recentItems.length > 0 ? 'led-ok' : ''"></span>
          <span class="kicker" style="color: var(--color-text-primary)">RECENT RESULTS · 最近結果</span>
          <span v-if="watchStore.recentItems.length" class="font-mono text-[11px] text-text-tertiary">{{ watchStore.recentItems.length }} 筆</span>
        </div>
        <div class="flex items-center gap-3 text-[11px] text-text-tertiary font-mono">
          <span v-if="!watchStore.sseConnected" class="flex items-center gap-1.5 text-error">
            <span class="led led-error"></span>
            <span>SSE 連線中斷</span>
          </span>
        </div>
      </div>

      <!-- column headers -->
      <div class="grid grid-cols-12 gap-2 px-4 py-2 border-b border-border-default bg-surface-0">
        <div class="col-span-1 kicker">狀態</div>
        <div class="col-span-7 kicker">FILE · 檔案</div>
        <div class="col-span-3 kicker">NOTE · 備註</div>
        <div class="col-span-1 kicker text-right">時間</div>
      </div>

      <!-- empty state -->
      <div v-if="watchStore.recentItems.length === 0" class="px-4 py-12 text-center">
        <p class="font-mono text-xs text-text-tertiary">尚無處理記錄</p>
        <p class="kicker mt-2">開始監控或手動加入資料夾後，結果會顯示在這裡</p>
      </div>

      <!-- rows -->
      <div v-else class="max-h-[520px] overflow-y-auto">
        <div
          v-for="item in watchStore.recentItems"
          :key="item.file_path"
          @click="openDetail(item)"
          class="grid grid-cols-12 gap-2 px-4 py-2 border-b border-border-subtle cursor-pointer hover:bg-surface-2 transition-colors items-center"
        >
          <div class="col-span-1">
            <span class="led" :class="item.status === 'completed' ? 'led-ok' : 'led-error'"></span>
          </div>
          <div class="col-span-7 font-mono text-[12px] text-text-primary truncate">{{ relativePath(item.file_path) }}</div>
          <div class="col-span-3 text-[11px] truncate">
            <span v-if="item.status === 'failed' && item.error_message" class="text-error" :title="item.error_message">{{ humanizeError(item.error_message) }}</span>
            <span v-else class="text-text-tertiary font-mono">—</span>
          </div>
          <div class="col-span-1 font-mono text-[10px] text-text-tertiary text-right">{{ formatTime(item.updated_at) }}</div>
        </div>
      </div>
    </section>

    <!-- Detail modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="selected"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="closeDetail"
        >
          <div class="absolute inset-0 bg-black/75 backdrop-blur-sm" @click="closeDetail"></div>
          <div class="relative bg-surface-1 border border-border-default rounded-md w-full max-w-2xl max-h-[85vh] overflow-hidden shadow-2xl">
            <!-- Loading -->
            <div v-if="detailLoading" class="flex items-center justify-center py-20">
              <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
            </div>

            <template v-else-if="detailData">
              <!-- Header -->
              <div class="flex items-start justify-between p-5 border-b border-border-default">
                <div class="flex-1 min-w-0 pr-4">
                  <span class="kicker">結果詳情</span>
                  <h3 class="text-lg font-semibold text-text-primary leading-tight mt-1">{{ detailData.title || '(無標題)' }}</h3>
                  <p v-if="detailData.description" class="text-sm text-text-secondary mt-2 leading-relaxed">{{ detailData.description }}</p>
                </div>
                <button
                  @click="closeDetail"
                  class="shrink-0 w-8 h-8 rounded bg-surface-2 hover:bg-surface-3 flex items-center justify-center text-text-secondary hover:text-text-primary font-mono text-xs"
                >✕</button>
              </div>

              <!-- Content -->
              <div class="p-5 overflow-y-auto max-h-[calc(85vh-120px)] space-y-4">
                <!-- Keywords -->
                <div v-if="detailData.keywords?.length">
                  <p class="kicker mb-2">關鍵字</p>
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="kw in detailData.keywords"
                      :key="kw"
                      class="bg-accent-violet/10 text-accent-violet font-mono text-[11px] px-2 py-0.5 rounded"
                    >{{ kw }}</span>
                  </div>
                </div>

                <!-- Metadata grid -->
                <div class="grid grid-cols-2 gap-2">
                  <div class="bg-surface-0 border border-border-default rounded p-3">
                    <p class="kicker mb-1">分類</p>
                    <p class="font-mono text-sm text-text-primary">{{ detailData.category || '—' }}</p>
                  </div>
                  <div class="bg-surface-0 border border-border-default rounded p-3">
                    <p class="kicker mb-1">場景</p>
                    <p class="font-mono text-sm text-text-primary">{{ detailData.scene_type || '—' }}</p>
                  </div>
                  <div class="bg-surface-0 border border-border-default rounded p-3">
                    <p class="kicker mb-1">氛圍</p>
                    <p class="font-mono text-sm text-text-primary">{{ detailData.mood || '—' }}</p>
                  </div>
                  <div class="bg-surface-0 border border-border-default rounded p-3">
                    <p class="kicker mb-1">人數</p>
                    <p class="font-mono text-sm text-text-primary">{{ detailData.people_count ?? '—' }}</p>
                  </div>
                </div>

                <!-- Dedup badge -->
                <div v-if="detailData._dedup?.duplicate_of" class="border border-success/30 bg-success/[0.05] rounded p-3">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="led led-ok"></span>
                    <span class="kicker" style="color: var(--color-success)">DEDUP · 近似連拍</span>
                  </div>
                  <p class="text-[12px] text-text-secondary">此張 metadata 複製自 <span class="font-mono text-success">{{ relativePath(detailData._dedup.duplicate_of) }}</span>，未呼叫 Gemini（省下一次 API call）</p>
                </div>

                <!-- Usage / cost -->
                <div v-if="detailData._usage" class="border border-accent-violet/20 bg-accent-violet/[0.04] rounded p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="kicker" style="color: var(--color-accent-violet)">USAGE · 用量與花費</span>
                    <span class="font-mono text-[10px] text-text-tertiary">{{ detailData._usage.model || '—' }}</span>
                  </div>
                  <div class="grid grid-cols-3 gap-3">
                    <div>
                      <p class="kicker">INPUT</p>
                      <p class="font-mono text-sm text-text-primary mt-0.5">{{ (detailData._usage.input_tokens || 0).toLocaleString() }}</p>
                      <p class="font-mono text-[10px] text-text-tertiary">tokens</p>
                    </div>
                    <div>
                      <p class="kicker">OUTPUT</p>
                      <p class="font-mono text-sm text-text-primary mt-0.5">{{ (detailData._usage.output_tokens || 0).toLocaleString() }}</p>
                      <p class="font-mono text-[10px] text-text-tertiary">tokens</p>
                    </div>
                    <div>
                      <p class="kicker">COST</p>
                      <p class="font-mono text-sm text-accent-violet mt-0.5">{{ formatUsdFine(detailData._usage.cost_usd) }}</p>
                      <p class="font-mono text-[10px] text-text-tertiary">≈ NT${{ formatTwdShort(detailData._usage.cost_usd) }}</p>
                    </div>
                  </div>
                </div>

                <!-- Identified people -->
                <div v-if="detailData.identified_people?.length">
                  <p class="kicker mb-1">辨識出的人物</p>
                  <p class="text-sm text-text-secondary">{{ detailData.identified_people.join(', ') }}</p>
                </div>

                <!-- OCR -->
                <div v-if="detailData.ocr_text?.length">
                  <p class="kicker mb-1">辨識文字</p>
                  <p class="font-mono text-xs text-text-secondary bg-surface-0 border border-border-default rounded p-3">{{ detailData.ocr_text.join(' | ') }}</p>
                </div>

                <!-- Error (for failed items) -->
                <div v-if="selected?.status === 'failed'" class="border border-error/30 bg-error/[0.05] rounded p-3">
                  <p class="kicker mb-1" style="color: var(--color-error)">處理失敗</p>
                  <p class="text-xs text-error">{{ humanizeError(selected?.error_message || '(未記錄原因)') }}</p>
                  <p v-if="selected?.error_message && selected.error_message !== humanizeError(selected.error_message)" class="font-mono text-[10px] text-text-tertiary mt-1 break-all">技術細節：{{ selected.error_message }}</p>
                </div>

                <!-- File path -->
                <div class="pt-3 border-t border-border-default">
                  <p class="kicker mb-1">檔案路徑</p>
                  <p class="font-mono text-[11px] text-text-tertiary break-all">{{ selected?.file_path }}</p>
                </div>
              </div>
            </template>

            <!-- Failed, no result data -->
            <template v-else>
              <div class="p-5">
                <div class="flex items-start justify-between mb-4">
                  <div>
                    <span class="kicker">結果詳情</span>
                    <h3 class="text-lg font-semibold text-text-primary mt-1">處理失敗</h3>
                  </div>
                  <button
                    @click="closeDetail"
                    class="shrink-0 w-8 h-8 rounded bg-surface-2 hover:bg-surface-3 flex items-center justify-center text-text-secondary hover:text-text-primary font-mono text-xs"
                  >✕</button>
                </div>
                <div v-if="selected?.error_message" class="border border-error/30 bg-error/[0.05] rounded p-3 mb-4">
                  <p class="text-xs text-error">{{ humanizeError(selected.error_message) }}</p>
                  <p v-if="selected.error_message !== humanizeError(selected.error_message)" class="font-mono text-[10px] text-text-tertiary mt-2 break-all">技術細節：{{ selected.error_message }}</p>
                </div>
                <div class="pt-3 border-t border-border-default">
                  <p class="kicker mb-1">檔案路徑</p>
                  <p class="font-mono text-[11px] text-text-tertiary break-all">{{ selected?.file_path }}</p>
                </div>
              </div>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- v0.9.0: Async Batch API jobs, if any are in flight or recently finished. -->
    <BatchJobsPanel />

    <!-- v0.12.0: retry failed photos modal. Opened from the FAIL stat card. -->
    <FailedRetryModal
      :open="failedModalOpen"
      :folder="configuredFolder || watchStore.folder || ''"
      @close="failedModalOpen = false"
      @retried="onRetried"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWatchStore } from '../stores/watch'
import { useSettingsStore } from '../stores/settings'
import { humanizeError } from '../utils/errors.js'
import { pushToast } from '../utils/toast.js'
import BatchJobsPanel from '../components/BatchJobsPanel.vue'
import FailedRetryModal from '../components/FailedRetryModal.vue'

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

// v0.12.0: retry-failed modal state
const failedModalOpen = ref(false)
function openFailedModal() {
  if (watchStore.failedToday === 0) return
  failedModalOpen.value = true
}
async function onRetried(payload) {
  // Refresh stats so FAIL card updates immediately. watchStore.fetchStatus
  // reads today's completed/failed/cost counts from the DB.
  await watchStore.fetchStatus()
}

const timeTick = ref(0)
let tickTimer = null

// Export via backend save-to-Downloads. Earlier tried fetch → blob →
// programmatic <a download> click, but pywebview's WKWebView ignores
// the download attribute (or silently fails) — clicking just did nothing
// visible. The reliable fix: backend writes the file to ~/Downloads and
// returns the path, frontend shows a toast. No WKWebView download
// handler needed.
const exportBusy = ref(false)
const exportMsg = ref('')

const EXPORT_LABELS = {
  pdf: 'PDF 報告',
  csv: 'CSV',
  json: 'JSON',
  diagnostics: '診斷包',
}

async function downloadExport(kind) {
  if (exportBusy.value) return
  exportBusy.value = true
  errorMsg.value = ''
  exportMsg.value = ''
  try {
    const res = await fetch(`/api/export/save/${kind}`, { method: 'POST' })
    if (res.status === 404) {
      errorMsg.value = '尚無分析結果可匯出（先處理一些照片再試）'
      return
    }
    const body = await res.json().catch(() => ({}))
    if (!res.ok) {
      errorMsg.value = `匯出失敗：${body?.error || res.status}`
      return
    }
    // body.saved = absolute path like /Users/…/Downloads/happy_vision_report_20260420-094500.csv
    const label = EXPORT_LABELS[kind] || kind
    const shortPath = (body.saved || '').replace(/^.*\/Downloads\//, '~/Downloads/')
    exportMsg.value = `已匯出 ${label} → ${shortPath}`
    setTimeout(() => { exportMsg.value = '' }, 6000)
  } catch (e) {
    errorMsg.value = `匯出失敗：${e?.message || e}`
  } finally {
    exportBusy.value = false
  }
}

const hasApiKey = computed(() => !!settingsStore.settings.gemini_api_key_set)
const configuredFolder = computed(() => settingsStore.settings.watch_folder || '')
const displayFolder = computed(() => watchStore.folder || configuredFolder.value)

const browserFolders = computed(() =>
  browserData.value.items.filter(i => i.type === 'folder')
)

const startWatchTooltip = computed(() => {
  if (!hasApiKey.value) return '請先到設定頁填寫 Gemini API Key'
  if (!configuredFolder.value) return '請先到設定頁選擇監控資料夾'
  return '開始監控（即時分析新進照片）'
})

// Visual meters — cap at a reasonable ceiling so the bar is readable
const queueWidth = computed(() => Math.min(100, (watchStore.queueSize / 50) * 100))
const doneWidth = computed(() => Math.min(100, (watchStore.completedToday / 500) * 100))
const failRatio = computed(() => {
  const total = watchStore.completedToday + watchStore.failedToday
  if (!total) return 0
  return Math.min(100, (watchStore.failedToday / total) * 100)
})

function formatUsd(v) {
  if (!v) return '$0.00'
  if (v >= 1) return `$${v.toFixed(2)}`
  return `$${v.toFixed(4)}`
}

function formatTwdShort(v) {
  const twd = (v || 0) * 32
  if (twd >= 1) return `${Math.round(twd).toLocaleString()}`
  return twd.toFixed(1)
}

function formatUsdFine(v) {
  if (!v) return '$0.0000'
  if (v >= 1) return `$${v.toFixed(4)}`
  return `$${v.toFixed(6)}`
}

function relativePath(fullPath) {
  const base = displayFolder.value
  if (base && fullPath.startsWith(base)) {
    return fullPath.slice(base.length + 1) || fullPath.split('/').pop()
  }
  return fullPath
}

function formatTime(isoString) {
  // eslint-disable-next-line no-unused-expressions
  timeTick.value
  if (!isoString) return ''
  const d = new Date(isoString)
  const now = new Date()
  const diffSec = Math.floor((now - d) / 1000)
  if (diffSec < 60) return `${diffSec}s`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`
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
    if (res.ok) detailData.value = await res.json()
  } catch {}
  detailLoading.value = false
}

function closeDetail() {
  selected.value = null
  detailData.value = null
}

onMounted(async () => {
  await settingsStore.fetchSettings()
  tickTimer = setInterval(() => { timeTick.value++ }, 30_000)
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
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
