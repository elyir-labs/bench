<template>
  <!-- A model from the shelf (design/bench-print/, A-send and A-clear): how many, in what, and where. The box picks
       the soonest free printer with that filament loaded; Print on sets it up for that printer on the box, and asks if
       its bed is clear before anything starts.
       How it prints (design/bench-how/, A, picked 6 October 2026; docs/bench-how.md): the printer's own choices under
       Print on, kept with the model, so printing it again, queuing it and Whichever is free first all print it the same
       way. The page sets it up for the picked printer as soon as it opens and again once the taps stop, so the time is
       there before Print on, and Print on reuses that setup.
       Look (design/bench-look/, C, picked 10 October 2026): the picture turns and zooms; once the picked printer's setup is
       done, Layers shows that slice cut at a layer; and every printer the box can set the filament up for gets its own time
       on its row, sliced after the picked one.
       Which side down (the printer's own design/orientation/, on the box 11 October 2026): the Lying tile opens the sides
       each part can rest on; the side picked is kept with the model, so every print after lies it so, and the picture
       shows it down. -->
  <section class="bpage">
    <BenchTop title="Print"><router-link :to="{ path: '/print', query: route.query }" class="back">Shelf</router-link></BenchTop>
    <p v-if="!item && loaded" class="gone">That model isn't on the shelf any more.</p>
    <div v-if="item" class="cols">
      <div class="left">
        <h1 class="a-display name on-phone">{{ item.name }}</h1>
        <div class="picbig" :class="{ live: !!tris }">
          <ModelPicture v-if="tris" class="fill" :tris="tris" :color="fil?.color ?? '#8A8D91'" :alt="item.name" plate turnable zoomable :layers="layersPic" />
          <template v-else><img v-if="item.picture" :src="item.picture" alt="" /><span v-else class="ext">{{ item.file }}</span></template>
          <div v-if="tris && canLayers" class="seg" role="radiogroup" aria-label="Show">
            <button type="button" class="seg-opt" :class="{ on: mode === 'model' }" role="radio" :aria-checked="mode === 'model'" @click="mode = 'model'">Model</button>
            <button type="button" class="seg-opt" :class="{ on: mode === 'layers' }" role="radio" :aria-checked="mode === 'layers'" @click="mode = 'layers'">Layers</button>
          </div>
          <input v-if="mode === 'layers' && stack" v-model.number="upTo" class="cut" type="range" min="0" :max="stack.count - 1" step="1"
                 :aria-label="`Layer, of ${stack.count}`" :aria-valuetext="layerWords(stack, upTo)" />
          <span v-if="tris" class="pichint">{{ mode === 'layers' ? (stack ? `${layerWords(stack, upTo)} · ${ready?.name ?? ''}` : layersNote) : 'Drag to turn' }}</span>
        </div>
        <div v-if="mode === 'layers'" class="legend" aria-label="In the layer">
          <span v-for="(n, k) in KIND_NAMES" :key="n" class="key" :class="{ dim: paths && !kindsIn(paths).includes(k) }"><i :style="{ background: KIND_COLORS[k] }"></i>{{ n }}</span>
        </div>
        <div class="copies"><span class="muted">Copies</span>
          <button class="cstep" :disabled="copies <= 1" aria-label="One fewer" @click="copies--">−</button>
          <b class="a-num">{{ copies }}</b>
          <button class="cstep" :disabled="copies >= 50" aria-label="One more" @click="copies++">+</button></div>
        <!-- your filaments (design/bench-material/, B); before any, what's loaded as before -->
        <div v-if="mine.length" class="in"><span class="muted">In</span>
          <div class="mine" role="radiogroup" aria-label="Filament">
            <button v-for="f in fils" :key="f.key" role="radio" :aria-checked="f.key === fil?.key" class="mrow" :class="{ on: f.key === fil?.key }" @click="filKey = f.key">
              <i :style="{ background: f.color ?? 'var(--a-surface-2)' }"></i>
              <span class="t"><b>{{ f.name }}</b><span>{{ f.sub }}</span></span>
              <span v-if="f.key === fil?.key" class="tick" aria-hidden="true">✓</span>
            </button>
            <button class="mrow add" @click="adding = true">+ Add a filament</button>
          </div></div>
        <div v-else-if="fils.length" class="in"><span class="muted">In</span>
          <div class="chips" role="radiogroup" aria-label="Filament">
            <button v-for="f in fils" :key="f.key" role="radio" :aria-checked="f.key === fil?.key" class="chip" :class="{ on: f.key === fil?.key }" @click="filKey = f.key">
              <i :style="{ background: f.color ?? 'var(--a-surface-2)' }"></i>{{ f.name }}</button>
          </div></div>
        <button v-if="!mine.length" class="own" @click="adding = true">Name the filaments you have</button>
        <button class="remove" @click="remove">Take it off the shelf</button>
      </div>
      <div class="right">
        <h1 class="a-display name off-phone">{{ item.name }}</h1>
        <p class="muted sub">{{ item.from && item.last?.at === item.from.at ? `From ${item.from.printer_name}'s Print · ${shelfCard(item, now).line}`
          : item.last ? `Last printed: ${lastLine(item, now)}` : lastLine(item, now) }}</p>
        <p class="label">Print on</p>
        <div class="rows" role="radiogroup" aria-label="Print on">
          <button v-for="(r, n) in rows" :key="r.id" role="radio" :aria-checked="r.id === picked?.id" class="row"
                  :class="{ on: r.id === picked?.id, off: !r.fits }" :disabled="!r.fits" @click="chosen = r.id">
            <span class="t"><b>{{ n === 0 && r.fits && r.free ? 'Whichever is free first' : r.name }}</b>
              <span>{{ n === 0 && r.fits && r.free ? `${r.name} now: ${r.line.replace(/^Free now: /, '')}` : r.line }}</span></span>
            <span v-if="rowTime(r.id)" class="rt a-num">{{ rowTime(r.id) }}</span>
            <svg v-if="r.id === picked?.id" class="check" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
          </button>
        </div>

        <!-- How it prints: four tiles, each opening its sheet -->
        <div class="howhead"><p class="label">How it prints</p><span class="muted">kept with this model</span></div>
        <div class="tiles">
          <button class="tile wide" :disabled="!canPickSide(sides)" @click="sideOpen = true">
            <span class="k">Lying</span>
            <span class="v"><b>{{ sideRow(sides).value }}</b><span>{{ sideRow(sides).line }}</span></span>
            <svg v-if="canPickSide(sides)" class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button v-for="t in tiles" :key="t.id" class="tile" @click="open = t.id">
            <span class="k">{{ t.label }}</span>
            <span class="v"><b>{{ t.value }}</b><span :class="{ link: t.link }">{{ t.line }}</span></span>
            <svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
          </button>
        </div>
        <p v-if="howError" class="bad">{{ howError }}</p>

        <!-- the buttons stay above the tab bar while the page scrolls under them -->
        <div class="acts">
          <button class="a-btn accent go" :disabled="!picked" @click="go">{{ !picked ? 'No printer can take it' : picked.now ? `Print on ${picked.name}` : `Send to ${picked.name}` }}</button>
          <button class="a-btn ghost go" :disabled="!fil || queuing" @click="queueIt">Add to the queue</button>
          <span v-if="picked" class="muted line" :class="{ bad: ready?.state === 'failed' }">{{ underLine }}</span>
        </div>
      </div>
    </div>

    <!-- the four sheets; It's for timed for the printer Print on would use now (A-purpose) -->
    <HowSheets :open="open" :how="how" :name="item?.name ?? ''" :purposes="purposes" :editable="editable" :usual="usualKind"
               :printer="picked?.name ?? null" :values="values" :price="priceOf" :subs="{ purpose: purposeSub }"
               @change="change" @close="open = null" />
    <SideSheet :open="sideOpen" :view="sides" :tris="partsTris" :color="fil?.color ?? '#8A8D91'" :name="item?.name ?? ''"
               :time="ready?.state === 'done' ? costWords(ready.seconds, ready.grams) : ''" :time-note="picked ? `on ${picked.name}` : ''"
               @pick="pickSide" @close="sideOpen = false" />
    <AddFilament :open="adding" @close="adding = false" @added="onAdded" />

    <!-- set up on the box while someone looks at the bed (A-clear) -->
    <div v-if="sheet && setup" class="scrim" @click.self="notYet">
      <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Is ${setup.name}'s bed clear?`">
        <h2 class="a-display">{{ refused ? refused.headline || `${setup.name} says no.` : setup.now ? `Is ${setup.name}'s bed clear?` : `Sending it to ${setup.name}` }}</h2>
        <template v-if="!setup.now">
          <p class="status" :class="setup.sent ? 'done' : setup.state">{{ setup.sent ? `On ${setup.name} now, in its Print.` : status }}</p>
          <p class="muted">{{ setup.name }} is busy. Start it from {{ setup.name }}'s Print once it's free and the bed is clear.</p>
          <div class="acts">
            <router-link v-if="setup.sent" :to="`/p/${setup.printer}/print`" class="a-btn accent grow">Open {{ setup.name }}'s Print</router-link>
            <button class="a-btn ghost" :class="{ grow: !setup.sent }" @click="notYet">Done</button>
          </div>
        </template>
        <template v-else-if="refused && confirm">
          <!-- one spool it isn't sure of: the printer's own question and its own answers, as on its Print -->
          <p v-if="refused.detail" class="muted">{{ refused.detail }}</p>
          <div class="acts"><button class="a-btn accent grow" :disabled="busy" @click="yes">{{ busy ? 'Starting…' : confirm.label }}</button>
            <router-link :to="`/p/${setup.printer}/materials`" class="a-btn ghost">No, it's something else</router-link></div>
        </template>
        <template v-else-if="refused">
          <p class="muted">{{ refused.detail }}</p>
          <div class="acts"><button class="a-btn amber grow" :disabled="busy" @click="start(true)">Print anyway</button><button class="a-btn ghost" @click="notYet">Not now</button></div>
        </template>
        <template v-else>
          <BenchCamera :printer="setup.printer" :name="setup.name" />
          <p class="muted">Take a look at {{ setup.name }}: nothing left on the bed, and nothing in the way.</p>
          <p class="status" :class="setup.state">{{ status }}</p>
          <div class="acts">
            <button class="a-btn accent grow" :disabled="setup.state !== 'done' || busy" @click="start(false)">{{ busy ? 'Starting…' : "It's clear, print" }}</button>
            <button class="a-btn ghost" @click="notYet">Not yet</button>
          </div>
          <p class="muted small">Not yet: it stays set up. Print on {{ setup.name }} again when the bed is clear.</p>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { PrintCheck } from '@/intent/types'
import type { SliceOptions } from '@/slice/api'
import type { Purpose, SupportKind } from '@/slice/plan'
import { bench, clientOf, loadQueue } from '../live'
import { choices, filamentFor, firstPick, lastLine, printOn, shelfCard, timeable, type MyFilament, type Printable } from '../shelf'
import { addToQueue, cancelSetup, getLayer, getLayers, getMine, getPrintable, getSetup, getShelf, getSides, getSliceOptions, getUsual, partTris, removeModel, sendSetup, setHow, setSide, startSetup, type ShelfItem } from '../shelf-api'
import { canPickSide, laidPicture, pickOf, sideRow, sidesKey, withSide, type SidesView } from '../sides'
import ModelPicture from '@/components/slice/ModelPicture.vue'
import { KIND_NAMES, kindsIn, layerWords, type LayerPaths, type LayerStack } from '@/look/layers'
import { aboutLine, costWords, howOf, howTiles, mergeHow, minutes, purposeList, setupKey, type HowChange, type Tile } from '../how'
import BenchTop from './BenchTop.vue'
import BenchCamera from './BenchCamera.vue'
import HowSheets from './HowSheets.vue'
import AddFilament from './AddFilament.vue'
import SideSheet from './SideSheet.vue'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)
const item = ref<ShelfItem | null>(null)
const loaded = ref(false)
const printable = ref<Printable>({})
const options = ref<SliceOptions | null>(null)
const copies = ref(1)
const filKey = ref<string | null>(null)
const mine = ref<MyFilament[]>([])
const adding = ref(false)
function onAdded(f: MyFilament) {
  mine.value = [...mine.value.filter((m) => m.id !== f.id), f]
  filKey.value = `mine:${f.id}`
}
const chosen = ref<string | null>(null)
const now = new Date()

onMounted(async () => {
  void getSliceOptions().then((o) => (options.value = o), () => undefined)
  try {
    item.value = (await getShelf()).find((x) => x.id === id) ?? null
    if (item.value?.last && item.value.last.copies > 1) copies.value = item.value.last.copies
  } finally {
    loaded.value = true
  }
  if (item.value) {
    void partTris(item.value).then((t) => { partsTris.value = t.map((x) => (x ? markRaw(x) : null)) }, () => undefined)
    void getSides(item.value.id).then((v) => { if (!sideSaves) sides.value = v }, () => undefined).finally(() => { sidesRead.value = true })
  }
  printable.value = await getPrintable().catch(() => ({}))
  mine.value = await getMine().catch(() => [])
})
const partsTris = shallowRef<(Float32Array | null)[] | null>(null)
const sides = ref<SidesView | null>(null)
const sidesRead = ref(false)      // the first setup waits for the sides, so it isn't sliced twice
const tris = computed(() => {
  const t = partsTris.value ? laidPicture(partsTris.value, sides.value) : null
  return t ? markRaw(t) : null
})

const fils = computed(() => choices(bench.printers, printable.value, mine.value))
// what it was last printed in (the same one of yours, else its material and color, while loaded); else the first
const fil = computed(() => fils.value.find((f) => f.key === filKey.value)
  ?? fils.value.find((f) => f.preset && f.preset === item.value?.last?.filament && f.color === item.value?.last?.color)
  ?? filamentFor(fils.value, item.value?.last?.material, item.value?.last?.color) ?? fils.value[0] ?? null)
const named = computed(() => (fil.value?.preset ? { filament: fil.value.preset, filament_name: fil.value.name } : {}))
const rows = computed(() => printOn(bench.printers, fil.value, printable.value))
const picked = computed(() => rows.value.find((r) => r.fits && r.id === chosen.value) ?? firstPick(rows.value, route.query.on as string | undefined))

// ── how it prints, kept with the model ──
const how = computed(() => howOf(item.value))
const open = ref<Tile['id'] | null>(null)
const purposes = computed(() => purposeList(options.value?.purposes))
const editable = computed(() => options.value?.editable ?? [])
const purposeSub = computed(() => (picked.value ? `Times are for ${picked.value.name}, where it would go now.` : 'No printer can take it now, so there are no times yet.'))
// each printer's own usual supports (its Print's), asked once per printer
const usual = reactive<Record<string, SupportKind>>({})
watch(() => picked.value?.id, (p) => {
  if (p && !(p in usual)) void getUsual(p).then((u) => { usual[p] = u.supports }, () => undefined)
}, { immediate: true })
const usualKind = computed(() => (picked.value ? usual[picked.value.id] ?? null : null))
const tiles = computed(() => howTiles(how.value, { purposes: options.value?.purposes, editable: editable.value, usual: usualKind.value, printer: picked.value?.name }))

// A change shows at once and is saved at once; saves go one after another, so the last tap is the one kept, and a
// setup waits for them so it's sliced with what's on screen.
const howError = ref('')
let saving: Promise<unknown> = Promise.resolve()
let saves = 0
function change(c: HowChange) {
  const it = item.value
  if (!it) return
  item.value = { ...it, how: mergeHow(how.value, c) }
  howError.value = ''
  const n = ++saves
  saving = saving.then(() => setHow(it.id, c)).then(
    (back) => { if (n === saves && item.value?.id === back.id) item.value = back },
    (e) => { howError.value = `It couldn't be kept with the model: ${(e as Error).message}` })
}

// Which side down: shown at once, kept in turn with how's saves, so a setup is sliced with the side on screen
const sideOpen = ref(false)
let sideSaves = 0
function pickSide(n: number, normal: number[] | null) {
  const it = item.value, v = sides.value
  if (!it || !v) return
  sides.value = withSide(v, n, normal)
  howError.value = ''
  const k = ++sideSaves
  saving = saving.then(() => setSide(it.id, pickOf(n, normal))).then(
    (back) => { if (k === sideSaves && back.id === item.value?.id) sides.value = back },
    (e) => { howError.value = `It couldn't be kept with the model: ${(e as Error).message}` })
}

// Every setting starts from the model's own, else as the printer prints it (its setup's values)
const values = computed(() => (setup.value?.printer === picked.value?.id && setup.value?.state === 'done' ? setup.value.values : null))

// ── setting it up on the box: as soon as the page opens, and once the taps stop after a change ──
interface Setup {
  key: string; job: string; printer: string; name: string; now: boolean; state: string
  seconds: number | null; grams: number | null; values: Record<string, string> | null; error: string
  asked?: boolean     // Print on (or Send to) was tapped: a busy printer gets the file once it's set up
  sent?: string
}
const setup = ref<Setup | null>(null)
const sheet = ref(false)
const busy = ref(false)
const refused = ref<PrintCheck | null>(null)
let timer = 0
let soon = 0

const key = computed(() => (picked.value && item.value && sidesRead.value ? setupKey(picked.value.id, copies.value, fil.value?.key ?? '', how.value, sidesKey(sides.value)) : ''))
// the setup for what's on screen now, or null while the next one waits for the taps to stop
const ready = computed(() => (setup.value && setup.value.key === key.value ? setup.value : null))
watch(key, () => {
  window.clearTimeout(soon)
  soon = window.setTimeout(() => void prepare(), 700)
}, { immediate: true })

const underLine = computed(() => {
  const p = picked.value, s = ready.value
  if (!p) return ''
  if (!s || (s.state !== 'done' && s.state !== 'failed')) return `Setting it up for ${p.name}…`
  if (s.state === 'failed') return s.error || `It couldn't be set up for ${p.name}.`
  const about = aboutLine(s.seconds, s.grams, p.name)
  const then = p.now ? `It sets it up, then asks if ${p.name}'s bed is clear.` : `It goes on ${p.name}, to start there once it's free.`
  return about ? `${about}. ${then}` : then
})

const status = computed(() => {
  const s = setup.value!
  if (s.state === 'failed') return s.error || `It couldn't be set up for ${s.name}.`
  if (s.state !== 'done') return `Setting it up for ${s.name}…`
  return [`Set up for ${s.name}`, fil.value?.name, minutes(s.seconds), s.grams ? `${Math.round(s.grams)} g` : ''].filter(Boolean).join(' · ')
})

/** Sets the model up for the picked printer, unless it already is for what's on screen. */
async function prepare(asked = false) {
  window.clearTimeout(soon)
  const p = picked.value, it = item.value, k = key.value
  if (!p || !it || !k) return
  const s = setup.value
  if (s && s.key === k && s.state !== 'failed') {
    setup.value = { ...s, name: p.name, now: p.now, asked: s.asked || asked }
    if (asked && setup.value.state === 'done' && !setup.value.now) void sendOnly()
    return
  }
  // the printer it was set up for keeps that slice as its row's time; a time already sliced for this printer is the setup
  if (s?.job && !s.sent) {
    if (s.state === 'done' && s.printer !== p.id) timed.value = { ...timed.value, [s.printer]: { key: s.key, job: s.job, state: 'done', seconds: s.seconds, grams: s.grams } }
    else void cancelSetup(s.job)
  }
  const t = timed.value[p.id]
  if (t && t.key === k && t.job && t.state !== 'failed') {
    const { [p.id]: _, ...rest } = timed.value
    timed.value = rest
    setup.value = { key: k, job: t.job, printer: p.id, name: p.name, now: p.now, state: t.state, seconds: t.seconds, grams: t.grams, values: null, error: '', asked }
    follow()
    return
  }
  window.clearTimeout(timer)
  setup.value = { key: k, job: '', printer: p.id, name: p.name, now: p.now, state: 'queued', seconds: null, grams: null, values: null, error: '', asked }
  await saving                                    // sliced with the model's how as saved
  if (setup.value?.key !== k) return
  try {
    const job = await startSetup(it.id, { printer: p.id, copies: copies.value, material: fil.value?.material ?? 'PLA',
                                          color: fil.value?.color ?? null, slot: p.slot, ...named.value })
    if (setup.value?.key !== k) { void cancelSetup(job.id); return }
    setup.value = { ...setup.value, job: job.id, state: job.state }
    follow()
  } catch (e) {
    if (setup.value?.key === k) setup.value = { ...setup.value, state: 'failed', error: (e as Error).message }
  }
}

async function go() {
  if (!picked.value || !item.value) return
  refused.value = null
  sheet.value = true
  await prepare(true)                             // still set up from before (the page's own, or Not yet): reused
}

function follow() {
  window.clearTimeout(timer)
  const s = setup.value
  if (!s || s.state === 'done' || s.state === 'failed') return
  timer = window.setTimeout(async () => {
    try {
      const j = await getSetup(s.job)
      if (!setup.value || setup.value.job !== s.job) return
      setup.value = { ...setup.value, state: j.state === 'cancelled' ? 'failed' : j.state, seconds: j.estimate?.seconds ?? null,
                      grams: j.estimate?.grams ?? null, values: j.values ?? null, error: j.error ?? '' }
      if (setup.value.state === 'done' && !setup.value.now && setup.value.asked) void sendOnly()
    } catch { /* the box's slicer restarting: look again */ }
    follow()
  }, 700)
}

// A printer that's busy gets the file only: it starts there, once it's free and someone has cleared the bed
async function sendOnly() {
  const s = setup.value
  if (!s || s.sent) return
  try {
    s.sent = (await sendSetup(s.job)).sent
  } catch (e) {
    setup.value = { ...s, state: 'failed', error: (e as Error).message }
  }
}

// It's clear: the file goes to the printer, the printer checks its spools against it (as for any file), and starts
async function start(anyway: boolean) {
  const s = setup.value
  const client = s && clientOf(s.printer)
  if (!s || !client) return
  busy.value = true
  try {
    const sent = s.sent ?? (await sendSetup(s.job)).sent
    s.sent = sent                                   // on the printer now: Print anyway doesn't send it twice
    const state = clientOf(s.printer)?.intent.value?.state
    if (state !== 'ready' && state !== 'finished') {           // it started something else meanwhile: never on top of it
      setup.value = { ...s, state: 'failed', error: `${s.name} isn't free any more. It's on ${s.name}'s Print, to start there later.` }
      return
    }
    if (!anyway) {
      const check = await client.call<PrintCheck>('printer.intent.check_print', { filename: sent }).catch(() => null)
      if (check && (!check.ok || check.colour)) { refused.value = check; return }
    }
    await client.act('start_file', { filename: sent })
    setup.value = null
    sheet.value = false
    await router.push(`/p/${s.printer}`)
  } catch (e) {
    setup.value = { ...s, state: 'failed', error: (e as Error).message }
  } finally {
    busy.value = false
  }
}

// "This file uses Black PLA. Is that what's loaded?": Yes tells the printer and starts, as its own Print's sheet does
const confirm = computed(() => (refused.value?.ask && refused.value.actions?.find((a) => a.id === 'confirm_spool')) || null)
async function yes() {
  const s = setup.value
  const client = s && clientOf(s.printer)
  if (!s || !client || !confirm.value) return
  busy.value = true
  try {
    await client.act('confirm_spool', confirm.value.args ?? {})
    setup.value = null
    sheet.value = false
    refused.value = null
    await router.push(`/p/${s.printer}`)
  } catch (e) {
    setup.value = { ...s, state: 'failed', error: (e as Error).message }
  } finally {
    busy.value = false
  }
}

// ── Look (design/bench-look/, C): Model | Layers, and a time on every row ──
const KIND_COLORS = ['#e0533f', '#f0a35e', '#8e5bd6', '#2bd14a', '#9aa0a8']
const mode = ref<'model' | 'layers'>('model')
const stack = shallowRef<LayerStack | null>(null)
const paths = shallowRef<LayerPaths | null>(null)
const upTo = ref(0)
const layersNote = ref('')
const canLayers = computed(() => ready.value?.state === 'done' && !!ready.value.job)
const layersPic = computed(() => (mode.value === 'layers' && stack.value
  ? { stack: stack.value, upTo: upTo.value, paths: paths.value, color: fil.value?.color ?? '#8A8D91', kindColors: KIND_COLORS } : null))
watch(() => [mode.value, canLayers.value ? ready.value!.job : ''] as const, async ([m, job]) => {
  stack.value = null
  paths.value = null
  if (m !== 'layers') return
  if (!job) { mode.value = 'model'; return }
  layersNote.value = 'Reading the slice…'
  try {
    const s = await getLayers(job)
    if (mode.value !== 'layers' || ready.value?.job !== job) return
    upTo.value = Math.max(0, s.count - 1)
    stack.value = s
  } catch (e) {
    layersNote.value = (e as Error).message
  }
})
let cutTimer = 0
watch(() => [upTo.value, stack.value] as const, ([n, s]) => {
  window.clearTimeout(cutTimer)
  const job = ready.value?.job
  if (!s || !job) return
  cutTimer = window.setTimeout(async () => {
    const got = await getLayer(job, n).catch(() => null)
    if (got && got.n === upTo.value && ready.value?.job === job) paths.value = got
  }, 60)
})

interface Timed { key: string; job: string; state: string; seconds: number | null; grams: number | null }
const timed = ref<Record<string, Timed>>({})
let timing = 0
const timedIds = computed(() => timeable(rows.value, printable.value, fil.value).filter((x) => x !== picked.value?.id))
const keyFor = (pid: string) => (item.value ? setupKey(pid, copies.value, fil.value?.key ?? '', how.value, sidesKey(sides.value)) : '')
/** After the picked printer's own setup: each other printer's, one request each (the box's slicer takes them in turn). */
async function timeOthers() {
  const it = item.value, s = ready.value
  if (!it || (s && s.state !== 'done' && s.state !== 'failed')) return
  await saving
  const want = new Set(timedIds.value)
  for (const [pid, t] of Object.entries(timed.value)) {
    if (!want.has(pid) || t.key !== keyFor(pid)) {
      if (t.job && t.state !== 'done' && t.state !== 'failed') void cancelSetup(t.job)
      const { [pid]: _, ...rest } = timed.value
      timed.value = rest
    }
  }
  for (const pid of want) {
    if (timed.value[pid]) continue
    const k = keyFor(pid), r = rows.value.find((x) => x.id === pid)
    timed.value = { ...timed.value, [pid]: { key: k, job: '', state: 'queued', seconds: null, grams: null } }
    void startSetup(it.id, { printer: pid, copies: copies.value, material: fil.value?.material ?? 'PLA', color: fil.value?.color ?? null,
                             slot: r?.slot ?? null, ...named.value })
      .then((j) => {
        const cur = timed.value[pid]
        if (cur?.key !== k) { void cancelSetup(j.id); return }
        timed.value = { ...timed.value, [pid]: { ...cur, job: j.id, state: j.state } }
        followTimed()
      }, () => { if (timed.value[pid]?.key === k) timed.value = { ...timed.value, [pid]: { key: k, job: '', state: 'failed', seconds: null, grams: null } } })
  }
}
function followTimed() {
  window.clearTimeout(timing)
  timing = window.setTimeout(async () => {
    const waiting = Object.entries(timed.value).filter(([, t]) => t.job && t.state !== 'done' && t.state !== 'failed')
    await Promise.all(waiting.map(async ([pid, t]) => {
      const j = await getSetup(t.job).catch(() => null)
      const cur = timed.value[pid]
      if (!j || cur?.job !== t.job) return
      timed.value = { ...timed.value, [pid]: { ...cur, state: j.state === 'cancelled' ? 'failed' : j.state, seconds: j.estimate?.seconds ?? null, grams: j.estimate?.grams ?? null } }
    }))
    if (Object.values(timed.value).some((t) => t.job && t.state !== 'done' && t.state !== 'failed')) followTimed()
  }, 900)
}
watch(() => [timedIds.value.join(), fil.value?.key, copies.value, JSON.stringify(how.value), sidesKey(sides.value), ready.value?.state] as const, () => void timeOthers())
/** A row's time: the picked printer's from its setup, every other's from its own slice. */
function rowTime(pid: string): string {
  if (pid === picked.value?.id) return ready.value?.state === 'done' ? costWords(ready.value.seconds, ready.value.grams) : ''
  const t = timed.value[pid]
  return t && t.state === 'done' && t.key === keyFor(pid) ? costWords(t.seconds, t.grams) : ''
}

// ── It's for: the chosen purpose is the page's own setup; the other three are sliced with a how override while the
//    sheet is open (not saved), and dropped when it closes ──
interface Priced { job: string; state: string; seconds: number | null; grams: number | null }
const priced = ref<Partial<Record<Purpose, Priced>>>({})
let pricedFor = ''
let pricing = 0
const priceBase = computed(() => (picked.value && item.value ? setupKey(picked.value.id, copies.value, fil.value?.key ?? '', { ...how.value, purpose: 'everyday' }, sidesKey(sides.value)) : ''))

function dropPriced() {
  window.clearTimeout(pricing)
  for (const p of Object.values(priced.value)) if (p?.job) void cancelSetup(p.job)
  priced.value = {}
  pricedFor = ''
}

async function priceOthers() {
  const p = picked.value, it = item.value
  if (open.value !== 'purpose' || !p || !it) return dropPriced()
  if (priceBase.value !== pricedFor) { dropPriced(); pricedFor = priceBase.value }
  const base = pricedFor
  await saving
  for (const q of purposeList(null).map((x) => x.id)) {
    if (q === how.value.purpose || priced.value[q]) continue
    priced.value = { ...priced.value, [q]: { job: '', state: 'queued', seconds: null, grams: null } }
    void startSetup(it.id, { printer: p.id, copies: copies.value, material: fil.value?.material ?? 'PLA', color: fil.value?.color ?? null,
                             slot: p.slot, how: { purpose: q }, ...named.value })
      .then((j) => {
        if (pricedFor !== base) { void cancelSetup(j.id); return }
        priced.value = { ...priced.value, [q]: { ...priced.value[q]!, job: j.id, state: j.state } }
        followPriced()
      }, () => { if (pricedFor === base) priced.value = { ...priced.value, [q]: { job: '', state: 'failed', seconds: null, grams: null } } })
  }
}

function followPriced() {
  window.clearTimeout(pricing)
  pricing = window.setTimeout(async () => {
    const waiting = Object.entries(priced.value).filter(([, p]) => p?.job && p.state !== 'done' && p.state !== 'failed')
    await Promise.all(waiting.map(async ([q, p]) => {
      const j = await getSetup(p!.job).catch(() => null)
      const cur = priced.value[q as Purpose]
      if (!j || cur?.job !== p!.job) return
      priced.value = { ...priced.value, [q]: { ...cur, state: j.state === 'cancelled' ? 'failed' : j.state, seconds: j.estimate?.seconds ?? null, grams: j.estimate?.grams ?? null } }
    }))
    if (Object.values(priced.value).some((p) => p && p.state !== 'done' && p.state !== 'failed')) followPriced()
  }, 800)
}

watch(() => [open.value === 'purpose', priceBase.value, how.value.purpose] as const, ([on]) => { if (on) void priceOthers(); else dropPriced() })

/** A purpose's time and grams on the printer it would go to: the page's setup for the chosen one, else its own slice. */
function priceOf(q: Purpose): string {
  if (!picked.value) return ''
  const s = ready.value
  if (q === how.value.purpose && s?.state === 'done') return costWords(s.seconds, s.grams)
  const p = priced.value[q]
  if (p?.state === 'done') return costWords(p.seconds, p.grams)
  if (p?.state === 'failed' || (q === how.value.purpose && s?.state === 'failed')) return '—'
  return '…'
}

// Queue A: it waits for the first printer that's free with its filament; the box sets it up then, and asks for the bed
const queuing = ref(false)
async function queueIt() {
  if (!item.value || !fil.value) return
  queuing.value = true
  try {
    await addToQueue({ shelf: item.value.id, copies: copies.value, material: fil.value.material, color: fil.value.color, ...named.value })
    await loadQueue()
    await router.push({ path: '/print', query: route.query })
  } finally {
    queuing.value = false
  }
}

function notYet() {
  sheet.value = false
  refused.value = null
}

async function remove() {
  if (!item.value) return
  await removeModel(item.value.id).catch(() => undefined)
  await router.push({ path: '/print', query: route.query })
}

onBeforeUnmount(() => {
  window.clearTimeout(timer)
  window.clearTimeout(soon)
  dropPriced()
  if (setup.value?.job && !setup.value.sent) void cancelSetup(setup.value.job)
  window.clearTimeout(timing)
  window.clearTimeout(cutTimer)
  for (const t of Object.values(timed.value)) if (t.job && t.state !== 'done' && t.state !== 'failed') void cancelSetup(t.job)
})
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 14px; position: relative; }
.back { color: var(--a-accent-text); font-weight: 650; font-size: 20px; text-decoration: none; }
.back::before { content: '‹ '; }
.gone { color: var(--a-ink-3); font-size: 22px; }
.muted { color: var(--a-ink-3); }
.bad { color: var(--a-red-text); }
.cols { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 32px; align-items: start; }
.left { display: grid; gap: 16px; }
.picbig { height: 300px; border-radius: 22px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); box-shadow: var(--a-card-shadow); display: grid; place-items: center; overflow: hidden; }
.picbig img { max-width: 86%; max-height: 270px; object-fit: contain; }
.picbig { position: relative; }
.picbig.live { background: none; }
.picbig :deep(.fill) { position: absolute; inset: 0; }
.picbig .seg { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); display: flex; padding: 4px; gap: 4px; border-radius: 99px;
  background: color-mix(in srgb, var(--a-surface-2) 92%, transparent); z-index: 2; }
.seg-opt { appearance: none; border: 0; font: inherit; font-weight: 600; font-size: 15px; min-height: 36px; padding: 0 16px; border-radius: 99px;
  background: transparent; color: var(--a-ink-2); cursor: pointer; }
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.cut { position: absolute; right: 8px; top: 60px; bottom: 46px; width: 32px; margin: 0; writing-mode: vertical-lr; direction: rtl; accent-color: var(--a-accent); z-index: 2; }
.pichint { position: absolute; left: 12px; bottom: 10px; padding: 5px 12px; border-radius: 99px; font-size: 13px; color: var(--a-ink-2); pointer-events: none;
  background: color-mix(in srgb, var(--a-surface) 92%, transparent); box-shadow: var(--a-card-shadow); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 14px; color: var(--a-ink-2); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 12px; height: 12px; border-radius: 50%; }
.key.dim { opacity: 0.4; }
.rt { flex: none; margin-left: auto; padding-left: 12px; font-size: 17px; font-weight: 650; white-space: nowrap; }
.row.off .rt { color: var(--a-ink-3); }
.ext { color: var(--a-ink-3); font-size: 18px; }
.copies { display: flex; align-items: center; gap: 14px; font-size: 18px; }
.copies .muted { flex: 1; }
.copies b { font-size: 26px; width: 34px; text-align: center; }
.cstep { width: 52px; height: 52px; border-radius: 50%; border: 1px solid var(--a-line); background: var(--a-surface); color: var(--a-ink-2); font: inherit; font-size: 26px; cursor: pointer; }
.cstep:disabled { opacity: .4; cursor: default; }
.in { display: grid; gap: 8px; font-size: 18px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { display: inline-flex; align-items: center; gap: 8px; border: 0; border-radius: 999px; padding: 8px 14px; font: inherit; font-size: 16px; font-weight: 650; background: var(--a-surface); color: var(--a-ink-2); cursor: pointer; }
.chip i { width: 14px; height: 14px; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(0,0,0,.2); }
.chip.on { background: var(--a-ink); color: var(--a-bg); }
.mine { display: grid; gap: 1px; margin-top: 6px; border-radius: 16px; overflow: auto; max-height: 230px; background: var(--a-line); box-shadow: var(--a-card-shadow); }
.mrow { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px; padding: 10px 14px; background: var(--a-surface); }
.mrow.on { box-shadow: inset 0 0 0 2px var(--a-accent); }
.mrow i { width: 16px; height: 16px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 1px rgba(0,0,0,.15); }
.mrow .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.mrow .t b { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrow .t span { font-size: 13px; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrow .tick { color: var(--a-accent); font-weight: 800; }
.mrow.add { color: var(--a-accent-text); font-weight: 650; font-size: 15px; }
.remove { justify-self: start; border: 0; background: none; padding: 4px 0; font: inherit; font-size: 16px; color: var(--a-ink-3); text-decoration: underline; cursor: pointer; }
.right { display: grid; gap: 12px; align-content: start; }
.on-phone { display: none; }
.name { margin: 0; font-size: 40px; line-height: 1.05; letter-spacing: -.025em; }
.sub { margin: 0 0 4px; font-size: 19px; }
.label { margin: 4px 0 0; color: var(--a-ink-3); font-size: 16px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.rows { display: grid; gap: 10px; }
.row { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 16px;
       padding: 14px 20px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.row.on { box-shadow: 0 0 0 3px var(--a-accent), var(--a-card-shadow); }
.row.off { opacity: .5; cursor: default; }
.t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.t b { font-size: 21px; } .t span { color: var(--a-ink-3); font-size: 17px; }
.check { width: 28px; height: 28px; flex: none; fill: none; stroke: var(--a-accent); stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
/* How it prints: the tiles (A-model) */
.howhead { display: flex; align-items: baseline; gap: 12px; margin-top: 6px; }
.howhead .label { margin: 0; }
.howhead .muted { font-size: 15px; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tile { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: grid; grid-template-columns: 92px minmax(0, 1fr) 18px;
        gap: 10px; align-items: center; padding: 11px 16px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.tile .k { color: var(--a-ink-3); font-size: 16px; }
.tile.wide { grid-column: 1 / -1; }
.tile:disabled { cursor: default; }
.tile .v { display: grid; min-width: 0; }
.tile .v b { font-size: 19px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tile .v span { font-size: 14px; color: var(--a-ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tile .v span.link { color: var(--a-accent-text); font-weight: 650; }
.chev { width: 18px; height: 18px; fill: none; stroke: var(--a-ink-3); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.tile:focus-visible, .row:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.right > .bad { margin: 0; font-size: 16px; }
/* the buttons and their line stay in view above the tab bar (they were cut off under it on the box's own screen) */
.acts { display: flex; align-items: center; gap: 14px; margin-top: 4px; position: sticky; bottom: 0; z-index: 2;
        padding: 16px 0 14px; background: linear-gradient(transparent, var(--a-bg) 14px); }
.go { width: auto; flex: none; white-space: nowrap; height: 58px; font-size: 21px; padding: 0 28px; }
.acts > .line { flex: 1; min-width: 0; font-size: 16px; line-height: 1.3; }
.own { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; text-align: left; padding: 2px 0 0; justify-self: start; font-size: 14.5px; color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; }
.scrim { position: fixed; inset: 0; background: rgba(16, 20, 28, .42); display: grid; place-items: center; z-index: 20; padding: 16px; }
.sheet { width: min(640px, 100%); box-sizing: border-box; background: var(--a-surface); border-radius: 24px; padding: 28px 30px; display: grid; gap: 14px; box-shadow: var(--a-card-shadow); }
.sheet h2 { margin: 0; font-size: 34px; letter-spacing: -.02em; }
.sheet p { margin: 0; font-size: 18px; }
.status { font-weight: 650; color: var(--a-ink-2); }
.status.done { color: var(--a-green-text); } .status.failed { color: var(--a-red-text); }
.sheet .acts { margin: 0; position: static; padding: 0; background: none; flex-wrap: wrap; }
.sheet a.a-btn { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; box-sizing: border-box; } .sheet .a-btn { height: 62px; font-size: 21px; padding: 0 28px; } .grow { flex: 1; }
.small { font-size: 15px !important; }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 24px; gap: 10px; }
  .cols { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .picbig { height: 180px; } .picbig img { max-height: 160px; }
  .picbig.live { height: 300px; }
  .name { font-size: 28px; } .sub { font-size: 15px; }
  .on-phone { display: block; } .off-phone { display: none; }
  .row { padding: 10px 14px; border-radius: 14px; } .t b { font-size: 17px; } .t span { font-size: 14px; }
  .tiles { grid-template-columns: minmax(0, 1fr); gap: 8px; }
  .tile { grid-template-columns: 76px minmax(0, 1fr) 16px; padding: 10px 14px; border-radius: 14px; }
  .tile .k { font-size: 14px; } .tile .v b { font-size: 17px; } .tile .v span { font-size: 13px; }
  .howhead .muted { font-size: 13px; }
  .acts { position: static; flex-wrap: wrap; padding: 4px 0 0; background: none; gap: 10px; }
  .go { height: 54px; font-size: 18px; width: 100%; } .acts > .line { flex-basis: 100%; font-size: 14px; }
  .sheet { padding: 20px; } .sheet h2 { font-size: 24px; } .sheet p { font-size: 15px; } .sheet .a-btn { height: 52px; font-size: 17px; }
}
</style>
