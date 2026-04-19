<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
        @click.self="cancel"
      >
        <div class="bg-surface-1 border border-border-default rounded-lg p-7 max-w-xl w-full shadow-2xl">
          <div class="flex items-center justify-between mb-5">
            <div class="flex items-center gap-2">
              <span class="led led-accent"></span>
              <span class="kicker" style="color: var(--color-text-primary)">
                BATCH SUBMIT · 成本預覽
              </span>
            </div>
            <button
              @click="cancel"
              class="text-text-tertiary hover:text-text-primary font-mono text-sm"
            >✕</button>
          </div>

          <div v-if="loading" class="py-10 text-center">
            <p class="kicker text-text-secondary">估算中...</p>
          </div>

          <div v-else-if="error" class="py-6">
            <p class="kicker text-warning">⚠ {{ error }}</p>
          </div>

          <div v-else-if="estimate" class="space-y-5">
            <!-- Big numbers row -->
            <div class="grid grid-cols-3 gap-3">
              <div class="bg-surface-2 border border-border-default rounded p-3 text-center">
                <p class="kicker text-text-tertiary mb-1">照片數</p>
                <p class="font-mono text-2xl font-semibold text-accent-violet">
                  {{ estimate.photo_count.toLocaleString() }}
                </p>
                <p class="text-[10px] text-text-tertiary mt-1">
                  掃描 {{ estimate.scanned_count.toLocaleString() }} 張
                </p>
              </div>
              <div class="bg-surface-2 border border-border-default rounded p-3 text-center">
                <p class="kicker text-text-tertiary mb-1">批次費用</p>
                <p class="font-mono text-2xl font-semibold text-success">
                  ${{ estimate.batch_cost_usd.toFixed(2) }}
                </p>
                <p class="text-[10px] text-text-tertiary mt-1">
                  NT${{ Math.round(estimate.twd_per_batch) }}
                </p>
              </div>
              <div class="bg-surface-2 border border-border-default rounded p-3 text-center">
                <p class="kicker text-text-tertiary mb-1">預計完成</p>
                <p class="font-mono text-2xl font-semibold text-text-primary">
                  {{ estimate.hours_slo }}h
                </p>
                <p class="text-[10px] text-text-tertiary mt-1">
                  SLO 內(通常更快)
                </p>
              </div>
            </div>

            <!-- Savings callout -->
            <div class="bg-success/10 border border-success/30 rounded p-3">
              <p class="text-sm text-text-primary">
                <span class="font-mono font-semibold text-success">
                  省 ${{ estimate.savings_usd.toFixed(2) }}
                </span>
                <span class="text-text-secondary">
                  · vs 即時模式
                  <span class="font-mono">${{ estimate.realtime_cost_usd.toFixed(2) }}</span>
                  (Batch API 折扣 50%)
                </span>
              </p>
            </div>

            <!-- Breakdown -->
            <div class="bg-surface-2 border border-border-default rounded p-4 space-y-2 text-[11px]">
              <div class="flex justify-between font-mono">
                <span class="text-text-tertiary">模型</span>
                <span class="text-text-primary">{{ estimate.model_name }}</span>
              </div>
              <div class="flex justify-between font-mono">
                <span class="text-text-tertiary">圖片長邊</span>
                <span class="text-text-primary">{{ estimate.image_max_size }}px</span>
              </div>
              <div class="flex justify-between font-mono">
                <span class="text-text-tertiary">每張平均 tokens</span>
                <span class="text-text-primary">
                  in {{ estimate.avg_input_tokens }} · out {{ estimate.avg_output_tokens }}
                  <span class="text-text-tertiary ml-1">
                    ({{ estimate.source === 'history' ? `歷史 N=${estimate.sample_size}` : '估算' }})
                  </span>
                </span>
              </div>
              <div class="flex justify-between font-mono">
                <span class="text-text-tertiary">拆分 jobs</span>
                <span class="text-text-primary">
                  {{ estimate.chunks }} 個 · 每個最多 3000 張
                </span>
              </div>
              <div
                v-if="estimate.skipped_processed || estimate.skipped_rating"
                class="flex justify-between font-mono"
              >
                <span class="text-text-tertiary">已過濾</span>
                <span class="text-text-primary">
                  <span v-if="estimate.skipped_processed">
                    已處理 {{ estimate.skipped_processed.toLocaleString() }}
                  </span>
                  <span v-if="estimate.skipped_rating" class="ml-2">
                    rating 不足 {{ estimate.skipped_rating.toLocaleString() }}
                  </span>
                </span>
              </div>
            </div>

            <!-- Tier 1 reminder -->
            <div class="bg-amber-900/10 border border-amber-700/30 rounded p-3">
              <p class="text-[11px] text-text-secondary leading-relaxed">
                ⚠ 需要 Google AI Studio 付費 Tier 1 帳號。若送出後收到 PERMISSION_DENIED,
                請到
                <button
                  @click="openBilling"
                  class="text-accent-violet hover:underline"
                >AI Studio 綁定信用卡</button>
                。
              </p>
            </div>

            <!-- Actions -->
            <div class="flex justify-end gap-2 pt-2">
              <button
                @click="cancel"
                class="bg-surface-3 hover:bg-surface-4 text-text-primary font-mono text-[11px] tracking-wider px-5 py-2 rounded transition-colors"
              >取消</button>
              <button
                @click="confirm"
                :disabled="estimate.photo_count === 0 || submitting"
                class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-25 disabled:cursor-not-allowed text-white font-mono text-[11px] tracking-wider px-5 py-2 rounded transition-colors"
              >
                {{ submitting ? '送出中...' : `確認送出 (${estimate.photo_count.toLocaleString()} 張)` }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { pushToast } from '../utils/toast.js'

const props = defineProps({
  open: Boolean,
  folder: String,
})
const emit = defineEmits(['close', 'submitted'])

const estimate = ref(null)
const loading = ref(false)
const error = ref('')
const submitting = ref(false)

watch(() => props.open, async (isOpen) => {
  if (!isOpen) {
    estimate.value = null
    error.value = ''
    return
  }
  if (!props.folder) {
    error.value = '未指定資料夾'
    return
  }
  await fetchEstimate()
}, { immediate: true })

async function fetchEstimate() {
  loading.value = true
  error.value = ''
  try {
    const url = `/api/batch/estimate?folder=${encodeURIComponent(props.folder)}`
    const res = await fetch(url)
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || data.message || '估算失敗')
    estimate.value = data
  } catch (e) {
    error.value = e.message || '估算失敗'
  } finally {
    loading.value = false
  }
}

async function confirm() {
  if (!estimate.value || estimate.value.photo_count === 0) return
  submitting.value = true
  try {
    const res = await fetch('/api/batch/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: props.folder }),
    })
    const data = await res.json()
    if (!res.ok) {
      if (data.error === 'tier_required') {
        pushToast('需要付費 Tier 1 帳號,請到 AI Studio 綁定信用卡', { kind: 'error' })
        if (data.billing_url) openBilling(data.billing_url)
      } else {
        pushToast(data.message || '送出失敗', { kind: 'error' })
      }
      return
    }
    pushToast(
      `已送出 ${data.total_photos} 張 → ${data.chunks} 個 batch job`,
      { kind: 'success' },
    )
    emit('submitted', data)
    emit('close')
  } catch (e) {
    pushToast(e.message || '送出失敗', { kind: 'error' })
  } finally {
    submitting.value = false
  }
}

function cancel() {
  if (submitting.value) return
  emit('close')
}

async function openBilling(url = 'https://aistudio.google.com/app/plan_information') {
  try {
    await fetch('/api/system/open_external', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}
</script>

<style scoped>
.modal-enter-active, .modal-leave-active { transition: opacity 180ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
