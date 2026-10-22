<template>
  <div class="shell" :class="['state-' + state, 'lay-' + layout, { offline: !connected, bench: benchChrome, framed: embedded && !benchChrome, trying: trial }]" :style="unitStyle">
    <!-- The printer's screen on trial after the phone's Try it (design/getting-started/, C): Keep it here? -->
    <TrialBar v-if="trial" :seconds-left="intent!.printer.screen_trial!.seconds_left" />
    <!-- Tablets and laptops: Now never leaves the screen (design/responsive/, B). -->
    <aside v-if="pane" class="nowpane">
      <!-- framed in the Printers app or a Bench Box, whose own bar names this printer (design/printers-open/, A) -->
      <header v-if="!embedded" class="top">
        <button class="name" v-bind="hold.handlers" :style="{ '--hold': hold.progress.value }" aria-label="Hold to open Advanced">
          <span class="dot"></span>
          <span class="label">{{ printerName }}</span>
          <span class="sep">·</span>
          <span class="status">{{ statusWord }}</span>
          <span class="ring" aria-hidden="true"></span>
        </button>
        <LightButton v-if="lightTop" variant="pill" class="top-light" />
        <div class="clock a-num">{{ clock }}</div>
      </header>
      <NowScreen :layout="layout" />
    </aside>

    <header v-else-if="!embedded" class="top">
      <button
        class="name"
        v-bind="hold.handlers"
        :style="{ '--hold': hold.progress.value }"
        aria-label="Hold to open Advanced"
      >
        <span class="dot"></span>
        <span class="label">{{ printerName }}</span>
        <span class="sep">·</span>
        <span class="status">{{ statusWord }}</span>
        <span class="ring" aria-hidden="true"></span>
      </button>
      <div class="right">
        <Vitals v-if="intent && layout === 'panel'" :intent="intent" />
        <LightButton v-if="lightTop" variant="pill" class="top-light" />
        <div class="clock a-num">{{ clock }}</div>
      </div>
    </header>

    <main class="content">
      <!-- Check and measure a filament unit (design/unit-setup/, B): the flow takes the screen, as drawn, until Done -->
      <UnitCheckFlow v-if="checking" :uc="intent!.unit_check!" />
      <template v-else>
      <nav v-if="pane" class="areas" aria-label="Sections">
        <router-link
          v-for="t in areaTabs" :key="t.to" :to="t.to" class="area"
          :class="{ on: !cameraInPane && isArea(t.to), locked: t.to === '/print' && busy }"
          :aria-disabled="t.to === '/print' && busy ? 'true' : undefined"
          @click="onArea($event, t.to)"
        >{{ t.label }}</router-link>
      </nav>
      <div v-if="cameraInPane" class="pane-camera"><CameraViewer :camera="camera!" inline @close="cameraOpen = false" @fullscreen="cameraFull = true" /></div>
      <router-view v-else v-slot="{ Component, route: r }">
        <transition name="a-fade" mode="out-in">
          <component :is="pane && r.path === '/' ? defaultArea : Component" :key="pane && r.path === '/' ? 'area-default' : r.path" />
        </transition>
      </router-view>
      </template>
    </main>

    <NowBar v-if="layout === 'compact' && route.path !== '/' && !benchChrome && !checking" class="nowbar-slot" />

    <nav v-if="!pane && !benchChrome && !checking" class="tabs" aria-label="Sections">
      <router-link
        v-for="t in tabs" :key="t.to" :to="t.to" class="tab"
        :class="{ attention: t.to === '/' && needsAttention, locked: t.to === '/print' && busy, 'router-link-active': t.to !== '/' && route.path.startsWith(t.to + '/') }"
        :aria-disabled="t.to === '/print' && busy ? 'true' : undefined"
        @click="t.to === '/print' && busy && $event.preventDefault()"
      >
        <span class="icon" v-html="t.icon"></span>
        <span class="tab-label">{{ t.label }}</span>
      </router-link>
    </nav>

    <CameraViewer v-if="cameraOpen && camera && !cameraInPane" :camera="camera" @close="cameraOpen = false" />
    <LightSheet />
    <AdvancedDoor v-if="advancedOpen" :url="advancedUrl" @close="advancedOpen = false" />
    <AskCard />

    <div v-if="!connected" class="offline-note">Connecting to {{ printerName }}…</div>

    <BootScreen v-if="booting" @done="booting = false" />
  </div>
</template>

<script setup lang="ts">
import { preparingWord } from '@/intent/colour'
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import { useLongPress } from '@/composables/useLongPress'
import AdvancedDoor from './AdvancedDoor.vue'
import AskCard from '@/components/door/AskCard.vue'
import { followAsks } from '@/asks'
import BootScreen from '@/boot/BootScreen.vue'
import Vitals from '@/components/now/Vitals.vue'
import { followPanelTheme } from '@/theme'
import { layout, finePointer } from './useLayout'
import { unitFor } from './layout'
import NowScreen from '@/pages/NowScreen.vue'
import PrintScreen from '@/pages/PrintScreen.vue'
import MaterialsScreen from '@/pages/MaterialsScreen.vue'
import NowBar from '@/components/now/NowBar.vue'
import CameraViewer from '@/components/camera/CameraViewer.vue'
import LightButton from '@/components/light/LightButton.vue'
import LightSheet from '@/components/light/LightSheet.vue'
import { lightPlace, nowCameraShown } from '@/intent/light'
import { useCameras } from '@/camera/useCameras'
import { cameraOpen, cameraFull } from '@/camera/viewer'
import { door } from '@/door'
import { benchChrome, embedded } from '@/auth'
import TrialBar from '@/components/setup/TrialBar.vue'
import UnitCheckFlow from '@/components/unitcheck/UnitCheckFlow.vue'
import { flowShown } from '@/intent/unitCheck'

const store = useIntentStore()
const router = useRouter()
const route = useRoute()

// Tablets and laptops get the Now pane beside the other tabs; phones and the panel get tabs.
const pane = computed(() => layout.value === 'split' || layout.value === 'stacked')
const unitStyle = computed(() => {
  const u = unitFor(layout.value)
  return u ? { '--u': u } : undefined
})
const areaTabs = [
  { to: '/print', label: 'Print' },
  { to: '/materials', label: 'Materials' },
  { to: '/care', label: 'Care' },
]
// With Now in its own pane, '/' shows what's next: Print when the printer is free, Materials otherwise.
const defaultArea = computed(() => (store.busy ? MaterialsScreen : PrintScreen))
const defaultPath = computed(() => (store.busy ? '/materials' : '/print'))
function isArea(to: string) {
  return route.path === to || route.path.startsWith(to + '/') || (route.path === '/' && to === defaultPath.value)
}
function onArea(e: Event, to: string) {
  if (to === '/print' && busy.value) { e.preventDefault(); return }
  cameraOpen.value = false
}

const { cameras } = useCameras()
const lightTop = computed(() => lightPlace({ light: !!intent.value?.light, cameraOnNow: nowCameraShown.value, embedded }) === 'top')
const camera = computed(() => cameras.value[0] ?? null)
// On a laptop the camera opens in the right-hand pane (with a Full screen button); phones and
// tablets, whichever way up, go straight to full screen.
const cameraInPane = computed(() => cameraOpen.value && !!camera.value && layout.value === 'split' && finePointer.value && !cameraFull.value)
watch(camera, (c) => { if (!c) cameraOpen.value = false })
watch(cameraOpen, (o) => { if (!o) cameraFull.value = false })

// index.html decides, before anything else runs, whether this page load is the panel waking up
const booting = ref(document.documentElement.dataset.boot === '1')

const intent = computed(() => store.intent)
const connected = computed(() => store.connected)
const state = computed(() => intent.value?.state ?? 'ready')
const printerName = computed(() => intent.value?.printer?.name ?? 'Printer')
const advancedUrl = computed(() => store.advancedUrl)
// Only the panel asks: the trial is about the screen it's on (docs/setup-card.md)
const trial = computed(() => layout.value === 'panel' && !benchChrome && !!intent.value?.printer.screen_trial)
const needsAttention = computed(() => state.value === 'needs_you' || state.value === 'problem')
const busy = computed(() => store.busy)
const checking = computed(() => flowShown(intent.value?.unit_check, door.away))

const statusWord = computed(() => {
  switch (state.value) {
    case 'preparing': return preparingWord(intent.value)
    case 'printing': return 'Printing'
    case 'needs_you': return intent.value?.phase === 'power_hold' ? 'On battery' : 'Needs you'
    case 'finished': return 'Finished'
    case 'problem': return 'Stopped'
    case 'setup': return 'New printer'
    default: return 'Ready'
  }
})

const tabs = [
  { to: '/', label: 'Now', icon: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>' },
  { to: '/print', label: 'Print', icon: '<svg viewBox="0 0 24 24"><path d="M7 8V4.5h10V8M6 16H4.5v-5.5A2.5 2.5 0 0 1 7 8h10a2.5 2.5 0 0 1 2.5 2.5V16H18M7 13h10v6.5H7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>' },
  { to: '/materials', label: 'Materials', icon: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>' },
  { to: '/care', label: 'Care', icon: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.6-7.5-10A4.2 4.2 0 0 1 12 8a4.2 4.2 0 0 1 7.5 2.5c0 5.4-7.5 10-7.5 10z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>' },
]

// The tab and the Home Screen icon carry the printer's name, so two printers stay apart.
watch(printerName, (n) => {
  document.title = n
  document.querySelector('meta[name="apple-mobile-web-app-title"]')?.setAttribute('content', n)
}, { immediate: true })

// Advanced door: hold the printer name for two seconds.
const advancedOpen = ref(false)
// Not from away: Mainsail lives on the home network and the door doesn't carry it.
const hold = useLongPress(2000, () => { if (!door.away && !embedded) advancedOpen.value = true })

// When the printer needs a person, the Now screen wins and Advanced closes.
const attention = (s?: string) => s === 'needs_you' || s === 'problem'
watch(() => intent.value, (now, before) => {
  if (before && now && attention(now.state) && !attention(before.state)) {
    advancedOpen.value = false
    // With a Now pane, Now is already on screen.
    if (!pane.value && router.currentRoute.value.path !== '/') router.push('/')
  }
})

// The panel drifts back to Now after two idle minutes, so nobody returns to a stale page.
const IDLE_RETURN_MS = 2 * 60 * 1000
let idleTimer = 0
function armIdle() {
  window.clearTimeout(idleTimer)
  if (layout.value !== 'panel') return
  idleTimer = window.setTimeout(() => {
    if (!advancedOpen.value && router.currentRoute.value.path !== '/') router.push('/')
  }, IDLE_RETURN_MS)
}

// Clock in the corner, updated on the minute.
const clock = ref('')
let clockTimer = 0
function tickClock() {
  const d = new Date()
  clock.value = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()
}
let stopTheme = () => {}
let stopAsks = () => {}
onMounted(() => {
  document.body.classList.add('elyir-bench')
  stopTheme = followPanelTheme(store.call)
  stopAsks = followAsks(store.on)
  tickClock()
  clockTimer = window.setInterval(tickClock, 10000)
  window.addEventListener('pointerdown', armIdle, { passive: true })
  armIdle()
})
onBeforeUnmount(() => {
  stopTheme()
  stopAsks()
  window.clearInterval(clockTimer)
  window.clearTimeout(idleTimer)
  window.removeEventListener('pointerdown', armIdle)
})
</script>

<style scoped>
.shell {
  position: relative;
  height: 100%;
  min-height: 100dvh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  /* one column the width of the screen: content-sized, the Now bar's long line made every tab 441 px wide
     on a 390 px phone (found 3 October 2026) */
  grid-template-columns: minmax(0, 1fr);
  background:
    radial-gradient(120% 90% at 100% 0%, var(--a-tint), transparent 60%),
    var(--a-bg);
  transition: background 600ms ease;
  --a-tint: transparent;
  --a-state: var(--a-ink-3);
  --tabbar-h: calc(56 * var(--u) + 8px);
}
/* the screen trial's bar takes the top row's place for its two minutes, so the page below keeps its whole
   height (a row added above clipped Print again on the 7" panel) */
.shell.trying > header.top { display: none; }
/* inside a Bench Box: the box draws the top row and the sections (design/bench-box/, D) */
.shell.bench { grid-template-rows: minmax(0, 1fr); --tabbar-h: 0px; padding-top: calc(10 * var(--u) + 4px); }
/* inside the Printers app: its bar names the printer, so no top row here (design/printers-open/, A) */
.shell.framed:not(.lay-split):not(.lay-stacked) { grid-template-rows: minmax(0, 1fr) auto; }
.state-preparing, .state-printing { --a-tint: var(--a-tint-blue); --a-state: var(--a-accent); }
.state-needs_you { --a-tint: var(--a-tint-amber); --a-state: var(--a-amber); }
.state-finished { --a-tint: var(--a-tint-green); --a-state: var(--a-green); }
.state-problem { --a-tint: var(--a-tint-red); --a-state: var(--a-red); }
/* not answering (or turned off, design/power/): the last state's colour would be a claim it can't make */
.shell.offline { --a-tint: transparent; --a-state: var(--a-ink-3); }

.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
  white-space: nowrap;
  gap: 8px;
  padding: calc(14 * var(--u) + 4px) calc(28 * var(--u) + 8px) 0;
  color: var(--a-ink-3);
  font-size: calc(15 * var(--u) + 5px);
}
.name {
  appearance: none;
  background: none;
  border: 0;
  padding: 6px 10px 6px 4px;
  margin-left: -4px;
  color: inherit;
  font: inherit;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  position: relative;
  border-radius: 99px;
  cursor: pointer;
  touch-action: none;
}
.name .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--a-state); box-shadow: 0 0 0 3px color-mix(in srgb, var(--a-state) 25%, transparent); }
.name .label { color: var(--a-ink-2); font-weight: 600; }
.name .sep { opacity: 0.5; }
.name .ring {
  position: absolute;
  inset: 0;
  border-radius: 99px;
  background: linear-gradient(90deg, color-mix(in srgb, var(--a-ink) 14%, transparent) calc(var(--hold, 0) * 100%), transparent 0);
  pointer-events: none;
}
.right { display: flex; align-items: center; gap: calc(18 * var(--u) + 8px); }
.clock { color: var(--a-ink-3); }
@media (max-width: 520px) {
  .right { gap: 10px; }
  .name .sep, .name .status { display: none; }   /* the tint and the tab dot say it */
  .name { min-width: 0; }
}

.content {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.tabs {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  height: var(--tabbar-h);
  padding-bottom: var(--safe-b);
  border-top: 1px solid var(--a-line);
  background: color-mix(in srgb, var(--a-bg) 70%, transparent);
  backdrop-filter: blur(10px);
}
.tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--a-ink-3);
  text-decoration: none;
  font-size: calc(11 * var(--u) + 4px);
  font-weight: 600;
  letter-spacing: 0.02em;
  position: relative;
}
.tab .icon { width: calc(20 * var(--u) + 6px); height: calc(20 * var(--u) + 6px); display: block; }
.tab .icon :deep(svg) { width: 100%; height: 100%; display: block; }
.tab.router-link-active { color: var(--a-ink); }
.tab.locked { color: color-mix(in srgb, var(--a-ink-3) 45%, transparent); cursor: default; }
.tab.attention::after {
  content: '';
  position: absolute;
  top: 8px;
  right: calc(50% - 22px);
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--a-state);
}

.offline-note {
  position: absolute;
  left: 50%; bottom: calc(var(--tabbar-h) + 12px);
  transform: translateX(-50%);
  padding: 8px 14px;
  border-radius: 99px;
  background: var(--a-surface-2);
  color: var(--a-ink-2);
  font-size: 13px;
}

/* ---- off the panel ------------------------------------------------------------------- */
/* The legacy design system's global .label (uppercase, 12 px) was shrinking the printer's name. */
.shell:not(.lay-panel) .name .label { font-size: inherit; text-transform: none; letter-spacing: normal; color: var(--a-ink); font-weight: 700; }
.lay-compact .top { padding: calc(10px + env(safe-area-inset-top, 0px)) 20px 0; font-size: 15px; }
.lay-compact .tabs { height: calc(58px + var(--safe-b)); }
.lay-compact .tab { font-size: 12px; }
.lay-compact .tab .icon { width: 24px; height: 24px; }
.nowbar-slot { position: relative; z-index: 2; }

.lay-split, .lay-stacked { grid-template-rows: none; }
.lay-split { grid-template-columns: clamp(360px, 34vw, 480px) minmax(0, 1fr); height: 100dvh; }
.lay-stacked { grid-template-rows: auto minmax(0, 1fr); height: 100dvh; }
.nowpane { min-height: 0; display: flex; flex-direction: column; }
.lay-split .nowpane {
  border-right: 1px solid var(--a-line);
  background: color-mix(in srgb, var(--a-surface) 40%, transparent);
  overflow-y: auto;
}
.lay-split .nowpane .top, .lay-stacked .nowpane .top { padding: 22px 28px 0; font-size: 16px; }
.lay-split .content, .lay-stacked .content { min-height: 0; overflow: hidden; padding: 0; }
.areas {
  display: inline-flex; align-self: flex-start; gap: 2px;
  margin: 22px 32px 6px; padding: 4px; border-radius: 12px;
  background: color-mix(in srgb, var(--a-ink) 6%, transparent);
}
.lay-stacked .areas { margin: 16px 28px 4px; }
.area {
  padding: 8px 18px; border-radius: 9px;
  font-weight: 600; font-size: 15px; color: var(--a-ink-2); text-decoration: none;
}
.area.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.area.locked { opacity: 0.45; cursor: default; }
.content > :deep(section) { overflow-y: auto; }
.pane-camera { margin: 12px 32px 28px; flex: 1; min-height: 0; }

.a-fade-enter-active, .a-fade-leave-active { transition: opacity 160ms ease; }
.a-fade-enter-from, .a-fade-leave-to { opacity: 0; }
.top-light { margin-right: 10px; }
</style>
