// The Bench Box's screen (design/bench-box/, D). Light or dark follows the screen it's on, as the printer app does.
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import '@/styles/elyir-bench.css'
import App from '@/bench-app/App.vue'
import HomePage from '@/bench-app/pages/HomePage.vue'
import PrinterPage from '@/bench-app/pages/PrinterPage.vue'
import SetupPage from '@/bench-app/pages/SetupPage.vue'
import ShelfPage from '@/bench-app/pages/ShelfPage.vue'
import ModelPage from '@/bench-app/pages/ModelPage.vue'
import PlanPage from '@/bench-app/pages/PlanPage.vue'
import SpoolsPage from '@/bench-app/pages/SpoolsPage.vue'
import CarePage from '@/bench-app/pages/CarePage.vue'
import JoinPage from '@/bench-app/pages/JoinPage.vue'
import PairPage from '@/bench-app/pages/PairPage.vue'
import AwayModel from '@/bench-app/pages/AwayModel.vue'
import { startBench } from '@/bench-app/live'
import { checkHere, here } from '@/bench-app/here'
import { tabsFor } from '@/bench-app/away'

const want = new URLSearchParams(location.search).get('theme')
const light = want ? want === 'light' : window.matchMedia('(prefers-color-scheme: light)').matches
document.documentElement.dataset.theme = light ? 'light' : 'dark'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomePage },
    { path: '/p/:id/:area?', component: PrinterPage },
    { path: '/setup', component: SetupPage },
    { path: '/print', component: ShelfPage },
    { path: '/print/plan', component: PlanPage },
    // resolved after the guard below has waited for /door/me: away, a model is looked at and queued, never set up
    { path: '/print/:id', component: () => Promise.resolve(here.away ? AwayModel : ModelPage) },
    { path: '/join', component: JoinPage },
    { path: '/pair', component: PairPage },
    { path: '/spools', component: SpoolsPage },
    { path: '/care', component: CarePage },
  ],
})

// away (the box's public name), the page waits to know who it's for; at home /door/me isn't there
const asked = checkHere().then(() => { if (!here.away || here.paired) startBench() })
router.beforeEach(async (to) => {
  await asked
  if (!here.away || to.path === '/join' || to.path === '/pair') return true
  if (to.path === '/setup') return '/'
  const tab = '/' + to.path.split('/')[1]
  return tab === '/p' || tabsFor(here).includes(tab) ? true : '/'
})

createApp(App).use(router).mount('#app')
