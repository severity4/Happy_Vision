<template>
  <div>
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
      <div>
        <h2 class="text-xl font-semibold text-text-primary tracking-tight">結果</h2>
        <p class="text-sm text-text-secondary mt-1" v-if="results.length">{{ results.length }} 張照片已分析</p>
      </div>
      <div v-if="results.length" class="flex items-center gap-2">
        <button
          @click="writeMetadata"
          class="inline-flex items-center gap-1.5 bg-accent-violet hover:bg-accent-violet-dim text-white px-3.5 py-2 rounded-lg text-xs font-medium transition-all shadow-lg shadow-accent-violet/20"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
          </svg>
          寫入照片 Metadata
        </button>
        <a
          href="/api/export/csv"
          class="inline-flex items-center gap-1.5 bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-2 rounded-lg text-xs font-medium transition-colors"
        >
          匯出 CSV
        </a>
        <a
          href="/api/export/json"
          class="inline-flex items-center gap-1.5 bg-surface-3 hover:bg-surface-4 text-text-primary px-3.5 py-2 rounded-lg text-xs font-medium transition-colors"
        >
          匯出 JSON
        </a>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
    </div>

    <!-- Empty state -->
    <div v-else-if="results.length === 0" class="rounded-xl border border-border-default bg-surface-1 p-12 text-center">
      <div class="w-12 h-12 rounded-xl bg-surface-3 flex items-center justify-center mx-auto mb-4">
        <svg class="w-6 h-6 text-text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
        </svg>
      </div>
      <p class="text-sm text-text-secondary mb-3">尚無結果</p>
      <router-link to="/" class="text-sm font-medium text-accent-violet hover:text-accent-violet-dim transition-colors">
        開始分析
      </router-link>
    </div>

    <!-- Photo grid -->
    <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      <div
        v-for="r in results"
        :key="r.file_path"
        @click="selected = r"
        class="group relative rounded-xl border border-border-default bg-surface-1 overflow-hidden cursor-pointer transition-all duration-200 hover:border-accent-violet/40 hover:bg-surface-2 hover:shadow-lg hover:shadow-accent-violet-glow hover:-translate-y-0.5"
        :class="selected?.file_path === r.file_path ? 'border-accent-violet/60 ring-1 ring-accent-violet/30' : ''"
      >
        <!-- Image -->
        <div class="aspect-[4/3] bg-surface-2 overflow-hidden">
          <img
            :src="`/api/photo?path=${encodeURIComponent(r.file_path)}`"
            class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            loading="lazy"
            @error="$event.target.style.display='none'"
          />
        </div>
        <!-- Info -->
        <div class="p-3">
          <p class="text-sm font-medium text-text-primary truncate leading-tight">{{ r.title }}</p>
          <p class="text-xs text-text-tertiary truncate mt-1">{{ r.category }}</p>
        </div>
        <!-- Hover overlay indicator -->
        <div class="absolute inset-0 bg-accent-violet/5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>
      </div>
    </div>

    <!-- Detail modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="selected"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="selected = null"
        >
          <!-- Backdrop -->
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="selected = null"></div>

          <!-- Modal -->
          <div class="relative bg-surface-1 border border-border-default rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden shadow-2xl">
            <!-- Header -->
            <div class="flex items-start justify-between p-6 pb-0">
              <div class="flex-1 min-w-0 pr-4">
                <h3 class="text-lg font-semibold text-text-primary leading-tight">{{ selected.title }}</h3>
                <p class="text-sm text-text-secondary mt-2 leading-relaxed">{{ selected.description }}</p>
              </div>
              <button
                @click="selected = null"
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
              <div v-if="selected.keywords?.length" class="mb-5">
                <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">關鍵字</p>
                <div class="flex flex-wrap gap-1.5">
                  <span
                    v-for="kw in selected.keywords"
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
                  <p class="text-sm font-medium text-text-primary">{{ selected.category || '--' }}</p>
                </div>
                <div class="bg-surface-2 rounded-lg p-3">
                  <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">場景</p>
                  <p class="text-sm font-medium text-text-primary">{{ selected.scene_type || '--' }}</p>
                </div>
                <div class="bg-surface-2 rounded-lg p-3">
                  <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">氛圍</p>
                  <p class="text-sm font-medium text-text-primary">{{ selected.mood || '--' }}</p>
                </div>
                <div class="bg-surface-2 rounded-lg p-3">
                  <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">人數</p>
                  <p class="text-sm font-medium text-text-primary">{{ selected.people_count ?? '--' }}</p>
                </div>
              </div>

              <!-- Identified people -->
              <div v-if="selected.identified_people?.length" class="mb-5">
                <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">辨識出的人物</p>
                <p class="text-sm text-text-secondary">{{ selected.identified_people.join(', ') }}</p>
              </div>

              <!-- OCR -->
              <div v-if="selected.ocr_text?.length" class="mb-5">
                <p class="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-2">辨識文字</p>
                <p class="text-sm text-text-secondary font-mono bg-surface-2 rounded-lg p-3">{{ selected.ocr_text.join(' | ') }}</p>
              </div>

              <!-- File path -->
              <div class="pt-4 border-t border-border-default">
                <p class="text-[10px] font-medium text-text-tertiary uppercase tracking-wider mb-1">檔案路徑</p>
                <p class="text-xs text-text-tertiary font-mono truncate">{{ selected.file_path }}</p>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const results = ref([])
const loading = ref(true)
const selected = ref(null)

onMounted(async () => {
  const res = await fetch('/api/results')
  const data = await res.json()
  results.value = data.results
  loading.value = false
})

async function writeMetadata() {
  if (!confirm('將 AI 產生的 Metadata 寫入所有照片？原有 Metadata 將會備份。')) return
  const res = await fetch('/api/results/write-metadata', { method: 'POST' })
  const data = await res.json()
  alert(`完成：${data.success} 張寫入成功，${data.failed} 張失敗`)
}
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
