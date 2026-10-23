<template>
  <section class="care">
    <h1 class="a-display title">Care</h1>
    <BusyBanner then="run a care routine" />
    <!-- Move and heat first (design/hands-on-find/, B): the jobs, then the controls (design/hands-on/, C) -->
    <div class="screen hands" v-if="intent?.hands" :class="{ off: !handsOk }">
      <div class="screen-text"><span class="name">Move and heat</span><span class="when">{{ rowLine(intent.hands, door.away) }}</span></div>
      <button v-if="!door.away" class="a-btn ghost back" :disabled="!handsOk" @click="handsOpen = true">Open</button>
    </div>
    <!-- Filament unit (design/unit-setup/, B): check each slot and measure the tube, on Happy Hare or AFC -->
    <div v-for="r in unitRows" :key="r.key" class="screen wrap unit-row" :class="{ off: !!r.why }">
      <div class="screen-text"><span class="name">{{ unitName(r) }}</span><span class="when">{{ r.why ? r.why : `${r.name}. ${r.line}` }}</span></div>
      <button v-if="!door.away" class="a-btn ghost back" :disabled="!!r.why || store.busyAction !== null" @click="store.act(r.action)">{{ r.action.label }}</button>
    </div>
    <!-- No unit yet: Set one up; a unit Bench set up: the old settings, kept (design/unit-setup/, B, stage 2) -->
    <div v-for="r in setupRows" :key="r.key" class="screen wrap unit-row" :class="{ off: !!r.why }">
      <div class="screen-text"><span class="name">{{ r.name }}</span><span class="when">{{ r.line }}</span></div>
      <button v-if="!door.away" class="a-btn ghost back" :disabled="!!r.why || store.busyAction !== null" @click="store.act(r.action)">{{ r.action.label }}</button>
    </div>
    <h2 class="group" v-if="intent?.hands || unitRows.length || setupRows.length">Maintenance</h2>
    <p class="sub">Small things, now and then, that keep prints looking good. The printer counts its own hours and asks when one is due.</p>
    <ul class="list" v-if="care && care.items.length">
      <li v-for="c in care.items" :key="c.id" :class="{ due: c.due }">
        <div class="row">
          <span class="name">{{ c.name }}</span>
          <span class="when a-num">{{ c.snoozed ? 'Later' : c.label }}</span>
        </div>
        <div class="bar" aria-hidden="true"><i :style="{ width: (c.progress * 100) + '%' }"></i></div>
        <template v-if="c.due">
          <p class="note" v-if="c.note">{{ c.note }}</p>
          <div class="actions">
            <button v-if="allowedHere('care_done')" class="a-btn amber" :disabled="busy || pending === c.id" @click="act('care_done', c.id)">Done</button>
            <button class="a-btn ghost" :disabled="busy || pending === c.id" @click="act('care_later', c.id)">Later</button>
          </div>
          <p v-if="!allowedHere('care_done')" class="note at-printer">Mark it done on the printer's screen once it's done.</p>
        </template>
      </li>
    </ul>
    <p class="sub tiny" v-else-if="intent">{{ care ? 'Nothing to look after yet.' : 'The printer starts counting once its software is updated.' }}</p>
    <p class="sub tiny err" v-if="careError">{{ careError }}</p>
    <!-- Printer › First layer (design/first-layer/, B): what's kept, and the way back -->
    <template v-if="intent?.first_layer">
      <h2 class="group">Printer</h2>
      <div class="screen wrap first-layer">
        <div class="screen-text">
          <span class="name">{{ sheets.length ? 'First layer · every print' : 'First layer' }}</span>
          <span class="when">{{ keptLine(intent.first_layer, intent.printer.name) }}</span>
        </div>
        <button
          v-for="a in backActions" :key="a.id" class="a-btn ghost back"
          :disabled="store.busyAction !== null" @click="goBack(a)"
        >{{ a.label }}</button>
      </div>
      <p class="sub tiny" v-if="backActions.length && intent.first_layer.kept?.back">Before: {{ intent.first_layer.kept.back.words.toLowerCase() }} ({{ intent.first_layer.kept.back.mm }}).</p>
      <!-- design/first-layer-sheets/, C: a sheet that keeps its own first layer -->
      <div v-for="sh in sheets" :key="sh.name" class="screen wrap first-layer">
        <div class="screen-text">
          <span class="name">{{ sh.name }}<i v-if="sh.on" class="on-now">On now</i></span>
          <span class="when">{{ sheetLine(sh) }}</span>
        </div>
        <button
          v-for="a in sh.actions.filter((x) => allowedHere(x.id))" :key="a.id" class="a-btn ghost back"
          :disabled="store.busyAction !== null" @click="goBack(a)"
        >{{ a.label }}</button>
      </div>
      <p class="sub tiny" v-if="intent.first_layer.can_keep && intent.first_layer.kept">{{ sheets.length ? 'Print asks which sheet is on when they differ. ' : '' }}{{ WHERE_KEPT }}</p>
      <p class="sub tiny err" v-if="backError">{{ backError }}</p>
      <!-- Printer › Slicing (design/slicing-elsewhere/, A): who slices for this printer, or who it slices for -->
      <div class="screen" v-if="slicingLine">
        <div class="screen-text"><span class="name">Slicing</span><span class="when">{{ slicingLine }}</span></div>
      </div>
      <div class="screen wrap lends" v-if="lendLine && !door.away">
        <div class="screen-text"><span class="name">Slicing for other printers</span><span class="when">{{ lendLine }}</span></div>
        <button v-for="p in joined" :key="p.id" class="a-btn ghost back" :disabled="stopping === p.id" @click="stop(p)">Stop for {{ p.name }}</button>
      </div>
      <p class="sub tiny err" v-if="stopError">{{ stopError }}</p>
    </template>
    <div class="screen" v-if="!isPanel && !embedded">
      <div class="screen-text">
        <span class="name">Notifications</span>
        <span class="when">{{ pushLine }}</span>
      </div>
      <div class="seg" role="radiogroup" aria-label="Notifications" v-if="pushState === 'on' || pushState === 'off'">
        <button
          v-for="o in pushOptions" :key="o.value" class="seg-opt" role="radio"
          :aria-checked="pushState === o.value" :class="{ on: pushState === o.value }"
          :disabled="pushBusy" @click="setPush(o.value)"
        >{{ o.label }}</button>
      </div>
    </div>
    <p class="sub tiny err" v-if="pushError">{{ pushError }}</p>
    <PhonesCard v-if="!door.away && !embedded" />
    <CloudCard />
    <router-link v-if="embedded" to="/phones" class="screen phones-link">
      <span class="screen-text"><span class="name">Phones</span><span class="when">Who can reach this printer, and who's asking to.</span></span>
      <span class="chev" aria-hidden="true">›</span>
    </router-link>
    <div class="screen" v-if="isPanel">
      <div class="screen-text">
        <span class="name">Printer screen</span>
        <span class="when">Light is easier to read under bright shop lights.</span>
      </div>
      <div class="seg" role="radiogroup" aria-label="Printer screen">
        <button
          v-for="o in themes" :key="o.value" class="seg-opt" role="radio"
          :aria-checked="panelTheme === o.value" :class="{ on: panelTheme === o.value }"
          :disabled="!connected" @click="choose(o.value)"
        >{{ o.label }}</button>
      </div>
    </div>
    <div class="screen wrap" v-else-if="!embedded">
      <div class="screen-text">
        <span class="name">This screen</span>
        <span class="when">Only here. The printer's own screen keeps its setting.</span>
      </div>
      <div class="seg" role="radiogroup" aria-label="This screen">
        <button
          v-for="o in screenThemes" :key="o.value" class="seg-opt" role="radio"
          :aria-checked="screenTheme === o.value" :class="{ on: screenTheme === o.value }"
          @click="setScreenTheme(o.value)"
        >{{ o.label }}</button>
      </div>
    </div>
    <p class="sub tiny err" v-if="themeError">{{ themeError }}</p>
    <div class="screen" v-if="!door.away && !embedded && intent?.printer.screen_switch">
      <div class="screen-text">
        <span class="name">KlipperScreen</span>
        <span class="when">{{ switchLine }}</span>
      </div>
      <div class="actions switch">
        <template v-if="confirmSwitch">
          <button class="a-btn ghost" @click="confirmSwitch = false">Cancel</button>
          <button class="a-btn accent" :disabled="!connected" @click="useKlipperScreen">Switch</button>
        </template>
        <button v-else class="a-btn ghost" :disabled="!connected || switching" @click="confirmSwitch = true">{{ switching ? 'Switching…' : 'Use it' }}</button>
      </div>
    </div>
    <p class="sub tiny err" v-if="switchError || (!door.away && !embedded && intent?.printer.screen_switch_failed)">{{ switchError || intent?.printer.screen_switch_failed }}</p>
    <!-- Turn off (design/power/, A): the last of the printer's rows. The printer cools the nozzle first; Now shows the wait. -->
    <div class="screen wrap power" v-if="intent?.power">
      <div class="screen-text">
        <span class="name">Turn off</span>
        <span class="when">{{ intent.power.allowed ? powerLine : intent.power.why }}</span>
      </div>
      <div class="actions switch">
        <button class="a-btn ghost" :disabled="!canPower" @click="powerAsk = 'restart'">Restart</button>
        <button class="a-btn ghost" :disabled="!canPower" @click="powerAsk = 'off'">Turn off</button>
      </div>
    </div>
    <PowerSheet :kind="powerAsk" @close="powerAsk = null" />
    <HandsSheet :open="handsOpen" @close="handsOpen = false" />
    <!-- Tell Elyir something (design/report/, B): a problem with its report, an idea, a request, anything -->
    <template v-if="!embedded">
      <h2 class="group">Help</h2>
      <div class="screen wrap tell">
        <div class="screen-text">
          <span class="name">Tell Elyir something</span>
          <span class="when">Something wrong, an idea, a request: it all reaches the people who make Elyir Bench.</span>
        </div>
        <button class="a-btn accent back" @click="telling = true">Write to Elyir</button>
      </div>
      <TellSheet :open="telling" :printer-name="intent?.printer.name" @close="telling = false" />
    </template>
    <p class="sub tiny" v-if="intent">Bed {{ Math.round(intent.printer.bed.temperature) }}° · Nozzle {{ Math.round(intent.printer.nozzle.temperature) }}°<template v-if="intent.printer.simulated"> · simulated printer, scenario “{{ intent.printer.scenario }}”</template></p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useIntentStore } from '@/intent/store'
import { isPanel, panelTheme, screenTheme, setPanelTheme, setScreenTheme, type ScreenTheme, type Theme } from '@/theme'
import { disablePush, enablePush, pushStatus, type PushStatus } from '@/push'
import { careOf } from '@/intent/care'
import { allowedHere, door } from '@/door'
import { embedded } from '@/auth'
import PhonesCard from '@/components/door/PhonesCard.vue'
import CloudCard from '@/components/cloud/CloudCard.vue'
import BusyBanner from '@/components/now/BusyBanner.vue'
import PowerSheet from '@/components/now/PowerSheet.vue'
import TellSheet from '@/components/report/TellSheet.vue'
import type { PowerKind } from '@/intent/power'
import { keptLine, sheetLine, WHERE_KEPT } from '@/intent/firstLayer'
import { rowLine } from '@/intent/hands'
import HandsSheet from '@/components/hands/HandsSheet.vue'
import { careRows } from '@/intent/unitCheck'
import { careSetupRows } from '@/intent/unitSetup'
import type { IntentAction } from '@/intent/types'
import { slicerPrinters, slicerStatus, stopPrinter, type SlicerPrinter } from '@/slice/api'
import { careLine, hostLine, type SlicerState } from '@/slice/elsewhere'
const store = useIntentStore()
const intent = computed(() => store.intent)
const handsOpen = ref(false)
const handsOk = computed(() => !!intent.value?.hands && !intent.value.hands.why_not)
const unitRows = computed(() => careRows(intent.value?.units?.list))
const unitName = (r: { name: string; gear: boolean }) => {
  const many = unitRows.value.filter((x) => !x.gear).length > 1
  const base = many ? `Filament unit · ${r.name}` : 'Filament unit'
  return r.gear ? `${base} · The gear` : base
}
const setupRows = computed(() => careSetupRows(intent.value?.unit_setup_offer, intent.value?.unit_putback))

// slicing for this printer elsewhere, or for others here (design/slicing-elsewhere/, A)
const slicing = ref<SlicerState | null>(null)
const joined = ref<SlicerPrinter[]>([])
const stopping = ref<string | null>(null)
const stopError = ref<string | null>(null)
const me = computed(() => intent.value?.printer?.name ?? 'This printer')
const slicingLine = computed(() => (slicing.value ? careLine(slicing.value, me.value) : null))
const lendLine = computed(() => hostLine(joined.value.map(p => p.name), me.value))
async function loadSlicing() {
  slicing.value = await slicerStatus(true)
  const s = slicing.value
  joined.value = s.state === 'ready' && s.slicer?.here
    ? await slicerPrinters().then(d => d.printers.filter(p => p.joined), () => [])
    : []
}
async function stop(p: SlicerPrinter) {
  stopping.value = p.id
  stopError.value = null
  try {
    await stopPrinter(p.id)
    joined.value = joined.value.filter(j => j.id !== p.id)
  } catch (e) {
    stopError.value = (e as Error).message
  } finally {
    stopping.value = null
  }
}
onMounted(() => { void loadSlicing() })
const connected = computed(() => store.connected)

const themes: { value: Theme; label: string }[] = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
]
const screenThemes: { value: ScreenTheme; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  ...themes,
]
const themeError = ref<string | null>(null)
async function choose(t: Theme) {
  themeError.value = null
  try {
    await setPanelTheme(store.call, t)
  } catch {
    themeError.value = "Couldn't save that on the printer. Try again in a moment."
  }
}
// The printer's screen can show KlipperScreen instead, for its menus. KlipperScreen's own
// menu gets an Elyir Bench entry (the installer adds it) to come back.
const confirmSwitch = ref(false)
const telling = ref(false)
// Turn off / Restart (design/power/, A)
const powerAsk = ref<PowerKind | null>(null)
const canPower = computed(() => connected.value && !!intent.value?.power?.allowed && !intent.value?.power?.kind && allowedHere('power_off'))
const powerLine = computed(() => isPanel
  ? 'It lets the nozzle cool first. When its screen goes dark, switch it off.'
  : 'It lets the nozzle cool first. When its screen goes dark, switch it off. It can only be switched on again at the printer.')
const switching = ref(false)
const switchError = ref<string | null>(null)
const switchLine = computed(() => {
  if (switching.value) return isPanel ? 'This screen goes dark for a moment, then shows KlipperScreen.' : "Switching the printer's screen…"
  if (confirmSwitch.value) return isPanel
    ? 'This screen goes dark for a moment. To come back, tap Elyir Bench in its main menu.'
    : "The printer's screen goes dark for a moment, then shows KlipperScreen."
  return isPanel
    ? 'Its menus, on this screen. Tap Elyir Bench in its main menu to come back.'
    : "Show it on the printer's screen instead. Tap Elyir Bench in its main menu to come back."
})
async function useKlipperScreen() {
  confirmSwitch.value = false
  switching.value = true
  switchError.value = null
  await store.act('use_klipperscreen')
  if (store.actionError) {
    switching.value = false
    switchError.value = "Couldn't switch the screen. Try again in a moment."
    return
  }
  // the panel's own page goes away with the switch; a phone just stops saying so
  window.setTimeout(() => { switching.value = false }, 15000)
}

// Phone notifications: only offered where this browser can actually receive them.
const pushState = ref<PushStatus | null>(null)
const pushBusy = ref(false)
const pushError = ref<string | null>(null)
const pushOptions: { value: 'off' | 'on'; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'on', label: 'On' },
]
const pushLine = computed(() => {
  switch (pushState.value) {
    case 'on': case 'off': return 'Tell this phone when a print is done or needs you.'
    case 'needs-install': return 'To get them on this iPhone, tap Share, then Add to Home Screen, and open the printer from there.'
    case 'insecure': return "They need the printer's secure link, which isn't set up yet."
    case 'no-door': return "This printer can't send notifications yet."
    case 'blocked': return 'Notifications are turned off for this page in your browser settings.'
    case 'unsupported': return "This browser can't show notifications from the printer."
    default: return 'Checking…'
  }
})
onMounted(async () => { pushState.value = await pushStatus() })
async function setPush(v: 'on' | 'off') {
  if (v === pushState.value) return
  pushBusy.value = true
  pushError.value = null
  try {
    pushState.value = v === 'on' ? await enablePush() : await disablePush()
  } catch {
    pushError.value = "Couldn't change that. Try again in a moment."
  } finally {
    pushBusy.value = false
  }
}

// The first layer kept for next time, and "Back to how it was" (the value before the last one kept)
const backActions = computed(() => (intent.value?.first_layer?.kept?.actions ?? []).filter((a) => allowedHere(a.id)))
const sheets = computed(() => intent.value?.first_layer?.kept?.sheets ?? [])
const backError = ref<string | null>(null)
async function goBack(a: IntentAction) {
  backError.value = null
  await store.act(a)
  if (store.actionError) backError.value = "Couldn't save that on the printer. Try again in a moment."
}

// Maintenance the printer counts for itself; due tasks get Done and Later.
const care = computed(() => careOf(intent.value))
const busy = computed(() => store.busy)
const pending = ref<string | null>(null)
const careError = ref<string | null>(null)
async function act(action: 'care_done' | 'care_later', id: string) {
  pending.value = id
  careError.value = null
  await store.act(action, { id })
  if (store.actionError) careError.value = "Couldn't save that on the printer. Try again in a moment."
  pending.value = null
}
</script>

<style scoped>
.care { flex: 1; padding: calc(8 * var(--u) + 4px) calc(28 * var(--u) + 8px) calc(16 * var(--u) + 6px); overflow: auto; }
.title { font-size: calc(30 * var(--u) + 8px); margin: 0 0 calc(8 * var(--u) + 4px); }
.sub { color: var(--a-ink-2); font-size: calc(16 * var(--u) + 5px); margin: 0 0 calc(14 * var(--u) + 6px); max-width: 52ch; line-height: 1.4; }
.tiny { color: var(--a-ink-3); font-size: 13px; margin-top: 14px; }
.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-radius: calc(16 * var(--u) + 6px); overflow: hidden; background: var(--a-surface); }
.list li { color: var(--a-ink); display: flex; flex-direction: column; gap: calc(6 * var(--u) + 2px); padding: calc(12 * var(--u) + 5px) calc(16 * var(--u) + 6px); border-top: 1px solid var(--a-line); font-size: calc(17 * var(--u) + 5px); }
.list li:first-child { border-top: 0; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.name { font-weight: 600; }
.when { color: var(--a-ink-3); font-size: 0.85em; }
.row .when { white-space: nowrap; }
.bar { height: 4px; border-radius: 99px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 99px; background: var(--a-ink-3); }
.due .when { color: var(--a-amber-text); font-weight: 600; }
.due .bar i { background: var(--a-amber); }
.note.at-printer { color: var(--a-ink-3); }
.note { margin: 0; color: var(--a-ink-2); font-size: 0.9em; line-height: 1.4; max-width: 60ch; }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); margin-top: 2px; }
.actions .a-btn { flex: 0 1 auto; min-width: calc(110 * var(--u) + 30px); padding-top: calc(10 * var(--u) + 4px); padding-bottom: calc(10 * var(--u) + 4px); font-size: calc(17 * var(--u) + 5px); }
.err { color: var(--a-red-text); }
.group { font-size: calc(13 * var(--u) + 4px); font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--a-ink-3); margin: calc(18 * var(--u) + 6px) 0 0; }
.hands.off .name { color: var(--a-ink-3); }
.unit-row.off .name { color: var(--a-ink-3); }
.first-layer .back, .hands .back, .lends .back, .tell .back, .unit-row .back { flex: none; min-height: 44px; padding: 0 calc(16 * var(--u) + 6px); font-size: calc(15 * var(--u) + 5px); }
.first-layer + .tiny { margin-top: 8px; }
.actions.switch { flex: none; margin-top: 0; }

.screen {
  display: flex; align-items: center; justify-content: space-between; gap: calc(16 * var(--u) + 6px);
  margin-top: calc(12 * var(--u) + 4px);
  padding: calc(12 * var(--u) + 5px) calc(16 * var(--u) + 6px);
  border-radius: calc(16 * var(--u) + 6px);
  background: var(--a-surface);
  font-size: calc(17 * var(--u) + 5px);
}
.screen-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.screen.wrap { flex-wrap: wrap; row-gap: calc(8 * var(--u) + 4px); }   /* three options: they drop below the words on a phone */
.screen.wrap .screen-text { flex: 1 1 200px; }
.phones-link { text-decoration: none; color: var(--a-ink); }
.chev { color: var(--a-ink-3); font-size: 28px; line-height: 1; }
.seg { display: flex; flex: none; padding: 4px; gap: 4px; border-radius: 99px; background: var(--a-surface-2); }
.seg-opt {
  appearance: none; border: 0; margin: 0; font: inherit; font-weight: 600;
  font-size: calc(15 * var(--u) + 5px);
  min-height: 44px; min-width: calc(76 * var(--u) + 24px);
  padding: 0 calc(16 * var(--u) + 6px);
  border-radius: 99px;
  background: transparent; color: var(--a-ink-2);
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease;
}
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.seg-opt[disabled] { opacity: 0.5; cursor: default; }
.seg-opt:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.on-now { font-style: normal; font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 14%, transparent); padding: 2px 8px; border-radius: 999px; margin-left: 8px; vertical-align: 2px; }
</style>
