<template>
  <!-- Print, on the box (design/bench-print/, A): the shelf. Every model kept here, the last printed first, and Add a
       model. A model opens with how many, in what, and the printer the box picks for it. Above it, what's queued (design/
       bench-queue/, Queue A); below, the models not printed for a while, folded into one row (Tidy A).
       Several at once (design/bench-several/, C): Select, or holding a model, ticks models instead of opening them; the
       bar at the foot plans them (PlanPage). A bed of several in Up next shows each model's picture. -->
  <section class="bpage">
    <BenchTop title="Print" />
    <h1 class="a-display say">{{ selecting ? pickLine(picked.length) : line }}</h1>
    <p v-if="error" class="note" role="alert">{{ error }}</p>

    <div v-if="queue.length" class="queue">
      <p class="label">Up next{{ queue.length > 1 && !here.away ? ' · drag to change the order' : '' }}</p>
      <div ref="rows" class="qrows">
        <div v-for="(q, n) in queue" :key="q.id" class="qrow" :class="{ ready: q.state === 'ready', dragging: drag?.id === q.id }">
          <span v-if="queue.length > 1 && !here.away" class="handle" aria-label="Drag to move" @pointerdown="grab($event, q.id)">⋮⋮</span>
          <b class="n a-num">{{ n + 1 }}</b>
          <span class="qpics" :style="{ width: `${64 + (picsOf(q).length - 1) * 40}px` }">
            <span v-for="(src, k) in picsOf(q)" :key="k" class="qpic" :style="{ left: `${k * 40}px` }"><img v-if="src" :src="src" alt="" /></span></span>
          <span class="qt"><b>{{ queueTitle(q) }}</b><span>{{ q.line }}</span></span>
          <button v-if="q.state === 'ready' && !here.away" class="a-btn amber go" @click="starting = q">It's clear, start</button>
          <button v-if="!here.away" class="x" :aria-label="`Take ${q.name} out of the queue`" @click="unqueue(q.id)">×</button>
        </div>
      </div>
    </div>

    <div v-if="canPick" class="shelfhead">
      <p class="label">{{ selecting ? 'The shelf · tap to pick' : 'The shelf' }}</p>
      <button class="pill" @click="selecting ? cancel() : (selecting = true)">{{ selecting ? 'Cancel' : 'Select' }}</button>
    </div>
    <p v-else-if="queue.length" class="label">The shelf</p>
    <div class="grid">
      <label v-if="!here.away && !selecting" class="add" :class="{ busy: adding }">
        <input type="file" accept=".stl,.obj,.3mf,.step,.stp" multiple :disabled="!!adding" @change="add" />
        <span class="plus" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg></span>
        <b>{{ adding ? `Adding ${adding}…` : 'Add a model' }}</b>
        <span>From this screen, or a phone or computer at home. STL, 3MF, OBJ or STEP.</span>
      </label>
      <a v-for="it in shown" :key="it.id" :href="router.resolve(toModel(it.id)).href" class="item"
         :class="{ picking: selecting, on: selecting && picked.includes(it.id) }" :aria-pressed="selecting ? picked.includes(it.id) : undefined"
         @click.prevent="tap(it.id)" @pointerdown="press(it.id, $event)" @pointermove="drift" @pointerup="unpress" @pointerleave="unpress"
         @pointercancel="unpress" @contextmenu="($event) => { if (holding) $event.preventDefault() }">
        <span class="pic"><img v-if="it.picture" :src="it.picture" alt="" draggable="false" /><span v-else class="ext">{{ it.file.split('.').pop()?.toUpperCase() }}</span>
          <span v-if="card(it).tag && !selecting" class="tag">{{ card(it).tag }}</span>
          <span v-if="selecting" class="tick" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span></span>
        <span class="t"><b>{{ it.name }}</b><span>{{ card(it).line }}</span></span>
      </a>
    </div>
    <button v-if="fold.older.length" class="older" :aria-expanded="showOlder" @click="showOlder = !showOlder">
      <b>Older · {{ fold.older.length }}</b><span class="muted">{{ showOlder ? 'printed before the last 30 days' : `not printed since ${fold.since}` }}</span>
      <span class="minis"><span v-for="it in fold.older.slice(0, 7)" :key="it.id" class="mini"><img v-if="it.picture" :src="it.picture" alt="" /></span></span>
      <span class="show">{{ showOlder ? 'Hide' : 'Show ›' }}</span>
    </button>
    <p v-if="loaded && !items.length" class="empty">Nothing on the shelf yet. A model added here, or printed from any printer's own Print, stays, ready for any printer on the bench.</p>
    <p v-else-if="loaded && !selecting" class="foot">{{ here.away ? awayShelfFoot(here) : "Every model printed on the bench lands here, from the box or from a printer's own Print. Files sent from a slicer on a computer stay on their printer." }}</p>
    <div v-if="selecting" class="selbar">
      <b>{{ bar.count }}</b><span class="m">{{ bar.names }}</span>
      <button class="lnk" :disabled="!picked.length" @click="picked = []">Clear</button>
      <button class="a-btn accent sgo" :disabled="!picked.length" @click="planIt">{{ bar.go }}</button>
    </div>
    <QueueStart v-if="starting" :item="starting" @close="starting = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { bench, loadQueue, onBenchChange } from '../live'
import { foldShelf, queueSentence, queueTitle, shelfCard, shelfSentence, type QueueItem } from '../shelf'
import { footBar, pickLine, picksFromQuery, picksOf, picksToQuery, toggle } from '../several'
import { addModel, getShelf, removeQueued, reorderQueue, type ShelfItem } from '../shelf-api'
import BenchTop from './BenchTop.vue'
import QueueStart from './QueueStart.vue'
import { here } from '../here'
import { awayShelfFoot, isGuest, lookingOnly, mayPlan } from '../away'

const route = useRoute()
const router = useRouter()
const items = ref<ShelfItem[]>([])
const loaded = ref(false)
const error = ref('')
const adding = ref('')
const now = new Date()
const card = (it: ShelfItem) => shelfCard(it, now)
const line = computed(() => {
  if (!bench.loaded) return ''
  const s = queueSentence(queue.value) ?? shelfSentence(bench.printers)
  return isGuest(here) ? lookingOnly(s) : s
})

// Tidy A: the last 30 days on show, the rest folded into one row
const fold = computed(() => foldShelf(items.value, now))
const showOlder = ref(false)
const shown = computed(() => (showOlder.value ? [...fold.value.recent, ...fold.value.older] : fold.value.recent))
const pictureOf = (shelfId: string) => items.value.find((it) => it.id === shelfId)?.picture ?? null
const picsOf = (q: QueueItem) => (q.models?.length ? q.models : [{ shelf: q.shelf }]).slice(0, 3).map((m) => pictureOf(m.shelf))

// Several at once: Select (or holding a model) ticks instead of opening; Back from the plan comes back ticked (?pick=)
const canPick = computed(() => mayPlan(here) && items.value.length > 1)
const selecting = ref(false)
const picked = ref<string[]>(picksFromQuery(route.query.pick).map((p) => p.shelf))
if (picked.value.length) selecting.value = true
const bar = computed(() => footBar(picked.value.map((id) => items.value.find((it) => it.id === id)?.name ?? '').filter(Boolean)))
const toModel = (id: string) => ({ path: `/print/${id}`, query: route.query })
function cancel() {
  selecting.value = false
  picked.value = []
}
function planIt() {
  const { pick: _, ...query } = route.query
  void router.push({ path: '/print/plan', query: { ...query, m: picksToQuery(picksOf(picked.value, items.value)) } })
}

// a long press on a model: select mode with that one ticked; the click that ends the press opens nothing
const HOLD_MS = 550
let holdTimer = 0
let from: { x: number; y: number } | null = null
const holding = ref(false)
function press(id: string, ev: PointerEvent) {
  if (!canPick.value || selecting.value || ev.button > 0) return
  from = { x: ev.clientX, y: ev.clientY }
  window.clearTimeout(holdTimer)
  holdTimer = window.setTimeout(() => {
    holding.value = true
    selecting.value = true
    picked.value = [id]
    navigator.vibrate?.(12)
  }, HOLD_MS)
}
function drift(ev: PointerEvent) {
  if (from && Math.hypot(ev.clientX - from.x, ev.clientY - from.y) > 10) unpress()
}
function unpress() {
  window.clearTimeout(holdTimer)
  from = null
  if (holding.value) window.setTimeout(() => { holding.value = false }, 400)     // a press ended without its click
}
function tap(id: string) {
  if (holding.value) { holding.value = false; return }
  if (selecting.value) picked.value = toggle(picked.value, id)
  else void router.push(toModel(id))
}

// Queue A: what's waiting, as the box says; while a row is dragged, the order under the finger
const drag = ref<{ id: string; order: string[] } | null>(null)
const rows = ref<HTMLElement | null>(null)
const queue = computed<QueueItem[]>(() => (drag.value ? drag.value.order.map((id) => bench.queue.find((q) => q.id === id)!).filter(Boolean) : bench.queue))
const starting = ref<QueueItem | null>(null)

function grab(ev: PointerEvent, id: string) {
  drag.value = { id, order: bench.queue.map((q) => q.id) }
  ;(ev.target as HTMLElement).setPointerCapture(ev.pointerId)
  const move = (e: PointerEvent) => {
    const els = [...(rows.value?.children ?? [])] as HTMLElement[]
    const to = els.findIndex((el) => { const r = el.getBoundingClientRect(); return e.clientY < r.top + r.height / 2 })
    const order = drag.value!.order.filter((x) => x !== id)
    order.splice(to < 0 ? order.length : Math.min(to, order.length), 0, id)
    drag.value = { id, order }
  }
  const drop = async () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', drop)
    const order = drag.value!.order
    const changed = order.join() !== bench.queue.map((q) => q.id).join()
    try {
      if (changed) bench.queue = await reorderQueue(order)
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      drag.value = null
    }
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', drop)
}

async function unqueue(id: string) {
  await removeQueued(id).catch(() => undefined)
  await loadQueue()
}

async function load() {
  try {
    items.value = await getShelf()
    error.value = ''
  } catch (e) {
    error.value = "The box's shelf didn't load."
  } finally {
    loaded.value = true
  }
}
onMounted(load)
onUnmounted(onBenchChange(load))

async function add(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  error.value = ''
  const failed: string[] = []
  let only: ShelfItem | null = null
  for (const [n, file] of files.entries()) {
    adding.value = files.length > 1 ? `${n + 1} of ${files.length}: ${file.name}` : file.name
    try {
      only = await addModel(file)
    } catch (e) {
      failed.push(files.length > 1 ? `${file.name}: ${(e as Error).message}` : (e as Error).message)
    }
  }
  adding.value = ''
  if (files.length === 1 && only) return router.push({ path: `/print/${only.id}`, query: route.query })
  error.value = failed.join(' ')
  await load()
}
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 16px; }
.say { margin: 8px 0 0; font-size: 40px; line-height: 1.08; letter-spacing: -.025em; text-wrap: balance; }
.note { margin: 0; color: var(--a-red-text); font-size: 18px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.add, .item { border-radius: 22px; overflow: hidden; text-decoration: none; color: inherit; min-height: 210px; }
.add { display: grid; place-items: center; align-content: center; gap: 8px; padding: 18px; text-align: center; cursor: pointer;
       border: 2px dashed var(--a-line); }
.add input { display: none; }
.add.busy { cursor: progress; opacity: .7; }
.plus { width: 58px; height: 58px; border-radius: 16px; background: var(--a-accent); display: grid; place-items: center; }
.plus svg { width: 30px; height: 30px; fill: none; stroke: var(--a-accent-ink); stroke-width: 2.4; stroke-linecap: round; }
.add b { font-size: 20px; } .add span:last-child { color: var(--a-ink-3); font-size: 15px; max-width: 24ch; }
.item { display: grid; grid-template-rows: 140px auto; background: var(--a-surface); box-shadow: var(--a-card-shadow); position: relative;
        user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.item.on { box-shadow: 0 0 0 3px var(--a-accent), var(--a-card-shadow); }
.tick { position: absolute; right: 12px; top: 12px; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center;
        background: color-mix(in srgb, var(--a-surface) 90%, transparent); box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--a-ink) 28%, transparent); }
.item.on .tick { background: var(--a-accent); box-shadow: none; }
.tick svg { width: 18px; height: 18px; fill: none; stroke: var(--a-accent-ink); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.item:not(.on) .tick svg { visibility: hidden; }
.shelfhead { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 4px; }
.shelfhead .label { margin: 0; }
.pill { appearance: none; border: 0; min-height: 46px; padding: 0 20px; border-radius: 99px; background: var(--a-surface); color: var(--a-accent-text);
        font: inherit; font-size: 18px; font-weight: 650; box-shadow: var(--a-card-shadow); cursor: pointer; }
.selbar { position: sticky; bottom: 12px; z-index: 3; margin-top: auto; display: flex; align-items: center; gap: 16px; min-height: 66px; box-sizing: border-box;
          padding: 8px 10px 8px 22px; border-radius: 20px; background: var(--a-ink); color: var(--a-bg); box-shadow: 0 12px 30px rgba(8, 12, 20, .28); }
.selbar b { font-size: 20px; white-space: nowrap; }
.selbar .m { flex: 1; min-width: 0; opacity: .62; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.selbar .lnk { appearance: none; border: 0; background: none; color: inherit; opacity: .8; font: inherit; font-size: 17px; font-weight: 600; padding: 0 8px; min-height: 48px; cursor: pointer; }
.selbar .lnk:disabled { opacity: .3; cursor: default; }
.sgo { width: auto; flex: none; height: 50px; font-size: 19px; padding: 0 24px; }
.pic { display: grid; place-items: center; background: linear-gradient(var(--a-surface), var(--a-surface-2)); position: relative; }
.tag { position: absolute; left: 10px; top: 10px; padding: 4px 11px; border-radius: 999px; background: var(--a-surface); color: var(--a-ink-2); font-size: 13px; font-weight: 650; }
.pic img { max-width: 80%; max-height: 130px; object-fit: contain; }
.ext { color: var(--a-ink-3); font-weight: 700; letter-spacing: .1em; }
.t { display: grid; gap: 2px; padding: 12px 16px 14px; min-width: 0; }
.t b { font-size: 19px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.t span { color: var(--a-ink-3); font-size: 15px; }
.label { margin: 4px 0 0; color: var(--a-ink-3); font-size: 15px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.queue { display: grid; gap: 8px; }
.qrows { display: grid; gap: 8px; }
.qrow { display: flex; align-items: center; gap: 14px; padding: 10px 16px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.qrow.ready { box-shadow: 0 0 0 3px var(--a-amber), var(--a-card-shadow); }
.qrow.dragging { opacity: .7; }
.handle { cursor: grab; touch-action: none; color: var(--a-ink-3); font-size: 20px; letter-spacing: -3px; padding: 6px 4px; user-select: none; }
.n { color: var(--a-ink-3); font-size: 18px; width: 18px; }
.qpics { position: relative; height: 50px; flex: none; }
.qpics .qpic { position: absolute; top: 0; box-shadow: 0 0 0 2px var(--a-surface); }
.qpic { width: 64px; height: 50px; border-radius: 10px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); display: grid; place-items: center; flex: none; overflow: hidden; }
.qpic img { max-width: 90%; max-height: 46px; object-fit: contain; }
.qt { flex: 1; min-width: 0; display: grid; gap: 1px; }
.qt b { font-size: 18px; } .qt span { color: var(--a-ink-3); font-size: 15px; }
.go { flex: none; width: auto; height: 46px; font-size: 16px; padding: 0 18px; }
.x { appearance: none; border: 0; background: none; color: var(--a-ink-3); font-size: 26px; line-height: 1; padding: 4px 8px; cursor: pointer; }
.older { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 18px;
         padding: 12px 20px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.older b { font-size: 19px; white-space: nowrap; } .older .muted { color: var(--a-ink-3); font-size: 16px; white-space: nowrap; }
.minis { display: flex; gap: 6px; flex: 1; overflow: hidden; }
.mini { width: 58px; height: 44px; border-radius: 10px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); display: grid; place-items: center; flex: none; overflow: hidden; }
.mini img { max-width: 90%; max-height: 40px; object-fit: contain; }
.show { color: var(--a-accent-text); font-weight: 650; font-size: 18px; white-space: nowrap; }
.empty { margin: 0; color: var(--a-ink-3); font-size: 18px; }
.foot { margin: 0; color: var(--a-ink-3); font-size: 16px; }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 24px; gap: 10px; }
  .say { font-size: 25px; }
  .grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .add { min-height: 0; grid-template-columns: auto 1fr; justify-items: start; text-align: left; padding: 12px 14px; gap: 2px 12px; border-radius: 16px; }
  .add .plus { grid-row: span 2; width: 44px; height: 44px; } .add span:last-child { font-size: 13px; }
  .item { min-height: 0; grid-template-rows: none; grid-template-columns: 76px 1fr; border-radius: 16px; }
  .qrow { gap: 8px; padding: 8px 10px; } .qpics { display: none; } .qt b { font-size: 15px; } .qt span { font-size: 13px; } .go { height: 38px; font-size: 13px; padding: 0 10px; }
  .older { gap: 10px; padding: 10px 14px; } .minis { display: none; } .older b { font-size: 16px; } .older .muted { font-size: 13px; white-space: normal; }
  .pic img { max-height: 60px; } .tag { display: none; }
  .item.picking .pic { position: static; } .item.picking .t { padding-right: 52px; }
  .tick { right: 14px; top: 50%; margin-top: -15px; width: 30px; height: 30px; } .tick svg { width: 16px; height: 16px; }
  .pill { min-height: 40px; font-size: 15px; padding: 0 16px; }
  .selbar { bottom: 8px; min-height: 58px; gap: 10px; padding: 6px 8px 6px 16px; border-radius: 16px; }
  .selbar b { font-size: 16px; } .selbar .m { display: none; } .selbar .lnk { font-size: 15px; margin-left: auto; } .sgo { height: 44px; font-size: 16px; padding: 0 18px; } .t { align-content: center; padding: 10px 12px; } .t b { font-size: 16px; } .t span { font-size: 13px; }
}
</style>
