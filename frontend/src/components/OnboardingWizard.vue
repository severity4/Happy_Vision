<template>
  <Teleport to="body">
    <Transition name="onboard">
      <div
        v-if="open"
        class="fixed inset-0 z-[70] flex items-center justify-center p-6"
      >
        <!-- Backdrop: clicking does NOT dismiss (this is important enough
             that we want intentional skip/next, no accidental close). -->
        <div class="absolute inset-0 bg-black/80 backdrop-blur-sm"></div>

        <div class="relative w-full max-w-xl bg-surface-1 border border-border-default rounded-lg shadow-2xl overflow-hidden">
          <!-- Progress dots -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-border-default">
            <div class="flex items-center gap-2">
              <div
                v-for="i in 3"
                :key="i"
                class="w-6 h-1 rounded"
                :class="i <= step
                  ? 'bg-accent-violet'
                  : 'bg-surface-3'"
              ></div>
              <span class="ml-3 font-mono text-[10px] text-text-tertiary tracking-wider">STEP {{ step }} / 3</span>
            </div>
            <button
              @click="skip"
              class="font-mono text-[10px] tracking-wider text-text-tertiary hover:text-text-secondary px-2 py-1 rounded"
            >跳過引導</button>
          </div>

          <!-- Step 1: API key -->
          <section v-if="step === 1" class="p-6">
            <p class="kicker mb-2">STEP 1</p>
            <h2 class="text-xl font-semibold text-text-primary tracking-tight mb-3">需要 Gemini API Key</h2>
            <p class="text-sm text-text-secondary leading-relaxed mb-5">
              Happy Vision 用 Google Gemini 分析照片。到
              <a
                class="text-accent-violet hover:text-accent-violet-dim underline underline-offset-2 cursor-pointer"
                @click.prevent="openExternal('https://aistudio.google.com/apikey')"
              >Google AI Studio</a>
              用你的 Google 帳號登入、點「Create API key」即可拿到免費的 key（格式為 <code class="font-mono text-[11px] px-1 py-0.5 bg-surface-0 rounded border border-border-default text-accent-violet">AIzaSy…</code>）。免費方案每月 100 萬 tokens，夠分析數千張照片。
            </p>
            <input
              v-model="apiKeyInput"
              type="password"
              placeholder="AIzaSy..."
              class="w-full bg-surface-0 border border-border-default rounded px-3 py-2.5 text-sm font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent-violet/60 transition-colors mb-3"
              @keydown.enter="saveApiKey"
            />
            <p v-if="step1Error" class="font-mono text-xs text-error mb-3">{{ step1Error }}</p>
            <div class="flex items-center justify-end gap-2">
              <button
                @click="skip"
                class="bg-surface-2 hover:bg-surface-3 text-text-secondary font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >之後再設定</button>
              <button
                @click="saveApiKey"
                :disabled="!apiKeyInput || step1Busy"
                class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >{{ step1Busy ? '儲存中…' : '儲存並繼續' }}</button>
            </div>
          </section>

          <!-- Step 2: watch folder -->
          <section v-else-if="step === 2" class="p-6">
            <p class="kicker mb-2">STEP 2</p>
            <h2 class="text-xl font-semibold text-text-primary tracking-tight mb-3">選擇監控資料夾</h2>
            <p class="text-sm text-text-secondary leading-relaxed mb-5">
              Happy Vision 會自動監聽這個資料夾裡的新照片，分析後把描述 + 關鍵字寫入 IPTC / XMP metadata，Lightroom 可直接搜尋。
              通常選婚禮或活動的「精選」資料夾。
            </p>

            <!-- Folder browser (reuse same browse API) -->
            <div class="bg-surface-0 border border-border-default rounded p-3 mb-4 max-h-72 overflow-y-auto">
              <div class="flex items-center gap-2 mb-2">
                <button
                  v-if="browserData.parent"
                  @click="navigateTo(browserData.parent)"
                  class="px-2 py-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-3 font-mono text-xs"
                >← 上一層</button>
                <div class="flex-1 text-[11px] font-mono text-text-tertiary truncate">{{ browserData.current || '—' }}</div>
              </div>
              <div v-if="browserLoading" class="py-4 text-center font-mono text-xs text-text-tertiary">載入中…</div>
              <div v-else-if="!browserFolders.length" class="py-4 text-center text-xs text-text-tertiary">此資料夾沒有子資料夾</div>
              <div v-else>
                <div
                  v-for="item in browserFolders"
                  :key="item.path"
                  @click="navigateTo(item.path)"
                  class="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-surface-2 rounded"
                >
                  <span class="text-accent-violet font-mono text-xs flex-shrink-0">▸</span>
                  <span class="text-sm font-mono text-text-primary truncate flex-1">{{ item.name }}</span>
                  <span v-if="item.photo_count" class="text-[10px] font-mono text-text-tertiary">{{ item.photo_count }} 張</span>
                </div>
              </div>
            </div>
            <p v-if="step2Error" class="font-mono text-xs text-error mb-3">{{ step2Error }}</p>
            <div class="flex items-center justify-end gap-2">
              <button
                @click="back"
                class="bg-surface-2 hover:bg-surface-3 text-text-secondary font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >← 上一步</button>
              <button
                @click="selectFolder"
                :disabled="!browserData.current || step2Busy"
                class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >{{ step2Busy ? '儲存中…' : '選擇此資料夾' }}</button>
            </div>
          </section>

          <!-- Step 3: done -->
          <section v-else-if="step === 3" class="p-6">
            <p class="kicker mb-2">STEP 3</p>
            <h2 class="text-xl font-semibold text-text-primary tracking-tight mb-3">設定完成！</h2>
            <p class="text-sm text-text-secondary leading-relaxed mb-5">
              按「開始監控」後，Happy Vision 就會自動分析這個資料夾新進的 JPG。
              速度、成本、連拍去重、星等預篩等進階選項隨時可以到設定頁微調。
            </p>
            <div class="bg-surface-0 border border-border-default rounded p-4 mb-5 space-y-2.5">
              <div class="flex items-center justify-between">
                <span class="kicker">API KEY</span>
                <span class="flex items-center gap-1.5 text-[11px] text-success"><span class="led led-ok"></span>已設定</span>
              </div>
              <div class="flex items-start justify-between gap-3">
                <span class="kicker mt-0.5">監控資料夾</span>
                <span class="text-[11px] font-mono text-accent-violet break-all text-right">{{ truncate(selectedFolder, 48) }}</span>
              </div>
              <div class="flex items-center justify-between">
                <span class="kicker">模型</span>
                <span class="text-[11px] font-mono text-text-secondary">Flash Lite（最便宜）</span>
              </div>
              <div class="flex items-center justify-between">
                <span class="kicker">連拍去重</span>
                <span class="text-[11px] font-mono text-text-secondary">開啟 · 預設靈敏度</span>
              </div>
            </div>
            <p v-if="step3Error" class="font-mono text-xs text-error mb-3">{{ step3Error }}</p>
            <div class="flex items-center justify-end gap-2">
              <button
                @click="finishWithoutStart"
                class="bg-surface-2 hover:bg-surface-3 text-text-secondary font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >之後再開始</button>
              <button
                @click="startAndClose"
                :disabled="step3Busy"
                class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-4 py-2 rounded transition-colors"
              >{{ step3Busy ? '啟動中…' : '▶ 開始監控' }}</button>
            </div>
          </section>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useWatchStore } from '../stores/watch'
import { pushToast } from '../utils/toast.js'

const settings = useSettingsStore()
const watchStore = useWatchStore()

const props = defineProps({
  force: { type: Boolean, default: false },  // trigger from Settings' "再跑一次"
})
const emit = defineEmits(['close'])

const DISMISS_KEY = 'hv_onboarding_dismissed'

const step = ref(1)
const apiKeyInput = ref('')
const step1Error = ref('')
const step1Busy = ref(false)
const step2Error = ref('')
const step2Busy = ref(false)
const step3Error = ref('')
const step3Busy = ref(false)
const selectedFolder = ref('')

const browserData = ref({ current: '', parent: null, items: [] })
const browserLoading = ref(false)

const browserFolders = computed(() =>
  browserData.value.items.filter(i => i.type === 'folder')
)

// Dismissal state. localStorage is NOT reactive — if the computed below
// calls `localStorage.getItem` directly, setting the flag in `skip()` won't
// re-trigger the compute and the wizard stays open. Track it as a ref.
// Bug: 跳過引導 按鈕失效 (2026-04-19) — fixed here.
const dismissed = ref(localStorage.getItem(DISMISS_KEY) === '1')

// Show logic:
//  - force=true (triggered from Settings) always opens
//  - Otherwise, show only when settings are loaded AND user has no API key
//    AND no watch folder AND hasn't dismissed before
const open = computed(() => {
  if (props.force) return true
  if (!settings.loaded) return false
  if (dismissed.value) return false
  const needsKey = !settings.settings.gemini_api_key_set
  const needsFolder = !settings.settings.watch_folder
  return needsKey || needsFolder
})

// When the parent forces the wizard back on (Settings "再跑一次"), clear
// the local dismissed ref too — otherwise the wizard would flash open
// because of `force`, then latch closed as soon as force flips back to
// false after `emit('close')` resolves.
watch(() => props.force, (forced) => {
  if (forced) dismissed.value = false
})

// When opening, fast-forward to the first unfinished step so users who
// half-configured (e.g. have an API key but no folder) don't have to re-enter
// the key.
watch(open, (isOpen) => {
  if (!isOpen) return
  if (!settings.settings.gemini_api_key_set) {
    step.value = 1
  } else if (!settings.settings.watch_folder) {
    step.value = 2
    selectedFolder.value = ''
    navigateTo('')
  } else {
    step.value = 3
    selectedFolder.value = settings.settings.watch_folder || ''
  }
}, { immediate: true })

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? '…' + s.slice(-(n - 1)) : s
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

async function saveApiKey() {
  const k = apiKeyInput.value.trim()
  if (!k) return
  // Sanity — real keys start with AIzaSy and are ~39 chars. Don't reject
  // outright (future variants may differ), just warn if obviously wrong.
  if (k.length < 20) {
    step1Error.value = 'Key 看起來太短，請再確認一次（通常 39 字元開頭 AIzaSy）'
    return
  }
  step1Error.value = ''
  step1Busy.value = true
  try {
    await settings.updateSettings({ gemini_api_key: k })
    apiKeyInput.value = ''
    pushToast('API Key 已儲存', { kind: 'success' })
    step.value = 2
    await navigateTo('')
  } catch (e) {
    step1Error.value = 'API Key 儲存失敗，請重試'
  } finally {
    step1Busy.value = false
  }
}

async function navigateTo(path) {
  browserLoading.value = true
  try {
    const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : '/api/browse'
    const res = await fetch(url)
    const data = await res.json()
    if (!data.error) browserData.value = data
    else step2Error.value = data.error
  } catch {
    step2Error.value = '讀取資料夾失敗'
  } finally {
    browserLoading.value = false
  }
}

async function selectFolder() {
  const path = browserData.value.current
  if (!path) return
  step2Error.value = ''
  step2Busy.value = true
  try {
    await settings.updateSettings({ watch_folder: path })
    selectedFolder.value = path
    await watchStore.fetchStatus()
    step.value = 3
  } catch (e) {
    step2Error.value = '資料夾設定失敗，請重試'
  } finally {
    step2Busy.value = false
  }
}

function back() {
  if (step.value > 1) step.value -= 1
}

function skip() {
  localStorage.setItem(DISMISS_KEY, '1')
  dismissed.value = true
  emit('close')
}

function finishWithoutStart() {
  localStorage.setItem(DISMISS_KEY, '1')
  dismissed.value = true
  emit('close')
}

async function startAndClose() {
  step3Error.value = ''
  step3Busy.value = true
  try {
    const { ok, data } = await watchStore.startWatch(selectedFolder.value)
    if (!ok) {
      step3Error.value = data.error || '啟動失敗，請到監控頁手動開始'
      return
    }
    pushToast('開始監控', { kind: 'success' })
    localStorage.setItem(DISMISS_KEY, '1')
    dismissed.value = true
    emit('close')
  } catch (e) {
    step3Error.value = '啟動失敗，請到監控頁手動開始'
  } finally {
    step3Busy.value = false
  }
}

// Expose reset for settings-triggered "再跑一次"
defineExpose({
  reset: () => {
    localStorage.removeItem(DISMISS_KEY)
  },
})
</script>

<style scoped>
.onboard-enter-active,
.onboard-leave-active {
  transition: all 0.25s ease;
}
.onboard-enter-from,
.onboard-leave-to {
  opacity: 0;
  transform: scale(0.97);
}
</style>
