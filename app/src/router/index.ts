import { createRouter, createWebHashHistory, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { BASE } from '@/base'

// The four surfaces a person ever visits. Everything else is behind the
// Advanced door (Mainsail).
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'now', component: () => import('@/pages/NowScreen.vue'), meta: { title: 'Now' } },
  { path: '/print', name: 'print', component: () => import('@/pages/PrintScreen.vue'), meta: { title: 'Print' } },
  // A model from the phone, sliced and ready (design/print-a-model/, C). Part of Print.
  { path: '/print/model', name: 'model', component: () => import('@/pages/ModelScreen.vue'), meta: { title: 'Print' } },
  // Everything on the printer, with filters and search (design/print-library/, B). Part of Print.
  { path: '/print/library', name: 'library', component: () => import('@/pages/LibraryScreen.vue'), meta: { title: 'Print' } },
  { path: '/materials', name: 'materials', component: () => import('@/pages/MaterialsScreen.vue'), meta: { title: 'Materials' } },
  { path: '/care', name: 'care', component: () => import('@/pages/CareScreen.vue'), meta: { title: 'Care' } },
  // Who can reach the printer and who is asking to; the "wants to connect" notification opens it.
  { path: '/phones', name: 'phones', component: () => import('@/pages/PhonesScreen.vue'), meta: { title: 'Phones' } },
  // A phone away opens this from the panel's QR code (App.vue shows PairScreen for it).
  { path: '/pair', name: 'pair', component: { render: () => null } },

  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  // the web demo is static files in a folder: no server to send every path to index.html
  history: import.meta.env.VITE_DEMO === '1' ? createWebHashHistory() : createWebHistory(BASE ? `${BASE}/` : import.meta.env.BASE_URL),
  routes,
})

export default router
