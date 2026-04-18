<template>
  <Teleport to="body">
    <div class="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 pointer-events-none">
      <TransitionGroup name="toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="pointer-events-auto flex items-center gap-2 px-3.5 py-2 rounded border backdrop-blur-md shadow-lg font-mono text-[12px] min-w-[220px] max-w-[360px]"
          :class="{
            'border-success/40 bg-success/10 text-success': t.kind === 'success',
            'border-error/40 bg-error/10 text-error': t.kind === 'error',
            'border-accent-violet/40 bg-accent-violet/10 text-accent-violet': t.kind === 'info',
          }"
        >
          <span
            class="led flex-shrink-0"
            :class="{
              'led-ok': t.kind === 'success',
              'led-error': t.kind === 'error',
              'led-accent': t.kind === 'info',
            }"
          ></span>
          <span class="flex-1">{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToasts } from '../utils/toast.js'
const toasts = useToasts()
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.24s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(12px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
