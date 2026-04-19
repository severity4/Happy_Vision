<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
        @click.self="close"
      >
        <div class="bg-surface-1 border border-border-default rounded-lg p-6 max-w-2xl w-full shadow-2xl flex flex-col max-h-[80vh]">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-2">
              <span class="led led-error"></span>
              <span class="kicker" style="color: var(--color-text-primary)">
                FAILED · 失敗的照片
              </span>
            </div>
            <button
              @click="close"
              class="text-text-tertiary hover:text-text-primary font-mono text-sm"
            >✕</button>
          </div>

          <div v-if="loading" class="py-8 text-center kicker text-text-secondary">
            載入中...
          </div>

          <div v-else-if="error" class="py-4">
            <p class="kicker text-warning">⚠ {{ error }}</p>
          </div>

          <div v-else-if="items.length === 0" class="py-8 text-center kicker text-text-tertiary">
            目前沒有失敗的照片。
          </div>

          <template v-else>
            <p class="kicker text-text-secondary mb-3">
              {{ items.length }} 張照片分析失敗。重試會清除失敗標記,下次分析會重新送 API。
            </p>

            <div class="flex-1 overflow-y-auto border border-border-default rounded bg-surface-2 mb-4">
              <table class="w-full text-[11px]">
                <thead class="sticky top-0 bg-surface-3">
                  <tr class="border-b border-border-default">
                    <th class="text-left font-mono px-3 py-2 text-text-tertiary tracking-wider">
                      檔案
                    </th>
                    <th class="text-left font-mono px-3 py-2 text-text-tertiary tracking-wider">
                      錯誤
                    </th>
                    <th class="text-left font-mono px-3 py-2 text-text-tertiary tracking-wider w-20">
                      時間
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in items"
                    :key="item.file_path"
                    class="border-b border-border-default/40 last:border-0 hover:bg-surface-3/30"
                  >
                    <td class="font-mono px-3 py-1.5 text-text-primary truncate max-w-[260px]" :title="item.file_path">
                      {{ shortenPath(item.file_path) }}
                    </td>
                    <td class="font-mono px-3 py-1.5 text-warning" :title="item.error_message">
                      {{ humanizeError(item.error_message) }}
                    </td>
                    <td class="font-mono px-3 py-1.5 text-text-tertiary whitespace-nowrap">
                      {{ shortTime(item.updated_at) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <div class="flex justify-end gap-2 pt-1">
            <button
              @click="close"
              class="bg-surface-3 hover:bg-surface-4 text-text-primary font-mono text-[11px] tracking-wider px-5 py-2 rounded transition-colors"
            >關閉</button>
            <button
              v-if="items.length > 0"
              @click="retryAll"
              :disabled="retrying"
              class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-25 text-white font-mono text-[11px] tracking-wider px-5 py-2 rounded transition-colors"
            >
              {{ retrying ? '重新排隊中...' : `🔁 重試全部 ${items.length} 張` }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { humanizeError } from '../utils/errors.js'
import { pushToast } from '../utils/toast.js'

const props = defineProps({
  open: Boolean,
  folder: String,
})
const emit = defineEmits(['close', 'retried'])

const items = ref([])
const loading = ref(false)
const error = ref('')
const retrying = ref(false)

watch(() => props.open, async (isOpen) => {
  if (!isOpen) {
    error.value = ''
    return
  }
  await fetchList()
}, { immediate: true })

async function fetchList() {
  loading.value = true
  error.value = ''
  try {
    const qs = props.folder ? `?folder=${encodeURIComponent(props.folder)}` : ''
    const res = await fetch(`/api/results/failed${qs}`)
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || '載入失敗')
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

async function retryAll() {
  if (items.value.length === 0) return
  // v0.12.1: confirm before clearing. Pure UX guard — the action isn't
  // destructive (we only remove the 'failed' marker, not the photo or
  // prior good results), but 50+ rows at once deserves a second click.
  const ok = window.confirm(
    `確定要重試 ${items.value.length} 張失敗照片嗎?\n\n` +
    `這會清除失敗標記。下次分析執行時(自動監控或手動送批次),這些照片會重新送到 Gemini API。`
  )
  if (!ok) return
  retrying.value = true
  try {
    const res = await fetch('/api/results/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_paths: items.value.map(i => i.file_path),
        folder: props.folder || null,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || data.message || '重試失敗')
    pushToast(
      `已清除 ${data.cleared} 張失敗標記 · 下次分析執行時會自動重跑`,
      { kind: 'success' },
    )
    emit('retried', data)
    emit('close')
  } catch (e) {
    pushToast(e.message || '重試失敗', { kind: 'error' })
  } finally {
    retrying.value = false
  }
}

function close() {
  if (retrying.value) return
  emit('close')
}

function shortenPath(p) {
  if (!p) return ''
  if (p.length <= 50) return p
  return '…' + p.slice(-49)
}

function shortTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
</script>

<style scoped>
.modal-enter-active, .modal-leave-active { transition: opacity 180ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
