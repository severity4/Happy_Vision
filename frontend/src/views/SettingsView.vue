<template>
  <div>
    <!-- Header -->
    <div class="mb-8">
      <h2 class="text-xl font-semibold text-text-primary tracking-tight">Settings</h2>
      <p class="text-sm text-text-secondary mt-1">Configure API keys and analysis options</p>
    </div>

    <!-- Loading -->
    <div v-if="!store.loaded" class="flex items-center justify-center py-20">
      <div class="w-5 h-5 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin"></div>
    </div>

    <div v-else class="max-w-lg space-y-6">
      <!-- API Key -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
            </svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-text-primary">Gemini API Key</h3>
            <p v-if="store.settings.gemini_api_key_set" class="text-xs text-success mt-0.5">
              Active ({{ store.settings.gemini_api_key }})
            </p>
            <p v-else class="text-xs text-text-tertiary mt-0.5">Required for analysis</p>
          </div>
        </div>
        <div class="flex gap-2">
          <input
            v-model="apiKey"
            type="password"
            placeholder="Enter your Gemini API key"
            class="flex-1 bg-surface-0 border border-border-default rounded-lg px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent-violet/40 focus:border-accent-violet/60 transition-all"
          />
          <button
            @click="saveApiKey"
            :disabled="!apiKey"
            class="bg-accent-violet hover:bg-accent-violet-dim disabled:opacity-30 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-all"
          >
            Save
          </button>
        </div>
      </div>

      <!-- Model selection -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">Model</h3>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="model = 'lite'; save({ model: 'lite' })"
            class="relative rounded-lg border p-3 text-left transition-all"
            :class="model === 'lite'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <p class="text-sm font-medium text-text-primary">Flash Lite</p>
            <p class="text-xs text-text-tertiary mt-0.5">Faster, cheaper</p>
            <div v-if="model === 'lite'" class="absolute top-2.5 right-2.5 w-2 h-2 rounded-full bg-accent-violet"></div>
          </button>
          <button
            @click="model = 'flash'; save({ model: 'flash' })"
            class="relative rounded-lg border p-3 text-left transition-all"
            :class="model === 'flash'
              ? 'border-accent-violet/60 bg-accent-violet/5'
              : 'border-border-default bg-surface-0 hover:border-border-strong'"
          >
            <p class="text-sm font-medium text-text-primary">Flash 2.5</p>
            <p class="text-xs text-text-tertiary mt-0.5">Better quality</p>
            <div v-if="model === 'flash'" class="absolute top-2.5 right-2.5 w-2 h-2 rounded-full bg-accent-violet"></div>
          </button>
        </div>
      </div>

      <!-- Concurrency -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
            <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
          </div>
          <h3 class="text-sm font-semibold text-text-primary">Concurrency</h3>
        </div>
        <div class="flex items-center gap-3">
          <input
            v-model.number="concurrency"
            type="range"
            min="1"
            max="20"
            @change="save({ concurrency })"
            class="flex-1 h-1.5 bg-surface-3 rounded-full appearance-none cursor-pointer accent-accent-violet [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-violet [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-accent-violet/30"
          />
          <span class="text-sm font-mono font-semibold text-text-primary w-8 text-right tabular-nums">{{ concurrency }}</span>
        </div>
        <p class="text-xs text-text-tertiary mt-2">Parallel API requests (1-20)</p>
      </div>

      <!-- Skip existing -->
      <div class="rounded-xl border border-border-default bg-surface-1 p-5">
        <label for="skip" class="flex items-center justify-between cursor-pointer">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-accent-violet/10 flex items-center justify-center">
              <svg class="w-4 h-4 text-accent-violet" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 8.689c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062A1.125 1.125 0 013 16.811V8.69zM12.75 8.689c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062a1.125 1.125 0 01-1.683-.977V8.69z" />
              </svg>
            </div>
            <div>
              <p class="text-sm font-semibold text-text-primary">Skip processed</p>
              <p class="text-xs text-text-tertiary mt-0.5">Skip photos that were already analyzed</p>
            </div>
          </div>
          <!-- Toggle switch -->
          <div class="relative">
            <input
              v-model="skipExisting"
              type="checkbox"
              @change="save({ skip_existing: skipExisting })"
              class="sr-only peer"
              id="skip"
            />
            <div class="w-10 h-6 bg-surface-4 peer-checked:bg-accent-violet rounded-full transition-colors"></div>
            <div class="absolute left-0.5 top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform peer-checked:translate-x-4"></div>
          </div>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()
const apiKey = ref('')
const model = ref('lite')
const concurrency = ref(5)
const skipExisting = ref(false)

onMounted(async () => {
  await store.fetchSettings()
  model.value = store.settings.model || 'lite'
  concurrency.value = store.settings.concurrency || 5
  skipExisting.value = store.settings.skip_existing || false
})

async function saveApiKey() {
  if (apiKey.value) {
    await store.updateSettings({ gemini_api_key: apiKey.value })
    apiKey.value = ''
  }
}

async function save(updates) {
  await store.updateSettings(updates)
}
</script>
