<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">Analysis Progress</h2>
      <p class="text-sm text-text-secondary mt-1">Real-time photo analysis status</p>
    </div>

    <!-- Empty state -->
    <div v-if="!store.isRunning && store.done === 0" class="rounded-xl border border-border-default bg-surface-1 p-12 text-center">
      <div class="w-12 h-12 rounded-xl bg-surface-3 flex items-center justify-center mx-auto mb-4">
        <svg class="w-6 h-6 text-text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      </div>
      <p class="text-sm text-text-secondary mb-3">No analysis running</p>
      <router-link to="/" class="text-sm font-medium text-accent-violet hover:text-accent-violet-dim transition-colors">
        Start an analysis
      </router-link>
    </div>

    <!-- Progress card -->
    <div v-else class="rounded-xl border border-border-default bg-surface-1 overflow-hidden">
      <!-- Progress section -->
      <div class="p-6">
        <!-- Stats row -->
        <div class="flex items-baseline justify-between mb-3">
          <div class="flex items-baseline gap-2">
            <span class="text-2xl font-bold text-text-primary tabular-nums">
              {{ store.total ? Math.round(store.done / store.total * 100) : 0 }}%
            </span>
            <span class="text-xs text-text-tertiary">complete</span>
          </div>
          <span class="text-xs text-text-secondary tabular-nums">
            {{ store.done }} / {{ store.total }} photos
          </span>
        </div>

        <!-- Progress bar -->
        <div class="relative w-full h-2 bg-surface-3 rounded-full overflow-hidden">
          <div
            class="absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out"
            :class="store.isPaused ? 'bg-warning' : 'bg-accent-violet'"
            :style="{ width: store.total ? `${store.done / store.total * 100}%` : '0%' }"
          ></div>
          <!-- Animated shimmer on active -->
          <div
            v-if="store.isRunning && !store.isPaused"
            class="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer"
            :style="{ width: store.total ? `${store.done / store.total * 100}%` : '0%' }"
          ></div>
        </div>

        <!-- Current file -->
        <p v-if="store.currentFile" class="mt-3 text-xs text-text-tertiary font-mono truncate">
          <span class="text-text-secondary">Processing:</span> {{ store.currentFile }}
        </p>

        <!-- Status indicator -->
        <div v-if="store.isPaused" class="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-warning bg-warning/10 px-2.5 py-1 rounded-md">
          <span class="w-1.5 h-1.5 rounded-full bg-warning"></span>
          Paused
        </div>
      </div>

      <!-- Actions bar -->
      <div class="border-t border-border-default bg-surface-0/50 px-6 py-4 flex items-center gap-2">
        <button
          v-if="store.isRunning && !store.isPaused"
          @click="store.pause()"
          class="inline-flex items-center gap-1.5 bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-2 rounded-lg text-xs font-medium transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25v13.5m-7.5-13.5v13.5" />
          </svg>
          Pause
        </button>
        <button
          v-if="store.isPaused"
          @click="store.resume()"
          class="inline-flex items-center gap-1.5 bg-success/10 hover:bg-success/20 text-success px-3.5 py-2 rounded-lg text-xs font-medium transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
          </svg>
          Resume
        </button>
        <button
          v-if="store.isRunning"
          @click="store.cancel()"
          class="inline-flex items-center gap-1.5 bg-error/10 hover:bg-error/20 text-error px-3.5 py-2 rounded-lg text-xs font-medium transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          Cancel
        </button>
        <router-link
          v-if="!store.isRunning && store.done > 0"
          to="/results"
          class="inline-flex items-center gap-1.5 bg-accent-violet hover:bg-accent-violet-dim text-white px-3.5 py-2 rounded-lg text-xs font-medium transition-colors shadow-lg shadow-accent-violet/20"
        >
          View Results
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </router-link>
      </div>

      <!-- Errors -->
      <div v-if="store.errors.length" class="border-t border-border-default px-6 py-4">
        <button
          @click="errorsExpanded = !errorsExpanded"
          class="flex items-center gap-2 text-xs font-medium text-error hover:text-error/80 transition-colors"
        >
          <svg class="w-3.5 h-3.5 transition-transform" :class="errorsExpanded ? 'rotate-90' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
          {{ store.errors.length }} error{{ store.errors.length > 1 ? 's' : '' }}
        </button>
        <ul v-if="errorsExpanded" class="mt-3 space-y-1 max-h-40 overflow-y-auto">
          <li v-for="err in store.errors" :key="err.file" class="text-xs text-text-tertiary font-mono truncate">
            <span class="text-error/80">{{ err.file }}:</span> {{ err.error }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useAnalysisStore } from '../stores/analysis'

const store = useAnalysisStore()
const errorsExpanded = ref(false)
</script>

<style scoped>
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(200%); }
}
.animate-shimmer {
  animation: shimmer 2s infinite;
}
</style>
