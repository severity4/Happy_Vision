<template>
  <section
    v-if="jobs.length > 0 || batchModeEnabled"
    class="border border-border-default bg-surface-1 rounded-md p-5"
  >
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <span class="led" :class="hasActive ? 'led-accent' : 'led-ok'"></span>
        <span class="kicker" style="color: var(--color-text-primary)">BATCH JOBS · 非同步批次</span>
      </div>
      <div class="flex items-center gap-3">
        <button
          v-if="batchModeEnabled && currentFolder"
          @click="openEstimate"
          class="bg-accent-violet hover:bg-accent-violet-dim text-white font-mono text-[10px] tracking-wider px-3 py-1.5 rounded transition-colors"
          title="送出目前資料夾為批次 (24h 內完成,省 50%)"
        >📦 送批次</button>
        <span class="font-mono text-[10px] text-text-tertiary">{{ summaryLabel }}</span>
      </div>
    </div>
    <div class="space-y-2">
      <div
        v-for="job in jobs"
        :key="job.job_id"
        class="border border-border-default rounded bg-surface-2 p-3"
      >
        <div class="flex items-center justify-between gap-3 mb-2">
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <span class="led" :class="ledClass(job.status)"></span>
            <span class="font-mono text-[11px] text-text-primary truncate">
              {{ job.display_name || jobShortId(job.job_id) }}
            </span>
          </div>
          <span class="font-mono text-[10px] tracking-wider" :class="stateColor(job.status)">
            {{ stateLabel(job.status) }}
          </span>
        </div>
        <div class="flex items-center justify-between text-[10px] text-text-tertiary">
          <span class="font-mono">
            {{ job.completed_count || 0 }} / {{ job.photo_count }} 完成
            <span v-if="job.failed_count" class="text-warning ml-1">· {{ job.failed_count }} 失敗</span>
          </span>
          <span class="font-mono">
            {{ etaLabel(job) }}
          </span>
        </div>
        <div class="h-1 bg-surface-3 rounded mt-2 overflow-hidden">
          <div
            class="h-full transition-all"
            :class="progressColor(job.status)"
            :style="{ width: progressPercent(job) + '%' }"
          ></div>
        </div>
        <div v-if="isActive(job.status)" class="mt-2 flex justify-end">
          <button
            @click="cancelJob(job.job_id)"
            class="font-mono text-[10px] tracking-wider text-text-tertiary hover:text-warning transition-colors"
          >取消此 Job</button>
        </div>
        <div v-if="job.error_message" class="mt-2 text-[10px] text-warning font-mono">
          ⚠ {{ job.error_message }}
        </div>
      </div>
    </div>
    <div v-if="jobs.length > 0" class="mt-3 text-center">
      <button
        @click="showAll = !showAll"
        class="font-mono text-[10px] tracking-wider text-text-tertiary hover:text-text-primary"
      >{{ showAll ? '只看進行中' : '全部顯示' }}</button>
    </div>
    <div
      v-else-if="batchModeEnabled"
      class="text-center py-3 text-[11px] text-text-tertiary"
    >
      目前沒有 batch jobs。有目前監控資料夾時點「📦 送批次」提交。
    </div>

    <BatchEstimateModal
      :open="estimateOpen"
      :folder="currentFolder"
      @close="estimateOpen = false"
      @submitted="onSubmitted"
    />
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useWatchStore } from '../stores/watch'
import { pushToast } from '../utils/toast.js'
import BatchEstimateModal from './BatchEstimateModal.vue'

const settings = useSettingsStore()
const watchStore = useWatchStore()

const batchModeEnabled = computed(() => {
  const mode = settings.settings?.batch_mode
  return mode === 'auto' || mode === 'always'
})

const currentFolder = computed(() => {
  return watchStore.folder || settings.settings?.watch_folder || ''
})

const estimateOpen = ref(false)
function openEstimate() {
  if (!currentFolder.value) {
    pushToast('請先設定監控資料夾', { kind: 'info' })
    return
  }
  estimateOpen.value = true
}
function onSubmitted() { fetchJobs() }

const jobs = ref([])
const showAll = ref(false)
let es = null
let pollTimer = null

const ACTIVE_STATES = new Set([
  'JOB_STATE_PENDING',
  'JOB_STATE_QUEUED',
  'JOB_STATE_RUNNING',
])

const STATE_LABELS = {
  JOB_STATE_PENDING: '等候中',
  JOB_STATE_QUEUED: '排隊',
  JOB_STATE_RUNNING: '處理中',
  JOB_STATE_SUCCEEDED: '已完成',
  JOB_STATE_FAILED: '失敗',
  JOB_STATE_CANCELLED: '已取消',
  JOB_STATE_EXPIRED: '已過期',
  JOB_STATE_PARTIALLY_SUCCEEDED: '部分完成',
}

const hasActive = computed(() => jobs.value.some(j => ACTIVE_STATES.has(j.status)))

const summaryLabel = computed(() => {
  const active = jobs.value.filter(j => ACTIVE_STATES.has(j.status)).length
  const total = jobs.value.length
  if (active === 0) return `${total} 個 job`
  return `${active} / ${total} 進行中`
})

function isActive(s) { return ACTIVE_STATES.has(s) }

function stateLabel(s) { return STATE_LABELS[s] || s || '未知' }

function stateColor(s) {
  if (s === 'JOB_STATE_SUCCEEDED') return 'text-success'
  if (s === 'JOB_STATE_PARTIALLY_SUCCEEDED') return 'text-accent-violet'
  if (s === 'JOB_STATE_FAILED' || s === 'JOB_STATE_EXPIRED') return 'text-warning'
  if (s === 'JOB_STATE_CANCELLED') return 'text-text-tertiary'
  return 'text-accent-violet'
}

function progressColor(s) {
  if (s === 'JOB_STATE_SUCCEEDED') return 'bg-success'
  if (s === 'JOB_STATE_FAILED' || s === 'JOB_STATE_EXPIRED') return 'bg-warning'
  return 'bg-accent-violet'
}

function ledClass(s) {
  if (s === 'JOB_STATE_SUCCEEDED') return 'led-ok'
  if (s === 'JOB_STATE_FAILED' || s === 'JOB_STATE_EXPIRED') return 'led-warn'
  if (ACTIVE_STATES.has(s)) return 'led-accent'
  return ''
}

function jobShortId(id) {
  return id?.split('/').pop() || id || '?'
}

function progressPercent(job) {
  if (!job.photo_count) return 0
  const done = (job.completed_count || 0) + (job.failed_count || 0)
  return Math.min(100, Math.round((done / job.photo_count) * 100))
}

function etaLabel(job) {
  if (job.status === 'JOB_STATE_SUCCEEDED') return '✓ 完成'
  if (job.status === 'JOB_STATE_FAILED') return '失敗'
  if (job.status === 'JOB_STATE_EXPIRED') return '逾時 (48h)'
  if (job.status === 'JOB_STATE_CANCELLED') return '已取消'
  if (!job.created_at) return '—'
  try {
    const created = new Date(job.created_at)
    const eta = new Date(created.getTime() + 24 * 60 * 60 * 1000)
    return `SLO ${eta.toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })} 前`
  } catch {
    return '24h SLO'
  }
}

async function fetchJobs() {
  try {
    const url = showAll.value ? '/api/batch/jobs' : '/api/batch/jobs?active=1'
    const res = await fetch(url)
    if (!res.ok) return
    const data = await res.json()
    jobs.value = data.jobs || []
  } catch { /* ignore */ }
}

async function cancelJob(jobId) {
  if (!confirm('確定要取消此 batch job 嗎？已處理的結果會保留。')) return
  try {
    const res = await fetch(`/api/batch/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error()
    pushToast('已請求取消', { kind: 'info' })
    fetchJobs()
  } catch {
    pushToast('取消失敗', { kind: 'error' })
  }
}

function connectSSE() {
  try {
    es = new EventSource('/api/batch/stream')
    es.addEventListener('batch_state', () => fetchJobs())
    es.addEventListener('batch_submitted', () => fetchJobs())
    es.addEventListener('batch_item', () => fetchJobs())
    es.onerror = () => { /* auto-reconnect by EventSource */ }
  } catch { /* ignore */ }
}

onMounted(() => {
  fetchJobs()
  connectSSE()
  // Fallback polling every 30s in case SSE is flaky behind a proxy.
  pollTimer = setInterval(fetchJobs, 30_000)
})

onBeforeUnmount(() => {
  if (es) { try { es.close() } catch {} es = null }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>
