<template>
  <div class="min-h-screen bg-surface-0">
    <!-- Update Banner -->
    <Transition name="slide-down">
      <div v-if="update.show" class="sticky top-0 z-50">
        <!-- Available -->
        <div v-if="update.status === 'available'" class="bg-accent-violet/10 border-b border-accent-violet/20 px-6 py-2.5">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-xs text-text-primary">
              <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              <span>新版本 <strong>v{{ update.latestVersion }}</strong> 可用</span>
              <span class="text-text-tertiary">(目前 v{{ version }})</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="dismissUpdate" class="text-[10px] text-text-tertiary hover:text-text-secondary px-2 py-1">稍後</button>
              <button @click="startDownload" class="text-[10px] font-medium text-white bg-accent-violet hover:bg-accent-violet/90 px-3 py-1 rounded-md transition-colors">立即更新</button>
            </div>
          </div>
        </div>

        <!-- Downloading -->
        <div v-else-if="update.status === 'downloading'" class="bg-accent-violet/10 border-b border-accent-violet/20 px-6 py-2.5">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-xs text-text-primary">
              <svg class="w-4 h-4 text-accent-violet animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>正在下載更新... {{ update.progress }}%</span>
            </div>
            <div class="w-32 h-1.5 bg-surface-3 rounded-full overflow-hidden">
              <div class="h-full bg-accent-violet rounded-full transition-all duration-300" :style="{ width: update.progress + '%' }" />
            </div>
          </div>
        </div>

        <!-- Ready to restart -->
        <div v-else-if="update.status === 'ready'" class="bg-green-500/10 border-b border-green-500/20 px-6 py-2.5">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-xs text-text-primary">
              <svg class="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>更新已下載完成！重新啟動即可使用新版本</span>
            </div>
            <button @click="restartApp" class="text-[10px] font-medium text-white bg-green-600 hover:bg-green-500 px-3 py-1 rounded-md transition-colors">重新啟動</button>
          </div>
        </div>

        <!-- Error -->
        <div v-else-if="update.status === 'error'" class="bg-red-500/10 border-b border-red-500/20 px-6 py-2.5">
          <div class="flex items-center justify-between max-w-6xl mx-auto">
            <div class="flex items-center gap-2 text-xs text-text-primary">
              <svg class="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>更新檢查失敗</span>
            </div>
            <button @click="dismissUpdate" class="text-[10px] text-text-tertiary hover:text-text-secondary px-2 py-1">關閉</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Navigation -->
    <nav class="sticky top-0 z-40 border-b border-border-default bg-surface-0/80 backdrop-blur-xl">
      <div class="flex items-center justify-between max-w-6xl mx-auto px-6 h-14">
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-lg bg-accent-violet/20 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.573-3.007-9.963-7.178z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <span class="text-sm font-semibold text-text-primary tracking-tight">Happy Vision</span>
          <span v-if="version" class="text-[10px] font-medium text-text-tertiary bg-surface-3 px-1.5 py-0.5 rounded-md">v{{ version }}</span>
        </div>

        <div class="flex items-center gap-1 bg-surface-2 rounded-lg p-1">
          <router-link
            v-for="link in navLinks"
            :key="link.to"
            :to="link.to"
            class="relative px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200"
            :class="$route.name === link.name
              ? 'text-text-primary bg-surface-4 shadow-sm'
              : 'text-text-secondary hover:text-text-primary'"
          >
            {{ link.label }}
          </router-link>
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
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useWatchStore } from './stores/watch'

const watchStore = useWatchStore()

const version = ref('')
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

async function checkForUpdate() {
  try {
    const res = await fetch('/api/update/check', { method: 'POST' })
    const data = await res.json()
    update.status = data.status
    update.latestVersion = data.latest_version || ''

    if (data.status === 'available') {
      // Skip banner if user already dismissed this exact version
      const dismissed = localStorage.getItem('hv_dismissed_update')
      if (dismissed === data.latest_version) {
        return
      }
      update.show = true
    }
  } catch {
    // Silently fail — don't bother user if check fails
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
      if (data.status === 'ready' || data.status === 'error') {
        stopPolling()
      }
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

function dismissUpdate() {
  update.show = false
  stopPolling()
  // Remember which version was dismissed so we don't repeatedly bug the user
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

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}

  // Initialize watch store (fetch status, recent, connect SSE)
  watchStore.init()

  // Refresh store state when window comes back from background
  document.addEventListener('visibilitychange', handleVisibilityChange)

  // Check for updates after a short delay (don't block startup)
  setTimeout(checkForUpdate, 2000)
})

onUnmounted(() => {
  stopPolling()
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
