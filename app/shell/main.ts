// The Printers app. See vite.shell.config.ts and src/shell-app/.
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import '@/styles/elyir-bench.css'
import '@/shell-app/shell.css'   // after elyir-bench.css: pins its sizes for a phone column
import App from '@/shell-app/App.vue'
import HomePage from '@/shell-app/pages/HomePage.vue'
import AddPage from '@/shell-app/pages/AddPage.vue'
import LookPage from '@/shell-app/pages/LookPage.vue'
import YouPage from '@/shell-app/pages/YouPage.vue'

// Light or dark follows the phone; the printers' own screens do the same inside their frames.
const media = window.matchMedia('(prefers-color-scheme: light)')
const applyTheme = () => {
  const t = media.matches ? 'light' : 'dark'
  document.documentElement.dataset.theme = t
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'light' ? '#eceef2' : '#0b0e13')
}
applyTheme()
media.addEventListener('change', applyTheme)
document.body.classList.add('elyir-bench')

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/', component: HomePage },
    { path: '/p/:id', component: HomePage },
    { path: '/add', component: AddPage },
    { path: '/look', component: LookPage },
    { path: '/you', component: YouPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

createApp(App).use(router).mount('#shell')
