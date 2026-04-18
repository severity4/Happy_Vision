<template>
  <div class="min-h-screen bg-surface-0">
    <!-- Update Banner -->
    <Transition name="slide-down">
      <div v-if="update.show" class="sticky top-0 z-50">
        <!-- Available -->
        <div v-if="update.status === 'available'" class="bg-accent-violet/10 border-b border-border-default px-6 py-2">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-[11px] text-text-primary">
              <span class="led led-accent"></span>
              <span>新版本 <strong class="font-mono">v{{ update.latestVersion }}</strong> 可用</span>
              <span class="text-text-tertiary font-mono">(目前 v{{ version }})</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="dismissUpdate" class="text-[10px] text-text-tertiary hover:text-text-secondary px-2 py-1">稍後</button>
              <button @click="startDownload" class="text-[10px] font-medium text-white bg-accent-violet hover:bg-accent-violet-dim px-3 py-1 rounded transition-colors">立即更新</button>
            </div>
          </div>
        </div>

        <!-- Downloading -->
        <div v-else-if="update.status === 'downloading'" class="bg-accent-violet/10 border-b border-border-default px-6 py-2">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-[11px] text-text-primary">
              <span class="led led-accent led-pulse"></span>
              <span>正在下載更新... <span class="font-mono">{{ update.progress }}%</span></span>
            </div>
            <div class="w-32 h-1 bg-surface-2 rounded-full overflow-hidden">
              <div class="h-full bg-accent-violet rounded-full transition-all duration-300" :style="{ width: update.progress + '%' }" />
            </div>
          </div>
        </div>

        <!-- Ready -->
        <div v-else-if="update.status === 'ready'" class="bg-success/10 border-b border-border-default px-6 py-2">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-[11px] text-text-primary">
              <span class="led led-ok"></span>
              <span>更新已下載完成，重新啟動即可使用新版本</span>
            </div>
            <button @click="restartApp" class="text-[10px] font-medium text-white bg-success/90 hover:bg-success px-3 py-1 rounded transition-colors">重新啟動</button>
          </div>
        </div>

        <!-- Error -->
        <div v-else-if="update.status === 'error'" class="bg-error/10 border-b border-border-default px-6 py-2">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-[11px] text-text-primary">
              <span class="led led-error"></span>
              <span>更新檢查失敗</span>
            </div>
            <button @click="dismissUpdate" class="text-[10px] text-text-tertiary hover:text-text-secondary px-2 py-1">關閉</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Navigation -->
    <nav class="sticky top-0 z-40 border-b border-border-default bg-surface-1">
      <div class="h-11 px-6 flex items-center justify-between max-w-6xl mx-auto">
        <!-- Left: brand -->
        <div class="flex items-center gap-3">
          <span class="led" :class="brandLedClass"></span>
          <span class="text-[13px] font-semibold tracking-wider text-text-primary">HAPPY VISION</span>
          <span v-if="version" class="font-mono text-[10px] text-text-tertiary">v{{ version }}</span>
        </div>

        <!-- Center: tabs -->
        <div class="flex items-center gap-0 bg-surface-2 rounded-md p-0.5 border border-border-default">
          <router-link
            v-for="link in navLinks"
            :key="link.to"
            :to="link.to"
            class="px-3 py-1 text-[11px] font-medium tracking-wider rounded transition-colors"
            :class="$route.name === link.name
              ? 'text-text-primary bg-surface-4'
              : 'text-text-tertiary hover:text-text-secondary'"
          >
            {{ link.label }}
          </router-link>
        </div>

        <!-- Right: model + SSE -->
        <div class="flex items-center gap-4 text-[11px] text-text-secondary">
          <span class="flex items-center gap-1.5">
            <span class="led" :class="watchStore.sseConnected ? 'led-ok' : 'led-error'"></span>
            <span class="font-mono">gemini-2.0-flash</span>
          </span>
          <span class="font-mono text-text-tertiary">{{ clock }}</span>
        </div>
      </div>

      <!-- Persistent status strip (Monitor route only) -->
      <div v-if="$route.name === 'monitor'" class="h-9 px-6 flex items-center justify-between text-[11px] bg-surface-0 border-t border-border-default">
        <div class="flex items-center gap-5 max-w-6xl mx-auto w-full">
          <div class="flex items-center gap-5 flex-1 min-w-0">
            <span class="kicker">監控</span>
            <template v-if="watchStore.folder">
              <span class="font-mono truncate">
                <span class="text-text-tertiary">{{ folderPrefix }}</span><span class="text-accent-violet">{{ folderTail }}</span>
              </span>
              <span class="flex items-center gap-1.5 flex-shrink-0">
                <span class="led" :class="watchLedClass"></span>
                <span class="kicker" :class="watchLabelClass">{{ watchLabel }}</span>
              </span>
            </template>
            <template v-else>
              <span class="text-text-tertiary">尚未設定監控資料夾</span>
            </template>
          </div>
          <div class="flex items-center gap-5 font-mono flex-shrink-0">
            <span><span class="text-text-tertiary">佇列</span> <span :class="watchStore.queueSize > 0 ? 'text-warning' : 'text-text-primary'">{{ watchStore.queueSize }}</span></span>
            <span><span class="text-text-tertiary">完成</span> <span class="text-success">{{ watchStore.completedToday }}</span></span>
            <span v-if="watchStore.failedToday > 0"><span class="text-text-tertiary">失敗</span> <span class="text-error">{{ watchStore.failedToday }}</span></span>
            <span v-if="watchStore.dedupSavedToday > 0" title="連拍去重省掉的分析張數"><span class="text-text-tertiary">去重</span> <span class="text-success">{{ watchStore.dedupSavedToday }}</span></span>
            <span v-if="watchStore.costUsdToday > 0"><span class="text-text-tertiary">花費</span> <span class="text-accent-violet">{{ formatCost(watchStore.costUsdToday) }}</span></span>
          </div>
        </div>
      </div>
    </nav>

    <!-- Main content -->
    <main class="max-w-6xl mx-auto px-6 py-8">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useWatchStore } from './stores/watch'

const watchStore = useWatchStore()

const version = ref('')
const clock = ref('')
const navLinks = [
  { to: '/', name: 'monitor', label: '監控' },
  { to: '/settings', name: 'settings', label: '設定' },
]

const update = reactive({
  show: false,
  status: 'idle',       // idle | available | downloading | ready | error
  latestVersion: '',
  progress: 0,
})

let pollTimer = null
let clockTimer = null
let autoApplyAttempted = false

// Derived: watch LED + label
const brandLedClass = computed(() => {
  if (watchStore.status === 'watching') return watchStore.queueSize > 0 ? 'led-accent led-pulse' : 'led-ok'
  if (watchStore.status === 'paused') return 'led-warn'
  return ''
})

const watchLedClass = computed(() => {
  if (watchStore.status === 'watching') return watchStore.queueSize > 0 ? 'led-accent led-pulse' : 'led-ok'
  if (watchStore.status === 'paused') return 'led-warn'
  return ''
})

const watchLabel = computed(() => {
  if (watchStore.status === 'watching') return watchStore.queueSize > 0 ? 'ANALYZING' : 'WATCHING'
  if (watchStore.status === 'paused') return 'PAUSED'
  return 'STOPPED'
})

const watchLabelClass = computed(() => {
  if (watchStore.status === 'watching') return 'text-accent-violet'
  if (watchStore.status === 'paused') return 'text-warning'
  return 'text-text-tertiary'
})

// Split folder path: prefix (dim) + tail (accent). Tail = last segment.
const folderPrefix = computed(() => {
  const f = watchStore.folder
  if (!f) return ''
  const idx = f.lastIndexOf('/')
  return idx >= 0 ? f.slice(0, idx + 1) : ''
})
const folderTail = computed(() => {
  const f = watchStore.folder
  if (!f) return ''
  const idx = f.lastIndexOf('/')
  return idx >= 0 ? f.slice(idx + 1) : f
})

async function checkForUpdate() {
  try {
    const res = await fetch('/api/update/check', { method: 'POST' })
    const data = await res.json()
    update.status = data.status
    update.latestVersion = data.latest_version || ''

    if (data.status === 'available') {
      const dismissed = localStorage.getItem('hv_dismissed_update')
      if (dismissed === data.latest_version) return
      update.show = true
    }
  } catch {
    // Silent — don't interrupt user on check failure
  }
}

async function startDownload() {
  try {
    await fetch('/api/update/download', { method: 'POST' })
    update.status = 'downloading'
    update.progress = 0
    startPolling()
  } catch {
    update.status = 'error'
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/update/status')
      const data = await res.json()
      update.status = data.status
      update.progress = data.progress || 0
      if (data.status === 'ready' || data.status === 'error') stopPolling()
    } catch {}
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function restartApp() {
  try {
    await fetch('/api/update/restart', { method: 'POST' })
  } catch {}
}

async function applyPendingUpdateOnLaunch() {
  if (autoApplyAttempted) return
  autoApplyAttempted = true

  try {
    const res = await fetch('/api/update/status')
    const data = await res.json()
    update.status = data.status
    update.progress = data.progress || 0
    update.latestVersion = data.latest_version || ''

    if (data.status === 'ready') await restartApp()
  } catch {}
}

function dismissUpdate() {
  update.show = false
  stopPolling()
  if (update.latestVersion) {
    localStorage.setItem('hv_dismissed_update', update.latestVersion)
  }
}

function handleVisibilityChange() {
  if (!document.hidden) {
    watchStore.fetchStatus()
    watchStore.fetchRecent()
  }
}

function tickClock() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  clock.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatCost(v) {
  if (!v) return '$0.00'
  if (v >= 1) return `$${v.toFixed(2)}`
  return `$${v.toFixed(4)}`
}

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}

  watchStore.init()
  document.addEventListener('visibilitychange', handleVisibilityChange)

  tickClock()
  clockTimer = setInterval(tickClock, 1000)

  setTimeout(applyPendingUpdateOnLaunch, 1000)
  setTimeout(checkForUpdate, 2000)
})

onUnmounted(() => {
  stopPolling()
  if (clockTimer) clearInterval(clockTimer)
  watchStore.disconnectSSE()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>
