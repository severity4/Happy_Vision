<template>
  <div>
    <!-- Loading -->
    <div v-if="!store.loaded" class="flex items-center justify-center py-20">
      <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
    </div>

    <div v-else class="max-w-2xl space-y-4">
      <!-- API Key -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="store.settings.gemini_api_key_set ? 'led-ok' : 'led-warn'"></span>
            <span class="kicker" style="color: var(--color-text-primary)">GEMINI API KEY</span>
          </div>
          <span class="font-mono text-[11px]" :class="store.settings.gemini_api_key_set ? 'text-success' : 'text-warning'">
            {{ store.settings.gemini_api_key_set ? '已啟用' : '未設定' }}
          </span>
        </div>
        <div class="flex gap-2">
          <input
            v-model="apiKey"
            type="password"
            placeholder="AIzaSy..."
            class="flex-1 bg-surface-0 border border-border-default rounded px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-violet/60 transition-colors"
          />
          <button
            @click="saveApiKey"
            :disabled="!apiKey"
            class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-25 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
          >儲存</button>
        </div>
        <p class="text-xs text-text-tertiary mt-3 leading-relaxed">
          還沒有 API Key？到
          <a
            href="https://aistudio.google.com/apikey"
            @click.prevent="openExternal('https://aistudio.google.com/apikey')"
            class="text-accent-violet hover:text-accent-violet-dim font-medium cursor-pointer underline underline-offset-2"
          >Google AI Studio</a>
          用 Google 帳號登入，點「Create API key」就能拿到一組免費的 key（形如 <code class="font-mono text-[11px] px-1.5 py-0.5 bg-surface-0 rounded border border-border-default text-accent-violet">AIzaSy…</code>），複製後貼進上面欄位。
        </p>
      </section>

      <!-- Watch Folder -->
      <section class="border border-border-default bg-surface-1 rounded-md overflow-hidden">
        <div class="flex items-center justify-between p-5 pb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="watchFolder ? 'led-accent' : ''"></span>
            <span class="kicker" style="color: var(--color-text-primary)">WATCH FOLDER · 監控資料夾</span>
          </div>
          <span class="font-mono text-[11px]" :class="watchFolder ? 'text-accent-violet' : 'text-text-tertiary'">
            {{ watchFolder ? '已設定' : '未設定' }}
          </span>
        </div>
        <div class="px-5 pb-5">
          <div v-if="watchFolder" class="flex items-center gap-2 bg-surface-0 border border-border-default rounded px-3 py-2">
            <span class="text-accent-violet font-mono text-xs flex-shrink-0">▸</span>
            <span class="text-sm font-mono text-text-primary truncate flex-1">{{ watchFolder }}</span>
            <button @click="showBrowser = !showBrowser" class="font-mono text-[11px] tracking-wider text-accent-violet hover:text-accent-violet-dim transition-colors">更換</button>
          </div>
          <button
            v-else
            @click="openBrowser"
            class="w-full bg-surface-0 border border-dashed border-border-default hover:border-accent-violet/40 rounded px-3 py-4 font-mono text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            + 選擇要監控的資料夾
          </button>
        </div>

        <!-- Inline folder browser -->
        <div v-if="showBrowser" class="border-t border-border-default">
          <div class="flex items-center gap-2 px-4 py-2 border-b border-border-default bg-surface-2">
            <button
              v-if="browserData.parent"
              @click="navigateTo(browserData.parent)"
              class="px-2 py-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-3 font-mono text-xs"
            >← 上一層</button>
            <div class="flex-1 text-xs font-mono text-text-secondary truncate">{{ browserData.current || '—' }}</div>
            <button
              @click="selectWatchFolder(browserData.current)"
              class="bg-accent-violet hover:bg-accent-violet-dim text-white font-mono text-[11px] tracking-wider px-3 py-1 rounded transition-colors"
            >選擇此資料夾</button>
            <button
              @click="showBrowser = false"
              class="px-2 py-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-3 font-mono text-xs"
            >✕</button>
          </div>
          <div class="max-h-60 overflow-y-auto">
            <div v-if="browserLoading" class="px-4 py-6 text-center text-text-tertiary text-sm font-mono">載入中…</div>
            <div v-else-if="browserFolders.length === 0" class="px-4 py-6 text-center text-text-tertiary text-sm">沒有子資料夾</div>
            <div
              v-for="item in browserFolders"
              :key="item.path"
              @click="navigateTo(item.path)"
              class="flex items-center gap-3 px-4 py-2 border-b border-border-subtle cursor-pointer hover:bg-surface-2 transition-colors"
            >
              <span class="text-accent-violet font-mono text-xs flex-shrink-0">▸</span>
              <span class="text-sm font-mono text-text-primary truncate flex-1">{{ item.name }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Model -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led led-accent"></span>
            <span class="kicker" style="color: var(--color-text-primary)">MODEL · 分析模型</span>
          </div>
          <span class="font-mono text-[11px] text-accent-violet">{{ model === 'lite' ? 'gemini-flash-lite' : 'gemini-2.5-flash' }}</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="model = 'lite'; save({ model: 'lite' }, '模型')"
            class="relative rounded border p-3 text-left transition-colors"
            :class="model === 'lite'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono text-sm font-semibold text-text-primary">Flash Lite</span>
              <span v-if="model === 'lite'" class="led led-accent"></span>
            </div>
            <p class="text-[11px] text-text-tertiary mt-1">較快、較便宜</p>
          </button>
          <button
            @click="model = 'flash'; save({ model: 'flash' }, '模型')"
            class="relative rounded border p-3 text-left transition-colors"
            :class="model === 'flash'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono text-sm font-semibold text-text-primary">Flash 2.5</span>
              <span v-if="model === 'flash'" class="led led-accent"></span>
            </div>
            <p class="text-[11px] text-text-tertiary mt-1">品質較好</p>
          </button>
        </div>
      </section>

      <!-- === 進階效能（預設折疊） === -->
      <div>
        <button
          @click="showAdvanced = !showAdvanced"
          class="w-full flex items-center justify-between px-1 py-2 text-left"
          :aria-expanded="showAdvanced"
        >
          <div class="flex items-center gap-2">
            <span class="font-mono text-[11px] tracking-wider text-accent-violet transition-transform" :class="{ 'rotate-90': showAdvanced }">▸</span>
            <span class="kicker" style="color: var(--color-text-primary)">進階效能</span>
            <span class="text-[11px] text-text-tertiary">· 速度、成本、去重</span>
          </div>
          <span class="font-mono text-[10px] text-text-tertiary">{{ showAdvanced ? '收起' : '展開' }}</span>
        </button>
      </div>

      <template v-if="showAdvanced">

      <!-- Throughput · RPM -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="rpm > 1500 ? 'led-error' : rpm > 200 ? 'led-warn' : 'led-accent'"></span>
            <span class="kicker" style="color: var(--color-text-primary)">RATE LIMIT · 每分鐘請求數 (RPM)</span>
          </div>
          <span class="font-mono text-lg font-semibold" :class="rpm > 1500 ? 'text-error' : rpm > 200 ? 'text-warning' : 'text-accent-violet'">{{ rpm }}</span>
        </div>
        <div class="flex items-center gap-3">
          <input
            v-model.number="rpm"
            type="range"
            min="10"
            max="2000"
            step="10"
            @change="saveRpm"
            class="flex-1 h-1 bg-surface-3 rounded appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(155,123,255,0.6)]"
          />
          <input
            v-model.number="rpm"
            type="number"
            min="1"
            max="5000"
            @change="saveRpm"
            class="w-20 bg-surface-0 border border-border-default rounded px-2 py-1 text-sm font-mono text-text-primary focus:outline-none focus:border-accent-violet/60 text-right"
          />
        </div>
        <div class="flex justify-between mt-1 font-mono text-[10px] text-text-tertiary">
          <span>10</span><span>500</span><span>1000</span><span>1500</span><span>2000</span>
        </div>
        <p class="kicker mt-3" style="color: var(--color-text-secondary)">{{ rpmDescription }}</p>
      </section>

      <!-- Throughput · Image size -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="imageMaxSize < 1536 ? 'led-warn' : 'led-accent'"></span>
            <span class="kicker" style="color: var(--color-text-primary)">IMAGE SIZE · 上傳長邊上限</span>
          </div>
          <span class="font-mono text-[11px] text-accent-violet">{{ imageMaxSize }} px</span>
        </div>
        <div class="grid grid-cols-4 gap-2">
          <button
            v-for="size in [1024, 1536, 2048, 3072]"
            :key="size"
            @click="imageMaxSize = size; save({ image_max_size: size }, '上傳影像大小')"
            class="relative rounded border p-2.5 text-left transition-colors"
            :class="imageMaxSize === size
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <div class="flex items-center justify-between">
              <span class="font-mono text-sm font-semibold text-text-primary">{{ size }}</span>
              <span v-if="imageMaxSize === size" class="led led-accent"></span>
            </div>
            <p class="text-[10px] text-text-tertiary mt-0.5">{{ imageSizeLabels[size] }}</p>
          </button>
        </div>
        <p class="kicker mt-3" style="color: var(--color-text-secondary)">{{ imageSizeDescription }}</p>
      </section>

      <!-- Concurrency -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="concurrency > 3 ? 'led-warn' : 'led-accent'"></span>
            <span class="kicker" style="color: var(--color-text-primary)">CONCURRENCY · 同時處理數量</span>
          </div>
          <span class="font-mono text-lg font-semibold" :class="concurrency > 6 ? 'text-error' : concurrency > 3 ? 'text-warning' : 'text-accent-violet'">{{ concurrency }}</span>
        </div>
        <input
          v-model.number="concurrency"
          type="range"
          min="1"
          max="10"
          @change="saveConcurrency"
          class="w-full h-1 bg-surface-3 rounded appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(155,123,255,0.6)]"
        />
        <div class="flex justify-between mt-1 font-mono text-[10px] text-text-tertiary">
          <span>1</span><span>5</span><span>10</span>
        </div>
        <p class="kicker mt-3" style="color: var(--color-text-secondary)">{{ concurrencyDescription }}</p>
      </section>

      <!-- Dedup · pHash -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="led" :class="phashThreshold === 0 ? '' : phashThreshold > 10 ? 'led-warn' : 'led-ok'"></span>
            <span class="kicker" style="color: var(--color-text-primary)">DEDUP · 連拍去重</span>
          </div>
          <span class="font-mono text-lg font-semibold" :class="phashThreshold === 0 ? 'text-text-tertiary' : phashThreshold > 10 ? 'text-warning' : 'text-success'">{{ phashThreshold === 0 ? 'OFF' : phashThreshold }}</span>
        </div>
        <input
          v-model.number="phashThreshold"
          type="range"
          min="0"
          max="16"
          @change="save({ phash_threshold: phashThreshold }, '連拍去重靈敏度')"
          class="w-full h-1 bg-surface-3 rounded appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(155,123,255,0.6)]"
        />
        <div class="flex justify-between mt-1 font-mono text-[10px] text-text-tertiary">
          <span>0 OFF</span><span>5 預設</span><span>10</span><span>16 寬鬆</span>
        </div>
        <p class="kicker mt-3" style="color: var(--color-text-secondary)">{{ phashDescription }}</p>
      </section>

      <!-- Skip existing -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5" id="skip-existing-section">
        <label for="skip" class="flex items-center justify-between cursor-pointer">
          <div class="flex items-center gap-2">
            <span class="led" :class="skipExisting ? 'led-ok' : ''"></span>
            <div>
              <span class="kicker" style="color: var(--color-text-primary)">SKIP EXISTING · 跳過已處理</span>
              <p class="text-[11px] text-text-tertiary mt-1">跳過已分析過的照片</p>
            </div>
          </div>
          <div class="relative">
            <input
              v-model="skipExisting"
              type="checkbox"
              @change="save({ skip_existing: skipExisting }, '跳過已處理')"
              class="sr-only peer"
              id="skip"
            />
            <div class="w-9 h-5 bg-surface-3 peer-checked:bg-accent-violet rounded-full transition-colors"></div>
            <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform peer-checked:translate-x-4"></div>
          </div>
        </label>
      </section>

      </template>

      <!-- === 開發者工具（預設折疊） === -->
      <div>
        <button
          @click="showDeveloper = !showDeveloper"
          class="w-full flex items-center justify-between px-1 py-2 text-left"
          :aria-expanded="showDeveloper"
        >
          <div class="flex items-center gap-2">
            <span class="font-mono text-[11px] tracking-wider text-accent-violet transition-transform" :class="{ 'rotate-90': showDeveloper }">▸</span>
            <span class="kicker" style="color: var(--color-text-primary)">開發者工具</span>
            <span class="text-[11px] text-text-tertiary">· 回報問題時用</span>
          </div>
          <span class="font-mono text-[10px] text-text-tertiary">{{ showDeveloper ? '收起' : '展開' }}</span>
        </button>
      </div>

      <template v-if="showDeveloper">

      <!-- Tester identity -->
      <section class="border border-border-default bg-surface-1 rounded-md p-5">
        <div class="flex items-center gap-2 mb-3">
          <span class="led"></span>
          <span class="kicker" style="color: var(--color-text-primary)">TESTER · 測試者資訊</span>
        </div>
        <p class="text-[11px] text-text-tertiary mb-3">用來辨識是哪位同事、哪台機器回報的狀況</p>
        <div class="grid grid-cols-2 gap-2">
          <input
            v-model="testerName"
            type="text"
            placeholder="測試者名稱"
            class="bg-surface-0 border border-border-default rounded px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-violet/60 transition-colors"
          />
          <input
            v-model="machineName"
            type="text"
            placeholder="機器名稱"
            class="bg-surface-0 border border-border-default rounded px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-violet/60 transition-colors"
          />
        </div>
        <button
          @click="saveTesterInfo"
          class="mt-3 bg-surface-3 hover:bg-surface-4 text-text-primary font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
        >儲存測試資訊</button>
      </section>

      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useWatchStore } from '../stores/watch'
import { pushToast } from '../utils/toast.js'

const store = useSettingsStore()
const watchStore = useWatchStore()

const apiKey = ref('')
const testerName = ref('')
const machineName = ref('')
const model = ref('lite')
const concurrency = ref(1)
const skipExisting = ref(false)
const rpm = ref(60)
const imageMaxSize = ref(3072)
const phashThreshold = ref(5)
const showAdvanced = ref(false)
const showDeveloper = ref(false)

const imageSizeLabels = {
  1024: '最省',
  1536: '較省',
  2048: '平衡',
  3072: '最佳品質',
}

async function openExternal(url) {
  try {
    const res = await fetch('/api/system/open_external', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    if (!res.ok) throw new Error('backend refused')
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

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

const rpmDescription = computed(() => {
  const n = rpm.value
  if (n <= 60) return `每分鐘最多 ${n} 張 · 免費方案上限，安全值`
  if (n <= 200) return `每分鐘最多 ${n} 張 · 適合付費方案的起步檔位`
  if (n <= 1500) return `每分鐘最多 ${n} 張 · 付費方案 flash-lite 常態值，15 萬張約 ${Math.round(150000 / n)} 分鐘跑完`
  return `每分鐘最多 ${n} 張 · 超過 1500 RPM 需確認 API 配額已升級，不然會 429 連發`
})

const imageSizeDescription = computed(() => {
  const s = imageMaxSize.value
  if (s >= 3072) return '3072px · 細節最清楚，描述品質最高，input tokens 也最多'
  if (s >= 2048) return '2048px · 細節略減，input tokens 約減 45%'
  if (s >= 1536) return '1536px · 大場景與人像仍清楚，input tokens 約減 75%'
  return '1024px · 小字/遠景會糊，input tokens 約減 90%，僅推薦給大量歷史庫存補跑'
})

const phashDescription = computed(() => {
  const n = phashThreshold.value
  if (n === 0) return '關閉去重：每張都送 Gemini。保守，但有連拍時會花多一倍錢'
  if (n <= 3) return `嚴格比對（${n} bits）· 只合併幾乎一模一樣的連拍。誤判極低，但遺漏率較高`
  if (n <= 6) return `預設靈敏度（${n} bits）· 婚禮連拍 5-15 張會歸為同組，只分析 1 張，約省 20-40%`
  if (n <= 10) return `寬鬆比對（${n} bits）· 同場景不同動作也算同組，省更多但描述可能套錯`
  return `極寬鬆（${n} bits）· 會把不同人物或場景誤判為重複，不建議開這麼高`
})

onMounted(async () => {
  await store.fetchSettings()
  model.value = store.settings.model || 'lite'
  testerName.value = store.settings.tester_name || ''
  machineName.value = store.settings.machine_name || ''
  concurrency.value = Math.min(10, Math.max(1, store.settings.watch_concurrency || store.settings.concurrency || 1))
  skipExisting.value = store.settings.skip_existing || false
  watchFolder.value = store.settings.watch_folder || ''
  rpm.value = Math.min(5000, Math.max(1, store.settings.rate_limit_rpm || 60))
  imageMaxSize.value = [1024, 1536, 2048, 3072].includes(store.settings.image_max_size)
    ? store.settings.image_max_size
    : 3072
  phashThreshold.value = Math.min(16, Math.max(0, store.settings.phash_threshold ?? 5))
})

async function saveApiKey() {
  if (!apiKey.value) return
  try {
    await store.updateSettings({ gemini_api_key: apiKey.value })
    apiKey.value = ''
    pushToast('API Key 已儲存', { kind: 'success' })
  } catch {
    pushToast('儲存失敗，請重試', { kind: 'error' })
  }
}

async function save(updates, label = '') {
  try {
    await store.updateSettings(updates)
    pushToast(label ? `${label} 已儲存` : '設定已儲存', { kind: 'success' })
  } catch {
    pushToast('儲存失敗，請重試', { kind: 'error' })
  }
}

async function saveTesterInfo() {
  await save({
    tester_name: testerName.value,
    machine_name: machineName.value,
  }, '測試資訊')
}

async function saveRpm() {
  const v = Math.min(5000, Math.max(1, Number(rpm.value) || 60))
  rpm.value = v
  await save({ rate_limit_rpm: v }, '處理速度上限')
}

async function saveConcurrency() {
  try {
    await store.updateSettings({ concurrency: concurrency.value, watch_concurrency: concurrency.value })
    await fetch('/api/watch/concurrency', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concurrency: concurrency.value }),
    })
    pushToast('同時處理數量 已儲存', { kind: 'success' })
  } catch {
    pushToast('儲存失敗，請重試', { kind: 'error' })
  }
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
  await watchStore.fetchStatus()
}
</script>
