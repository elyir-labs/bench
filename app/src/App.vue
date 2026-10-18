<template>
  <component :is="shell" @paired="onPaired" />
  <p v-if="noToken" class="no-token" role="status">{{ benchChrome ? 'The Bench Box' : 'The Printers app' }} didn't hand this printer its access. Close it and open it again.</p>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useConfigStore } from '@/stores/config'
import { useIntentStore } from '@/intent/store'
import { checkDoor, door } from '@/door'
import { benchChrome, embedded, learnParents, linkToShell, receiveToken, reportConnection } from '@/auth'
import AppShell from '@/shell/AppShell.vue'
import PairScreen from '@/pages/PairScreen.vue'
import SetupScreen from '@/setup/SetupScreen.vue'
import BringScreen from '@/components/bring/BringScreen.vue'
import { bringShownFor, followBring } from '@/intent/useBring'
import { followWifi, wifi } from '@/setup/useWifi'
import { isPanel } from '@/theme'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const intentStore = useIntentStore()
const ready = ref(false)
const noToken = ref(false)   // embedded, but the Printers app never handed over access

// /legacy/* renders the old Quasar layout through its own router-view.
const LegacyShell = { render: () => h(RouterView) }
// Reached through a door (home or away name) and not paired: the door lets nothing through but
// pairing, so show only that. The panel and the house Wi-Fi page have no door in front (role null).
const needsPairing = computed(() => door.role !== null && !door.paired)
const Blank = { render: () => h('div', { style: 'min-height:100dvh;background:var(--a-bg)' }) }
const shell = computed(() => {
  // a new printer with no network sets up its Wi-Fi on the panel first (docs/setup.md)
  if (isPanel && !wifi.checked) return Blank
  if (isPanel && wifi.state.mode !== 'off') return SetupScreen
  if (!door.checked) return Blank   // a moment, so an unpaired phone never flashes the app
  if (needsPairing.value || (route.path === '/pair' && door.role !== null)) return PairScreen
  // a fresh card with no printer.cfg: Now the printer itself, instead of Problem (docs/bring-it-over.md)
  if (!route.path.startsWith('/legacy') && bringShownFor(intentStore.intent?.state)) return BringScreen
  return route.path.startsWith('/legacy') ? LegacyShell : AppShell
})

function start() {
  intentStore.start(configStore.moonrakerHost, configStore.moonrakerPort, configStore.moonrakerSSL)
  followBring(intentStore)
}

function onPaired() {
  start()
  router.replace('/')
}

// A file from Look at a model in the Printers app (design/look/): this printer's own Print, as if picked here.
async function takeModels(files: File[]) {
  const until = Date.now() + 10000
  while (!intentStore.intent && Date.now() < until) await new Promise((r) => setTimeout(r, 200))
  const { begin, useMoonraker } = await import('@/slice/session')
  useMoonraker(intentStore.call)
  void begin(files, intentStore.intent?.spools ?? [], intentStore.intent?.printer?.name)
  router.push('/print/model')
}

onMounted(async () => {
  if (isPanel) followWifi()
  try {
    await configStore.loadConfig()
  } catch {
    // config.json is optional; the intent store falls back to the page host
  }
  if (embedded) {
    await learnParents()                   // a Bench Box this printer said yes to may hand over the token too
    const token = await receiveToken()   // inside the Printers app or a Bench Box: its token, then go where it says
    noToken.value = token === null   // '' is an answer: reached without a door (the simulator, a Bench Box in dev)
    linkToShell(() => router.currentRoute.value.fullPath, (p) => router.push(p), takeModels)
    reportConnection(() => intentStore.connected)
  }
  await checkDoor()
  if (route.path === '/pair' && (door.role === null || door.paired)) router.replace('/')   // nothing to pair here
  if (!needsPairing.value) start()
  ready.value = true
})
</script>

<style>
.no-token {
  position: fixed; left: 12px; right: 12px; bottom: calc(var(--tabbar-h, 64px) + 12px); z-index: 70; margin: 0;
  padding: 12px 16px; border-radius: 14px; background: var(--a-surface); color: var(--a-ink);
  box-shadow: var(--a-card-shadow); font: 600 15px/1.4 var(--a-font); text-align: center;
}
</style>
