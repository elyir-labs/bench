<template>
  <!-- Look at a model (design/look/, A with C's layers, picked 9 October 2026). A file from this phone or
       computer, read here: turn it, zoom it, see its parts, show someone, send a picture. Nothing is
       uploaded to look. "How would it print?" asks each paired printer's own slicer, at home, for the slice Ready
       would start with, and sends nothing; "Print on Workshop…" opens Workshop's own Print with the file. Once a printer
       is picked, Layers shows its slice cut at a layer: the walls below, the layer's own paths by kind. -->
  <main class="look" :class="{ shown: !!parts }">
    <template v-if="!parts">
      <header class="bar"><button type="button" class="round" aria-label="Printers" @click="leave">‹</button></header>
      <h1 class="a-display">Look at a model</h1>
      <p class="lead">An STL, 3MF, STEP or OBJ file, from Files or Downloads. It's read on this {{ device }} and stays here.</p>
      <label class="a-btn accent open" :class="{ busy: !!reading }">
        Open a model
        <input type="file" :accept="ACCEPT" :disabled="!!reading" @change="picked" />
      </label>
      <p v-if="reading" class="reading" role="status">
        Reading {{ reading }}…<template v-if="readingStep"> The STEP reader comes first the first time, about 7 MB.</template>
      </p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="!touch" class="drop">Or drop a file anywhere on Printers.</p>

      <section v-if="kept.length" class="recent">
        <h2 class="grp">Looked at lately</h2>
        <div class="list">
          <div v-for="k in kept" :key="k.id" class="row">
            <button type="button" class="open-kept" @click="openKept(k.id)">
              <img class="thumb" :src="k.thumb" alt="" />
              <span class="t"><b>{{ k.name }}</b><span>{{ keptLine(k) }}</span></span>
            </button>
            <button type="button" class="x" :aria-label="`Forget ${k.name}`" @click="drop(k.id)">×</button>
          </div>
        </div>
        <p class="note">Kept on this {{ device }} only.</p>
      </section>
    </template>

    <template v-else>
      <div class="stage" :class="{ showing }" @click="showing && stopShowing()">
        <ModelPicture ref="pic" :tris="shownTris" :color="COLOR" :alt="heading" plate turnable zoomable :spin="showing" :layers="layersPic" class="fill" />
        <div v-if="canLayers && !showing" class="seg-wrap">
          <div class="seg" role="radiogroup" aria-label="Show">
            <button type="button" class="seg-opt" :class="{ on: mode === 'model' }" role="radio" :aria-checked="mode === 'model'" @click.stop="mode = 'model'">Model</button>
            <button type="button" class="seg-opt" :class="{ on: mode === 'layers' }" role="radio" :aria-checked="mode === 'layers'" @click.stop="mode = 'layers'">Layers</button>
          </div>
        </div>
        <input v-if="mode === 'layers' && stack && !showing" v-model.number="upTo" class="cut" type="range" min="0" :max="stack.count - 1" step="1"
               :aria-label="`Layer, of ${stack.count}`" :aria-valuetext="layerWords(stack, upTo)" @click.stop />
        <div v-if="!showing" class="top">
          <button type="button" class="round" aria-label="Back" @click="close">‹</button>
          <b class="file">{{ fileName }}</b>
          <button type="button" class="round" aria-label="Send a picture" @click="send">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" /></svg>
          </button>
        </div>
        <span v-if="!showing && mode === 'layers'" class="hint">{{ stack ? layerWords(stack, upTo) : layersNote }}</span>
        <span v-else-if="!showing" class="hint">Drag to turn · {{ touch ? 'pinch' : 'scroll' }} to zoom</span>
        <span v-else class="hint">Tap to stop</span>
      </div>
      <div class="card">
        <div v-if="mode === 'layers'" class="legend" aria-label="In the layer">
          <span v-for="(name, k) in KIND_NAMES" :key="name" class="key" :class="{ dim: paths && !kindsIn(paths).includes(k) }">
            <i :style="{ background: KIND_COLORS[k] }"></i>{{ name }}
          </span>
        </div>
        <h1>{{ heading }}</h1>
        <p class="sub">{{ sizeLine }}</p>
        <div v-if="parts.length > 1" class="parts" role="group" aria-label="Parts">
          <button type="button" class="part all" :class="{ on: alone === null }" @click="alone = null">
            <span class="thumb all-n">{{ parts.length }}</span><span>All</span>
          </button>
          <button v-for="(p, i) in parts.slice(0, SHOWN_PARTS)" :key="i" type="button" class="part" :class="{ on: alone === i }"
                  @click="alone = alone === i ? null : i">
            <img class="thumb" :src="thumbs[i]" alt="" /><span>{{ p.name }}</span>
          </button>
          <span v-if="parts.length > SHOWN_PARTS" class="more">+{{ parts.length - SHOWN_PARTS }}</span>
        </div>
        <div class="acts">
          <button type="button" class="a-btn" @click="show">Show someone</button>
          <button type="button" class="a-btn" @click="send">Send a picture</button>
        </div>
        <button v-if="!est.open" type="button" class="a-btn accent how-btn" :disabled="!printers.length && !benches.length" @click="ask">
          {{ pickedLine || 'How would it print?' }}
        </button>
        <p class="note">{{ sentNote || (printers.length || benches.length ? `Read on this ${device}. Nothing was uploaded.` : `Read on this ${device}. Add a printer to see how it would print.`) }}</p>

        <div v-if="est.open" class="backdrop" @click="est.open = false"></div>
        <section v-if="est.open" class="how" aria-label="How would it print?">
          <div class="grab" aria-hidden="true"></div>
          <div class="how-top">
            <h2>How would it print?</h2>
            <button type="button" class="x" aria-label="Close" @click="est.open = false">×</button>
          </div>
          <p class="sub">{{ est.slicer ? `Sliced on ${est.slicer} for each printer.` : 'Sliced at home for each printer.' }} Nothing is sent.</p>
          <div class="chips" role="radiogroup" aria-label="It's for">
            <button v-for="o in PURPOSE_CHIPS" :key="o.id" type="button" class="chip" :class="{ on: est.purpose === o.id }"
                    role="radio" :aria-checked="est.purpose === o.id" @click="estimate(current!, o.id)">{{ o.label }}</button>
          </div>
          <template v-for="g in groups" :key="g.key">
            <h3 class="grp">{{ g.title }}</h3>
            <div class="list">
              <button v-for="id in g.ids" :key="id" type="button" class="row est"
                      :class="{ on: est.picked === id, off: est.rows[id]?.kind !== 'done', dim: isDim(id) }"
                      :disabled="est.rows[id]?.kind !== 'done'" @click="est.picked = id">
                <span class="sdot" :style="{ background: dotOf(id) }"></span>
                <span class="t"><b>{{ nameOf(id) }}</b><span>{{ lineOf(id) }}</span></span>
                <span class="r">{{ words(id).time }}<small>{{ words(id).grams }}</small></span>
                <span v-if="est.picked === id" class="tick" aria-hidden="true">✓</span>
              </button>
            </div>
          </template>
          <button v-for="b in keepable" :key="b.id" type="button" class="a-btn how-btn" :disabled="est.kept.includes(b.id)" @click="keepOnBench(b.id)">
            {{ est.kept.includes(b.id) ? `On ${b.name}'s shelf` : `Keep it on ${b.name}'s shelf` }}
          </button>
          <button type="button" class="a-btn accent how-btn" :disabled="!est.picked" @click="printOn">
            {{ !est.picked ? 'Print on…' : est.info[est.picked]?.bench ? `Open on ${benchName(est.picked)} for ${nameOf(est.picked)}…` : `Print on ${nameOf(est.picked)}…` }}
          </button>
          <p v-if="est.picked" class="note">
            {{ est.info[est.picked]?.bench ? `${benchName(est.picked)} sets it up for ${nameOf(est.picked)} and asks if its bed is clear.` : `Opens ${nameOf(est.picked)}'s own Print with this file.` }}
            <button type="button" class="link" @click="seeLayers">See the layers</button>
          </p>
        </section>
      </div>
    </template>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ModelPicture from '@/components/slice/ModelPicture.vue'
import { draw } from '@/slice/render'
import { isStep, sizeWords, title, together, type Part } from '@/look/read.ts'
import { modelName } from '@/slice/plan.ts'
import { ACCEPT, forget, handoff, keep, looked, pending, read, recent, takeShared, type Looked } from '../look'
import { est, estimate, keepOnBench, lineFor, openOnBench, stopEstimates } from '../estimates'
import { benches, printers } from '../printers'
import { rowWords } from '@/look/estimate.ts'
import { KIND_NAMES, kindsIn, layerWords, type LayerPaths, type LayerStack } from '@/look/layers.ts'
import { layerPaths, layerStack } from '../estimates'
import type { Purpose } from '@/slice/plan.ts'

const COLOR = '#d9534f'
const PURPOSE_CHIPS: { id: Purpose; label: string }[] = [
  { id: 'everyday', label: 'Everyday' }, { id: 'draft', label: 'Quick draft' }, { id: 'strong', label: 'Strong' }, { id: 'display', label: 'Looks best' },
]
const SHOWN_PARTS = 24
const route = useRoute()
const router = useRouter()

const touch = matchMedia('(pointer: coarse)').matches
const device = /iPad|Tablet/i.test(navigator.userAgent) ? 'tablet' : touch ? 'phone' : 'computer'

const parts = shallowRef<Part[] | null>(null)
const fileName = ref('')
const thumbs = ref<string[]>([])
const alone = ref<number | null>(null)
const reading = ref('')
const readingStep = ref(false)
const error = ref('')
const kept = ref<Looked[]>([])
const showing = ref(false)
const sentNote = ref('')
const pic = ref<InstanceType<typeof ModelPicture> | null>(null)
const KIND_COLORS = ['#e0533f', '#f0a35e', '#8e5bd6', '#2bd14a', '#9aa0a8']
const mode = ref<'model' | 'layers'>('model')
const stack = shallowRef<LayerStack | null>(null)
const paths = shallowRef<LayerPaths | null>(null)
const upTo = ref(0)
const layersNote = ref('')
const current = shallowRef<File | null>(null)

const all = computed(() => (parts.value ? together(parts.value) : null))
const shownTris = computed(() => (alone.value !== null && parts.value ? parts.value[alone.value].tris : all.value))
const heading = computed(() => {
  if (!parts.value) return ''
  return alone.value !== null ? parts.value[alone.value].name : title(fileName.value, parts.value)
})
const sizeLine = computed(() => {
  if (!parts.value || !shownTris.value) return ''
  const size = sizeWords(shownTris.value)
  if (parts.value.length === 1) return size
  return alone.value !== null ? `${size} · 1 of ${parts.value.length} from ${fileName.value}` : `All together ${size} · from ${fileName.value}`
})

function thumbOf(tris: Float32Array, px = 112): string {
  const c = document.createElement('canvas')
  c.width = c.height = px
  draw(c, tris, COLOR, {}, 0.08)
  return c.toDataURL('image/png')
}

async function open(file: Blob, name: string, keptId?: string) {
  error.value = ''
  reading.value = name
  readingStep.value = isStep(name)
  try {
    const got = await read(file, name)
    fileName.value = name
    stopEstimates()
    current.value = file instanceof File && file.name === name ? file : new File([file], name)
    thumbs.value = got.length > 1 ? got.slice(0, SHOWN_PARTS).map((p) => thumbOf(p.tris)) : []
    alone.value = null
    parts.value = got
    await keep(file, name, got.length, got.length > 1 ? thumbOf(together(got)) : thumbOf(got[0].tris), keptId)
  } catch (e) {
    error.value = (e as Error).message || `${name} couldn't be read.`
  } finally {
    reading.value = ''
    readingStep.value = false
  }
}

function picked(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (f) open(f, f.name)
}

async function openKept(id: string) {
  const k = await looked(id)
  if (k) open(k.file, k.name, k.id)
  else refresh()
}
async function drop(id: string) {
  await forget(id)
  refresh()
}
async function refresh() {
  kept.value = await recent()
}

function keptLine(k: Looked): string {
  const d = new Date(k.at), now = new Date()
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const ago = Math.round((day(now) - day(d)) / 86400000)
  const when = ago === 0 ? 'today' : ago === 1 ? 'yesterday' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  return k.parts > 1 ? `${k.parts} parts · ${when}` : when[0].toUpperCase() + when.slice(1)
}

const nameOf = (id: string) => est.info[id]?.name ?? id
const benchName = (id: string) => benches.find((b) => b.id === est.info[id]?.bench)?.name ?? 'the Bench Box'
const words = (id: string) => rowWords(est.rows[id] ?? { kind: 'queued' })
const lineOf = (id: string) => lineFor(id, words(id).note)
const isDim = (id: string) => { const r = est.rows[id]; return r?.kind === 'done' && r.fits === false }
// a Bench Box's printers under its name, then the printers on their own
const groups = computed(() => {
  const out: { key: string; title: string; ids: string[] }[] = []
  for (const id of est.order) {
    const b = est.info[id]?.bench ?? ''
    const last = out[out.length - 1]
    if (last?.key === b) last.ids.push(id)
    else out.push({ key: b, title: b ? `On ${benchName(id)}` : (out.length ? 'On their own' : parts.value && parts.value.length > 1 ? `${parts.value.length} parts, as the file has them` : 'On each printer'), ids: [id] })
  }
  return out
})
const keepable = computed(() => benches.filter((b) => est.order.some((id) => est.info[id]?.bench === b.id && est.rows[id]?.kind === 'done')))
function dotOf(id: string): string {
  const r = est.rows[id]
  return r?.kind === 'done' ? (r.spool.color ?? 'var(--a-ink-3)') : 'var(--a-line)'
}
function ask() {
  if (est.order.length) est.open = true
  else if (current.value) estimate(current.value)
}
const canLayers = computed(() => !!est.picked && est.rows[est.picked]?.kind === 'done')
const pickedLine = computed(() => {
  if (!canLayers.value || !est.picked) return ''
  const w = words(est.picked)
  return `On ${nameOf(est.picked)}: ${[w.time, w.grams].filter(Boolean).join(' · ')}`
})
function seeLayers() {
  est.open = false
  mode.value = 'layers'
}
const layersPic = computed(() => {
  if (mode.value !== 'layers' || !stack.value || !est.picked) return null
  const r = est.rows[est.picked]
  const color = r?.kind === 'done' && r.spool.color ? r.spool.color : COLOR
  return { stack: stack.value, upTo: upTo.value, paths: paths.value, color, kindColors: KIND_COLORS }
})
// the picked printer's slice: its stack once, then the layer at the cut as the slider settles
watch(() => [mode.value, est.picked, canLayers.value] as const, async ([m, id, ok]) => {
  stack.value = null
  paths.value = null
  if (m !== 'layers') return
  if (!id || !ok) { mode.value = 'model'; return }
  layersNote.value = 'Reading the slice…'
  try {
    const s = await layerStack(id)
    if (!s || est.picked !== id || mode.value !== 'layers') return
    upTo.value = Math.max(0, s.count - 1)
    stack.value = s
  } catch (e) {
    layersNote.value = (e as Error).message
  }
})
let settle = 0
watch(() => [upTo.value, stack.value] as const, ([n, s]) => {
  window.clearTimeout(settle)
  if (!s || !est.picked) return
  const id = est.picked
  settle = window.setTimeout(async () => {
    const got = await layerPaths(id, n)?.catch(() => null)
    if (got && got.n === upTo.value && est.picked === id) paths.value = got
  }, 60)
})
function printOn() {
  const id = est.picked
  if (!id || !current.value) return
  if (est.info[id]?.bench) { void openOnBench(id); return }
  handoff.value = { printer: id, files: [current.value] }
  stopEstimates()
  router.push(`/p/${encodeURIComponent(id)}`)
}

function close() {
  stopEstimates()
  mode.value = 'model'
  showing.value = false
  parts.value = null
  sentNote.value = ''
  if (route.query.r || route.query.shared) router.replace('/look')
  refresh()
}
function leave() {
  if (window.history.state?.back) router.back()
  else router.push('/')
}

function show() {
  showing.value = true
  document.documentElement.requestFullscreen?.().catch(() => {})
}
function stopShowing() {
  showing.value = false
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
}
const onFullscreen = () => { if (!document.fullscreenElement) showing.value = false }

async function send() {
  const blob = await pic.value?.picture()
  if (!blob) return
  const f = new File([blob], `${modelName(fileName.value)}.png`, { type: 'image/png' })
  if (navigator.canShare?.({ files: [f] })) {
    try {
      await navigator.share({ files: [f], title: heading.value })
    } catch {
      // closed the share sheet
    }
    return
  }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(f)
  a.download = f.name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  sentNote.value = `Saved ${f.name} to your downloads.`
}

watch(pending, (f) => {
  if (!f) return
  pending.value = null
  stopShowing()
  open(f, f.name)
}, { immediate: true })

onMounted(async () => {
  document.addEventListener('fullscreenchange', onFullscreen)
  refresh()
  if (route.query.shared) {
    const f = await takeShared()
    if (f) open(f, f.name)
  } else if (typeof route.query.r === 'string') {
    openKept(route.query.r)
  }
})
onBeforeUnmount(() => { document.removeEventListener('fullscreenchange', onFullscreen); stopEstimates() })
</script>

<style scoped>
.look {
  min-height: 100dvh; box-sizing: border-box;
  padding: calc(14px + env(safe-area-inset-top, 0px)) 20px calc(28px + env(safe-area-inset-bottom, 0px));
  max-width: 640px; margin: 0 auto;
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font);
}
.bar { height: 48px; display: flex; align-items: center; }
.round {
  appearance: none; border: 0; width: 44px; height: 44px; border-radius: 50%; flex: none;
  display: grid; place-items: center; font: inherit; font-size: 22px; line-height: 1;
  background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); cursor: pointer;
}
h1.a-display { font-size: 34px; margin: 10px 0 8px; }
.lead { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0 0 22px; }
.open { position: relative; width: 100%; overflow: hidden; cursor: pointer; }
.open input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.open.busy { opacity: 0.6; }
.reading { color: var(--a-ink-2); font-size: 15px; margin: 14px 2px 0; }
.error { color: var(--a-red-text); font-size: 15px; margin: 14px 2px 0; line-height: 1.4; }
.drop { color: var(--a-ink-3); font-size: 14px; margin: 12px 2px 0; text-align: center; }
.grp { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); margin: 30px 2px 8px; }
.list { display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); }
.row { display: flex; align-items: center; background: var(--a-surface); }
.open-kept {
  appearance: none; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 10px 6px 10px 12px;
}
.x { appearance: none; border: 0; background: none; color: var(--a-ink-3); font-size: 22px; width: 48px; height: 48px; cursor: pointer; }
.thumb { width: 48px; height: 48px; border-radius: 10px; flex: none; object-fit: contain; background: radial-gradient(circle at 50% 38%, var(--a-obj-hi), var(--a-obj-lo)); }
.t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.t b { font-size: 16px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.t span { font-size: 13px; color: var(--a-ink-3); }
.note { color: var(--a-ink-3); font-size: 13px; margin: 10px 2px 0; }

/* the model: the picture on top, the card under it; side by side on a wide screen */
.look.shown { max-width: none; padding: 0; }
.stage { position: relative; height: 56dvh; min-height: 300px; }
.stage :deep(.fill) { position: absolute; inset: 0; border-radius: 0; }
.stage.showing { position: fixed; inset: 0; height: auto; z-index: 10; }
.top {
  position: absolute; left: 16px; right: 16px; top: calc(12px + env(safe-area-inset-top, 0px));
  display: flex; align-items: center; gap: 12px;
}
.file { flex: 1; min-width: 0; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hint {
  position: absolute; left: 16px; bottom: 14px; pointer-events: none;
  padding: 7px 14px; border-radius: 99px; font-size: 14px; color: var(--a-ink-2);
  background: color-mix(in srgb, var(--a-surface) 92%, transparent); box-shadow: var(--a-card-shadow);
}
.card { padding: 20px 20px calc(28px + env(safe-area-inset-bottom, 0px)); max-width: 640px; margin: 0 auto; box-sizing: border-box; }
.card h1 { font-size: 26px; margin: 0; letter-spacing: -.01em; overflow-wrap: anywhere; }
.sub { color: var(--a-ink-3); font-size: 15px; margin: 4px 0 0; overflow-wrap: anywhere; }
.parts { display: flex; gap: 8px; overflow-x: auto; margin: 16px -20px 0; padding: 2px 20px 6px; scrollbar-width: none; }
.part {
  appearance: none; border: 0; background: none; font: inherit; cursor: pointer; flex: none; width: 70px;
  display: grid; justify-items: center; gap: 4px; font-size: 11px; color: var(--a-ink-3);
}
.part span { max-width: 70px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.part .thumb { width: 62px; height: 62px; box-shadow: var(--a-card-shadow); }
.part.on .thumb { box-shadow: 0 0 0 2px var(--a-accent); }
.part.on span { color: var(--a-ink); font-weight: 600; }
.all-n { display: grid; place-items: center; font-size: 18px; font-weight: 700; color: var(--a-ink-2); }
.more { flex: none; align-self: start; height: 62px; display: grid; place-items: center; padding: 0 10px; color: var(--a-ink-3); font-weight: 600; }
.acts { display: flex; gap: 10px; margin-top: 18px; }
.acts .a-btn { flex: 1; }
.how-btn { width: 100%; margin-top: 12px; }
.link { appearance: none; border: 0; background: none; padding: 0; font: inherit; color: var(--a-accent-text); text-decoration: underline; cursor: pointer; }
.seg-wrap { position: absolute; left: 0; right: 0; top: calc(70px + env(safe-area-inset-top, 0px)); display: flex; justify-content: center; pointer-events: none; }
.seg { pointer-events: auto; display: flex; padding: 4px; gap: 4px; border-radius: 99px; background: color-mix(in srgb, var(--a-surface-2) 92%, transparent); }
.seg-opt {
  appearance: none; border: 0; font: inherit; font-weight: 600; font-size: 15px; min-height: 36px; padding: 0 16px; border-radius: 99px;
  background: transparent; color: var(--a-ink-2); cursor: pointer;
}
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
/* the cut: a vertical slider down the right of the picture, the top layer at the top */
.cut {
  position: absolute; right: 10px; top: calc(124px + env(safe-area-inset-top, 0px)); bottom: 64px; width: 36px; margin: 0;
  writing-mode: vertical-lr; direction: rtl; accent-color: var(--a-accent); cursor: pointer;
}
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0 0 14px; font-size: 13px; color: var(--a-ink-2); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 12px; height: 12px; border-radius: 50%; }
.key.dim { opacity: 0.4; }
.how { margin-top: 18px; }
.how-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.how h2 { margin: 0; font-size: 22px; letter-spacing: -.01em; }
.grab { display: none; }
.backdrop { display: none; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.chip {
  appearance: none; border: 0; font: inherit; font-size: 15px; font-weight: 600; height: 38px; padding: 0 14px; border-radius: 99px; cursor: pointer;
  background: var(--a-surface); color: var(--a-ink-2); box-shadow: var(--a-card-shadow);
}
.chip.on { background: var(--a-ink); color: var(--a-bg); }
.row.est {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left; width: 100%; cursor: pointer;
  gap: 12px; padding: 12px 14px; min-height: 62px;
}
.row.est:disabled { cursor: default; }
.row.est.on { box-shadow: inset 0 0 0 2px var(--a-accent); }
.row.est .t span { white-space: normal; }
.row.est.off .t b { color: var(--a-ink-2); }
.row.est.dim .r, .row.est.dim .t b { color: var(--a-ink-3); }
.sdot { width: 12px; height: 12px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 1px rgba(0,0,0,.15); }
.r { font-size: 15px; font-weight: 650; white-space: nowrap; text-align: right; }
.r small { display: block; font-size: 12px; font-weight: 500; color: var(--a-ink-3); }
.tick { color: var(--a-accent); font-weight: 800; }

/* on a phone, How would it print? is a sheet over the model */
@media (max-width: 899px) {
  .backdrop { display: block; position: fixed; inset: 0; z-index: 20; background: rgba(8,12,20,.42); }
  .how {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 21; margin: 0; max-height: 82dvh; overflow-y: auto;
    padding: 12px 20px calc(24px + env(safe-area-inset-bottom, 0px));
    background: var(--a-bg); border-radius: 26px 26px 0 0; box-shadow: 0 -10px 40px rgba(8,12,20,.25);
  }
  .grab { display: block; width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 12px; }
}

@media (min-width: 900px) {
  .look.shown { display: grid; grid-template-columns: minmax(0, 1fr) 440px; height: 100dvh; }
  .stage { height: 100dvh; }
  .card { margin: 24px 24px 24px 0; padding: 24px; max-width: none; border-radius: 24px; background: var(--a-surface); box-shadow: var(--a-card-shadow); overflow-y: auto; }
  .parts { flex-wrap: wrap; overflow: visible; margin: 16px 0 0; padding: 0; }
}
</style>
