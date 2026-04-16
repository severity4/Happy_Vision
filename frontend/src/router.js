import { createRouter, createWebHistory } from 'vue-router'
import MonitorView from './views/MonitorView.vue'
import SettingsView from './views/SettingsView.vue'

const routes = [
  { path: '/', name: 'monitor', component: MonitorView },
  { path: '/settings', name: 'settings', component: SettingsView },
  // Fallback: redirect unknown routes to home
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
