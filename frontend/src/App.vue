<template>
  <div class="min-h-screen bg-gray-50">
    <nav class="bg-white border-b border-gray-200 px-6 py-3">
      <div class="flex items-center justify-between max-w-6xl mx-auto">
        <h1 class="text-xl font-bold text-gray-900">Happy Vision <span v-if="version" class="text-xs font-normal text-gray-400">v{{ version }}</span></h1>
        <div class="flex gap-4">
          <router-link to="/" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'import' }">Import</router-link>
          <router-link to="/progress" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'progress' }">Progress</router-link>
          <router-link to="/results" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'results' }">Results</router-link>
          <router-link to="/settings" class="text-sm text-gray-600 hover:text-gray-900"
            :class="{ 'text-gray-900 font-medium': $route.name === 'settings' }">Settings</router-link>
        </div>
      </div>
    </nav>
    <main class="max-w-6xl mx-auto px-6 py-8">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const version = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    version.value = data.version || ''
  } catch {}
})
</script>
