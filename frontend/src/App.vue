<template>
  <div class="min-h-screen bg-surface-0">
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
import { ref, onMounted } from 'vue'

const version = ref('')
const navLinks = [
  { to: '/', name: 'import', label: '匯入' },
  { to: '/progress', name: 'progress', label: '進度' },
  { to: '/results', name: 'results', label: '結果' },
  { to: '/settings', name: 'settings', label: '設定' },
]

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}
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
</style>
