<template>
  <div>
    <h2 class="text-2xl font-bold mb-6">Analysis Progress</h2>

    <div v-if="!store.isRunning && store.done === 0" class="text-gray-500">
      No analysis running. <router-link to="/" class="text-blue-600">Start one</router-link>.
    </div>

    <div v-else class="bg-white rounded-lg border p-6">
      <div class="mb-4">
        <div class="flex justify-between text-sm text-gray-600 mb-1">
          <span>{{ store.done }} / {{ store.total }} photos</span>
          <span v-if="store.total">{{ Math.round(store.done / store.total * 100) }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-3">
          <div class="bg-blue-600 h-3 rounded-full transition-all duration-300"
               :style="{ width: store.total ? `${store.done / store.total * 100}%` : '0%' }"></div>
        </div>
      </div>

      <p v-if="store.currentFile" class="text-sm text-gray-500 mb-4 truncate">
        Current: {{ store.currentFile }}
      </p>

      <div class="flex gap-2">
        <button v-if="store.isRunning && !store.isPaused" @click="store.pause()"
                class="bg-yellow-500 text-white px-4 py-2 rounded text-sm">Pause</button>
        <button v-if="store.isPaused" @click="store.resume()"
                class="bg-green-600 text-white px-4 py-2 rounded text-sm">Resume</button>
        <button v-if="store.isRunning" @click="store.cancel()"
                class="bg-red-600 text-white px-4 py-2 rounded text-sm">Cancel</button>
        <router-link v-if="!store.isRunning && store.done > 0" to="/results"
                     class="bg-blue-600 text-white px-4 py-2 rounded text-sm">View Results</router-link>
      </div>

      <div v-if="store.errors.length" class="mt-4">
        <h3 class="text-sm font-medium text-red-600 mb-2">Errors ({{ store.errors.length }})</h3>
        <ul class="text-xs text-red-500 max-h-40 overflow-y-auto">
          <li v-for="err in store.errors" :key="err.file">{{ err.file }}: {{ err.error }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useAnalysisStore } from '../stores/analysis'
const store = useAnalysisStore()
</script>
