import { createRouter, createWebHistory } from 'vue-router'
import ImportView from './views/ImportView.vue'
import ProgressView from './views/ProgressView.vue'
import ResultsView from './views/ResultsView.vue'
import SettingsView from './views/SettingsView.vue'
import WatchView from './views/WatchView.vue'

const routes = [
  { path: '/', name: 'import', component: ImportView },
  { path: '/watch', name: 'watch', component: WatchView },
  { path: '/progress', name: 'progress', component: ProgressView },
  { path: '/results', name: 'results', component: ResultsView },
  { path: '/settings', name: 'settings', component: SettingsView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
