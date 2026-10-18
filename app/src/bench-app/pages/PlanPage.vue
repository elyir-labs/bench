<template>
  <!-- Several models from the shelf at once (design/bench-several/, C, picked 10 October 2026): the plan the box makes
       for the picked models (bench/plan.py), a card per bed. Each model's copies change on its row; tapping it moves it
       (MoveSheet, C-move); a bed too full is split, and says so with Keep them all (C-edge). Print all puts each bed at the
       end of Up next, where each printer asks about its own bed (C-sent); away it's Add to the queue, and nothing starts.
       The picks ride in the address (?m=), so a reload keeps them.
       How it prints (11 October 2026): each card says how its bed prints, as the box planned it; tapping it opens the
       model page's sheets for the whole bed, each change saved with every model on it, then the box plans again.
       Which side down (11 October 2026): a model's move sheet has its Lying row, the model page's sheet; the side is kept
       with the model and the box plans again (another side can change what fits a bed). -->
  <section class="bpage" :class="{ moving: !!(moving || movingWhole) }">
    <BenchTop title="Print"><router-link :to="{ path: '/print', query: rest }" class="back">Shelf</router-link></BenchTop>
    <h1 class="a-display say">{{ plan ? planHeadline(plan) : picks.length ? 'Working it out…' : 'Nothing picked.' }}</h1>
    <p v-if="plan && cards.length" class="rule">{{ RULE }}</p>
    <p v-if="error" class="note" role="alert">{{ error }}</p>

    <div v-for="s in splits" :key="s.printer" class="split">
      <p>{{ s.said }}</p>
      <button v-if="s.keep" class="a-btn ghost keep" :disabled="asking" @click="picks = keepAll(picks, s)">{{ s.keep }}</button>
    </div>
    <p v-for="s in strips" :key="`l:${s.key}`" class="sline"><i></i>{{ s.short }}</p>

    <div v-if="plan" class="cards" :style="{ '--n': Math.max(1, Math.min(cards.length, moving || movingWhole ? 2 : 4)) }">
      <article v-for="b in cards" :key="b.id" class="card" :class="{ later: !['now', 'clear'].includes(b.when.kind) }">
        <header class="ch"><h2>{{ b.printer_name }}</h2><span class="chip" :class="chipOf(b, picks).tone">{{ chipOf(b, picks).word }}</span></header>
        <p class="fil"><i :style="{ background: b.color ?? 'var(--a-surface-2)' }"></i><span class="fw">{{ filamentLine(b, jobOf(b.printer)) }}</span>
          <button class="chg" :class="{ on: movingWhole === b.models[0]?.shelf }" @click="openBed(b)">Change printer</button></p>
        <p class="blabel">{{ bedLabel(b) }}</p>
        <div class="mrows">
          <div v-for="m in b.models" :key="m.shelf" class="mrow" :class="{ sel: moving === m.shelf }">
            <button class="mopen" :aria-label="`Move ${m.name}`" @click="movingWhole = null; moving = m.shelf">
              <span class="mpic"><img v-if="m.picture" :src="m.picture" alt="" /></span>
              <span class="mt"><b>{{ m.name }}</b><span>{{ modelLine(plan, b, m) }}</span></span>
              <span class="go" aria-hidden="true">›</span>
            </button>
            <button class="cstep" :disabled="copiesOf(m.shelf) <= 1" :aria-label="`One fewer ${m.name}`" @click="step(m.shelf, -1)">−</button>
            <b class="a-num n">{{ m.copies }}</b>
            <button class="cstep" :disabled="copiesOf(m.shelf) >= 200" :aria-label="`One more ${m.name}`" @click="step(m.shelf, 1)">+</button>
          </div>
        </div>
        <button v-if="!here.away" class="how" :class="{ on: howShelf === b.models[0]?.shelf }" @click="openHow(b)">
          <span class="hk">How it prints</span><span class="hv">{{ howLineOf(b) }}</span><span class="go" aria-hidden="true">›</span></button>
        <p v-else class="how"><span class="hk">How it prints</span><span class="hv">{{ howLineOf(b) }}</span></p>
        <p v-if="noteOf(b)" class="cnote">{{ noteOf(b) }}</p>
        <div class="plate" aria-hidden="true">
          <svg viewBox="0 0 180 72"><polygon points="90,1 179,36 90,71 1,36" /></svg>
          <template v-for="(sp, k) in plateSpots(b.models)" :key="k">
            <img v-if="sp.picture" :src="sp.picture" alt="" :style="{ left: `${sp.x - sp.size / 2}px`, top: `${sp.y - sp.size * 0.8}px`, width: `${sp.size}px` }" />
          </template>
        </div>
        <p class="cost"><b class="a-num" :class="{ none: !costOf(b).cost }">{{ costOf(b).cost || UNTIMED }}</b><span>{{ costOf(b).done }}</span></p>
      </article>
    </div>

    <div v-for="s in strips" :key="s.key" class="strip">
      <span class="spics"><span v-for="(src, k) in s.pictures.slice(0, 2)" :key="k" class="spic"><img v-if="src" :src="src" alt="" /></span></span>
      <span class="st"><b>{{ s.title }}</b><span>{{ s.line }}</span></span>
      <button class="a-btn ghost sout" :disabled="asking" @click="takeOut(s.shelves)">Take it out</button>
    </div>
    <p v-if="plan && freeLine(plan)" class="free">{{ freeLine(plan) }}</p>
    <p v-if="plan?.out.length" class="free">Taken out: {{ plan.out.map((o) => o.name).join(', ') }} ·
      <button class="back-in" @click="putBack">Put {{ plan.out.length === 1 ? 'it' : 'them' }} back</button></p>

    <div class="foot">
      <span class="fw"><b>{{ foot.done }}</b><span>{{ foot.line }}</span></span>
      <router-link v-if="!moving && !movingWhole" :to="{ path: '/print', query: { ...rest, pick: picksToQuery(picks.filter((p) => !p.out)) } }" class="a-btn ghost fback">Back</router-link>
      <button class="a-btn accent fgo" :disabled="!foot.can || asking || sending" @click="printAll">
        <template v-if="sending">{{ here.away ? 'Adding…' : 'Putting it in Up next…' }}</template>
        <template v-else><span class="long">{{ foot.go }}</span><span class="short">{{ foot.short }}</span></template></button>
    </div>

    <MoveSheet v-if="plan && moving && movingBed && movingModel" :title="movingModel.name"
               :sub="movingSub" :pick="pickOf(moving)" :fils="inChoices(fils, movingBed).fils" :fil="inChoices(fils, movingBed).on"
               :options="moveOptions(movingBed, moving, picks, bench.printers, printable)" :side="here.away ? null : sideRowOf(moving)"
               @change="(c) => change(moving!, c)" @side="sideOpen = true" @close="moving = null" />
    <MoveSheet v-else-if="plan && movingWhole && wholeBed" :title="queueName(wholeBed)" :sub="`${wholeBed.words} · one bed`"
               :options="bedOptions(wholeBed, picks, bench.printers, printable)" out="Take this bed out of the print"
               :fils="inChoices(fils, wholeBed).fils" :fil="inChoices(fils, wholeBed).on"
               @change="changeBed" @close="movingWhole = null" />

    <SideSheet :open="sideOpen && !!moving" :view="moving ? sidesOf[moving] ?? null : null" :tris="moving ? trisOf[moving] ?? null : null"
               :color="movingBed?.color ?? '#8A8D91'" :name="movingModel?.name ?? ''" @pick="(n, normal) => pickSide(moving!, n, normal)" @close="sideOpen = false" />

    <template v-if="howBed">
      <HowSheet :open="howOpen === 'all'" title="How it prints" :model="''" :kept="BED_KEPT" :sub="`The whole bed on ${howBed.printer_name}: ${queueName(howBed)}.`"
                @close="closeHow">
        <button v-for="t in bedTiles(howBed, howWords(howBed))" :key="t.id" class="hpick" @click="howOpen = t.id">
          <span class="k">{{ t.label }}</span>
          <span class="v"><b>{{ t.value }}</b><span :class="{ link: t.link }">{{ t.line }}</span></span>
          <span class="go" aria-hidden="true">›</span>
        </button>
        <p v-if="howError" class="hbad" role="alert">{{ howError }}</p>
      </HowSheet>
      <HowSheets :open="howOpen === 'all' ? null : howOpen" :how="bedHow(howBed).how" :mixed="bedHow(howBed).mixed" name="" :kept="BED_KEPT"
                 :purposes="purposeList(options?.purposes)" :editable="options?.editable ?? []" :usual="usualOf(howBed.printer)"
                 :printer="howBed.printer_name" :subs="bedSubs(howBed)" @change="changeHow" @close="howOpen = 'all'" />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { bench, loadQueue } from '../live'
import { here } from '../here'
import { mayPlan } from '../away'
import { choices, type MyFilament, type Printable } from '../shelf'
import { getMine, getPlan, getPrintable, getShelf, getSides, getSliceOptions, getUsual, partTris, printPlan, setHow, setSide, type ShelfItem } from '../shelf-api'
import { canPickSide, pickOf as sidePick, sideRow, withSide, type SidesView } from '../sides'
import { RULE, UNTIMED, bedHow, bedHowLine, bedHowSaves, bedLabel, bedOptions, bedTiles, inChoices, moveBed, cardsOf, chipOf, costOf, filamentLine, footOf, freeLine, keepAll,
         modelLine, moveOptions, noteOf, picksFromQuery, picksToQuery, planHeadline, plateSpots, setPick, splitsOf, stripsOf, withHow, type PlanBed, type PlanPick, type Plan } from '../several'
import { purposeList, type HowChange, type Tile } from '../how'
import type { SliceOptions } from '@/slice/api'
import type { SupportKind } from '@/slice/plan'
import BenchTop from './BenchTop.vue'
import MoveSheet from './MoveSheet.vue'
import HowSheet from './HowSheet.vue'
import HowSheets from './HowSheets.vue'
import SideSheet from './SideSheet.vue'

const route = useRoute()
const router = useRouter()
const rest = computed(() => { const { m: _, pick: __, ...q } = route.query; return q })
const picks = ref<PlanPick[]>(picksFromQuery(route.query.m))
const plan = ref<Plan | null>(null)
const printable = ref<Printable>({})
const error = ref('')
const asking = ref(false)
const sending = ref(false)
const moving = ref<string | null>(null)

const cards = computed(() => (plan.value ? cardsOf(plan.value) : []))
const strips = computed(() => (plan.value ? stripsOf(plan.value) : []))
const splits = computed(() => (plan.value ? splitsOf(plan.value) : []))
const foot = computed(() => footOf(plan.value, here.away))
const movingBed = computed(() => plan.value?.beds.find((b) => b.models.some((m) => m.shelf === moving.value)) ?? null)
const movingModel = computed(() => movingBed.value?.models.find((m) => m.shelf === moving.value) ?? null)
const movingSub = computed(() => `${movingBed.value?.words}, ${movingModel.value?.chosen ? 'picked here' : movingModel.value?.first ? "what's loaded" : 'as last time'}`)
const mine = ref<MyFilament[]>([])
const fils = computed(() => choices(bench.printers, printable.value, mine.value))
// a whole bed is followed by its first model, since its id changes with its printer
const movingWhole = ref<string | null>(null)
const wholeBed = computed(() => plan.value?.beds.find((b) => b.models.some((m) => m.shelf === movingWhole.value)) ?? null)
const queueName = (b: { models: { name: string; copies: number }[] }) => b.models.map((m) => (m.copies > 1 ? `${m.name} × ${m.copies}` : m.name)).join(', ')
function openBed(b: { models: { shelf: string }[] }) {
  moving.value = null
  movingWhole.value = b.models[0]?.shelf ?? null
}
function changeBed(patch: Partial<PlanPick>) {
  if (!wholeBed.value) return
  if (patch.out) {
    takeOut(wholeBed.value.models.map((m) => m.shelf))
    movingWhole.value = null
  } else picks.value = moveBed(picks.value, wholeBed.value, patch)
}
const pickOf = (shelf: string) => picks.value.find((p) => p.shelf === shelf) ?? { shelf, copies: 1 }
const copiesOf = (shelf: string) => pickOf(shelf).copies
const jobOf = (id: string | null) => bench.printers.find((p) => p.id === id)?.intent?.job?.name ?? null

// The box answers at once with what it knows; while it checks what fits, the same picks are asked again
let seq = 0
let again = 0
async function replan() {
  const n = ++seq
  window.clearTimeout(again)
  if (!picks.value.length) { plan.value = null; return }
  asking.value = true
  try {
    const p = await getPlan(picks.value)
    if (n !== seq || saving) return
    plan.value = p
    error.value = ''
    if (p.checking) again = window.setTimeout(replan, 900)
  } catch (e) {
    if (n === seq) error.value = (e as Error).message
  } finally {
    if (n === seq) asking.value = false
  }
}

watch(picks, (ps) => {
  void router.replace({ query: { ...rest.value, m: picksToQuery(ps) } })
  void replan()
}, { deep: true })

function change(shelf: string, patch: Partial<PlanPick>) {
  picks.value = setPick(picks.value, shelf, patch)
  if (patch.out) moving.value = null
}
const step = (shelf: string, d: number) => change(shelf, { copies: copiesOf(shelf) + d })
function takeOut(shelves: string[]) {
  picks.value = picks.value.map((p) => (shelves.includes(p.shelf) ? { ...p, out: true } : p))
}
const putBack = () => { picks.value = picks.value.map(({ out: _, ...p }) => p) }
watch(movingBed, (b) => { if (!b && !asking.value) moving.value = null })
watch(wholeBed, (b) => { if (!b && !asking.value) movingWhole.value = null })

// ── how each bed prints: the model page's sheets, each change kept with every model on the bed ──
const options = ref<SliceOptions | null>(null)
// each printer's own usual supports (its Print's), asked once per printer
const usual = reactive<Record<string, SupportKind>>({})
const askedUsual = new Set<string>()
watch(() => cards.value.map((b) => b.printer).join(), () => {
  for (const pid of cards.value.map((b) => b.printer!)) {
    if (askedUsual.has(pid)) continue
    askedUsual.add(pid)
    void getUsual(pid).then((u) => { usual[pid] = u.supports }, () => askedUsual.delete(pid))
  }
})
const usualOf = (pid: string | null) => (pid ? usual[pid] ?? null : null)
const howWords = (b: PlanBed) => ({ purposes: options.value?.purposes, editable: options.value?.editable, usual: usualOf(b.printer) })
const howLineOf = (b: PlanBed) => bedHowLine(b, howWords(b))
const BED_KEPT = 'Kept with each model on this bed: next time, and on whichever printer takes them, they print this way.'
function bedSubs(b: PlanBed): Partial<Record<Tile['id'], string>> {
  return {
    purpose: 'A bed prints one way: every model on it gets this.',
    brim: bedHow(b).mixed ? 'They differ now. Pick one and every model on this bed gets it.'
      : 'What holds the first layer down, round every part. Every model on this bed gets the same.',
    settings: `Laid over ${b.printer_name}'s own. One set here is each of these models', on any printer.`,
  }
}

// a bed is followed by its first model, as Change printer's is: a change can move it
const howShelf = ref<string | null>(null)
const howOpen = ref<'all' | Tile['id']>('all')
const howBed = computed(() => plan.value?.beds.find((b) => b.models.some((m) => m.shelf === howShelf.value)) ?? null)
function openHow(b: PlanBed) {
  moving.value = null
  movingWhole.value = null
  howOpen.value = 'all'
  howShelf.value = b.models[0]?.shelf ?? null
}
const closeHow = () => { howShelf.value = null; howError.value = '' }
watch(howBed, (b) => { if (!b && !asking.value) howShelf.value = null })

// shown at once, saved one after another, then the box plans again with what's saved (it reads each model's how)
const howError = ref('')
let saving = 0
let saved: Promise<unknown> = Promise.resolve()
function changeHow(c: HowChange) {
  const b = howBed.value
  if (!b || !plan.value) return
  const each = bedHowSaves(b, c)
  plan.value = withHow(plan.value, each.map((x) => x.shelf), c)
  saving++
  window.clearTimeout(again)
  saved = saved.then(() => Promise.all(each.map((x) => setHow(x.shelf, x.change)))).then(
    () => { howError.value = '' },
    (e) => { howError.value = `It couldn't be kept with the models: ${(e as Error).message}` })
    .finally(() => { if (--saving === 0) void replan() })
}

// ── which side down, for the model being moved: read when its sheet opens, kept with it, then planned again ──
const sideOpen = ref(false)
const sidesOf = ref<Record<string, SidesView>>({})
const trisOf = shallowRef<Record<string, (Float32Array | null)[]>>({})
const shelf = ref<ShelfItem[]>([])
const asked = new Set<string>()
watch(() => [moving.value, shelf.value] as const, ([sid]) => {
  if (!sid) { sideOpen.value = false; return }
  if (!asked.has(sid)) {
    asked.add(sid)
    void getSides(sid).then((v) => { sidesOf.value = { ...sidesOf.value, [sid]: v } }, () => asked.delete(sid))
  }
  const it = shelf.value.find((x) => x.id === sid)
  if (it && !trisOf.value[sid]) {
    trisOf.value = { ...trisOf.value, [sid]: [] }
    void partTris(it).then((t) => { trisOf.value = { ...trisOf.value, [sid]: t.map((x) => (x ? markRaw(x) : null)) } }, () => undefined)
  }
})
const sideRowOf = (sid: string) => ({ ...sideRow(sidesOf.value[sid] ?? null), can: canPickSide(sidesOf.value[sid] ?? null) })
function pickSide(sid: string, n: number, normal: number[] | null) {
  const v = sidesOf.value[sid]
  if (!v) return
  sidesOf.value = { ...sidesOf.value, [sid]: withSide(v, n, normal) }
  saving++
  window.clearTimeout(again)
  saved = saved.then(() => setSide(sid, sidePick(n, normal))).then(
    (back) => { sidesOf.value = { ...sidesOf.value, [sid]: back }; error.value = '' },
    (e) => { error.value = `It couldn't be kept with the model: ${(e as Error).message}` })
    .finally(() => { if (--saving === 0) void replan() })
}

async function printAll() {
  if (!plan.value || !foot.value.can) return
  sending.value = true
  error.value = ''
  try {
    await printPlan(plan.value.beds)
    await loadQueue()
    await router.push({ path: '/print', query: rest.value })
  } catch (e) {
    error.value = (e as Error).message
    void replan()
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  if (!mayPlan(here)) { void router.replace({ path: '/print', query: rest.value }); return }
  void replan()
  void getPrintable().then((p) => (printable.value = p), () => undefined)
  void getMine().then((m) => (mine.value = m), () => undefined)
  void getSliceOptions().then((o) => (options.value = o), () => undefined)
  void getShelf().then((s) => (shelf.value = s), () => undefined)
})
onBeforeUnmount(() => { seq++; window.clearTimeout(again) })
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 0; display: flex; flex-direction: column; gap: 14px; }
.bpage.moving { padding-right: 510px; }
.back { color: var(--a-accent-text); font-weight: 650; font-size: 20px; text-decoration: none; }
.back::before { content: '‹ '; }
.say { margin: 8px 0 0; font-size: 40px; line-height: 1.08; letter-spacing: -.025em; text-wrap: balance; }
.rule { margin: -8px 0 0; color: var(--a-ink-3); font-size: 18px; }
.note { margin: 0; color: var(--a-red-text); font-size: 18px; }
.split { display: flex; align-items: center; gap: 18px; padding: 12px 14px 12px 20px; border-radius: 18px; background: color-mix(in srgb, var(--a-amber) 20%, var(--a-surface)); }
.split p { margin: 0; flex: 1; font-size: 17px; color: var(--a-amber-text); line-height: 1.35; }
.keep { width: auto; flex: none; height: 48px; font-size: 16px; padding: 0 20px; background: var(--a-surface); color: var(--a-ink); }
.sline { display: none; }
.cards { display: grid; gap: 16px; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); }
.card { container-type: inline-size; display: flex; flex-direction: column; gap: 6px; padding: 18px 18px 16px; background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); min-width: 0; }
.card.later { background: color-mix(in srgb, var(--a-surface) 70%, var(--a-bg)); }
.ch { display: flex; align-items: center; gap: 10px; }
.ch h2 { margin: 0; flex: 1; min-width: 0; font-size: 24px; letter-spacing: -.01em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip { flex: none; padding: 4px 11px; border-radius: 99px; font-size: 13px; font-weight: 700; white-space: nowrap; }
.chip.green { background: var(--a-tint-green); color: var(--a-green-text); }
.chip.gray { background: var(--a-surface-2); color: var(--a-ink-2); }
.chip.blue { background: var(--a-tint-blue); color: var(--a-accent-text); }
.chip.amber { background: var(--a-tint-amber); color: var(--a-amber-text); }
.fil { margin: 0; display: flex; align-items: center; gap: 8px; color: var(--a-ink-3); font-size: 15px; min-width: 0; }
.fw { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chg { appearance: none; flex: none; border: 0; background: none; font: inherit; font-size: 15px; font-weight: 650; color: var(--a-accent-text);
       padding: 8px 0 8px 10px; margin: -8px 0; cursor: pointer; }
.chg.on { text-decoration: underline; }
.go { flex: none; margin-left: auto; padding-left: 6px; font-size: 24px; line-height: 1; color: var(--a-ink-3); }
.fil i { width: 13px; height: 13px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .18); }
.blabel { margin: 6px 0 0; padding-bottom: 6px; border-bottom: 1px solid var(--a-line); color: var(--a-ink-3); font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.mrows { display: grid; }
.mrow { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--a-line); }
.mrow:last-child { border-bottom: 0; }
.mrow.sel .mopen { box-shadow: 0 0 0 2px var(--a-accent); }
.mopen { appearance: none; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; flex: 1; min-width: 0;
         display: flex; align-items: center; gap: 10px; padding: 4px; margin: -4px; border-radius: 12px; }
.mpic { width: 52px; height: 42px; flex: none; border-radius: 10px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); display: grid; place-items: center; overflow: hidden; }
.mpic img { max-width: 90%; max-height: 38px; object-fit: contain; }
.mt { min-width: 0; display: grid; gap: 1px; }
.mt b { font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mt span { font-size: 13px; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cstep { width: 40px; height: 40px; flex: none; border-radius: 50%; border: 1px solid var(--a-line); background: var(--a-surface); color: var(--a-ink-2); font: inherit; font-size: 20px; cursor: pointer; }
.cstep:disabled { opacity: .4; cursor: default; }
.n { font-size: 20px; min-width: 28px; text-align: center; }
.how { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; margin: 6px 0 0; padding: 8px 12px; border-radius: 12px;
       background: var(--a-surface-2); display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 8px; align-items: center; }
button.how { cursor: pointer; }
.how.on { box-shadow: 0 0 0 2px var(--a-accent); }
.how .hk { grid-column: 1; color: var(--a-ink-3); font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.how .hv { grid-column: 1; font-size: 15px; font-weight: 600; color: var(--a-ink-2); line-height: 1.3; }
.how .go { grid-column: 2; grid-row: 1 / span 2; }
.hpick { appearance: none; border: 0; border-top: 1px solid var(--a-line); width: 100%; font: inherit; color: inherit; text-align: left; cursor: pointer;
         display: grid; grid-template-columns: 110px minmax(0, 1fr) 20px; gap: 12px; align-items: center; padding: 14px 22px; background: none; }
.hpick .k { color: var(--a-ink-3); font-size: 16px; }
.hpick .v { display: grid; min-width: 0; }
.hpick .v b { font-size: 20px; } .hpick .v span { font-size: 15px; color: var(--a-ink-3); }
.hpick .v span.link { color: var(--a-accent-text); font-weight: 650; }
.hbad { margin: 0; padding: 12px 22px; border-top: 1px solid var(--a-line); color: var(--a-red-text); font-size: 16px; }
.hpick:focus-visible, .how:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.cnote { margin: 4px 0 0; color: var(--a-ink-3); font-size: 15px; line-height: 1.35; }
.plate { position: relative; width: 180px; height: 72px; margin: auto auto 0; padding-top: 10px; box-sizing: content-box; }
.plate svg { position: absolute; left: 0; top: 10px; width: 180px; height: 72px; }
.plate polygon { fill: var(--a-surface-2); stroke: var(--a-line); stroke-width: 1; opacity: .7; }
.plate img { position: absolute; margin-top: 10px; object-fit: contain; pointer-events: none; }
.cost { margin: 8px 0 0; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.cost b { font-size: 20px; } .cost b.none { font-size: 15px; font-weight: 600; color: var(--a-ink-3); }
.cost span { color: var(--a-ink-3); font-size: 15px; }
.strip { display: flex; align-items: center; gap: 16px; padding: 10px 12px 10px 16px; background: var(--a-surface); border-radius: 18px;
         box-shadow: inset 4px 0 0 var(--a-amber), var(--a-card-shadow); }
.spics { display: flex; flex: none; }
.spic { width: 60px; height: 44px; border-radius: 10px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); display: grid; place-items: center; overflow: hidden; }
.spic + .spic { margin-left: -18px; box-shadow: 0 0 0 2px var(--a-surface); }
.spic img { max-width: 90%; max-height: 40px; object-fit: contain; }
.st { flex: 1; min-width: 0; display: grid; gap: 2px; }
.st b { font-size: 18px; } .st span { color: var(--a-ink-3); font-size: 15px; }
.sout { width: auto; flex: none; height: 46px; font-size: 16px; padding: 0 18px; }
.free { margin: -4px 0 0 4px; color: var(--a-ink-3); font-size: 15px; }
.back-in { appearance: none; border: 0; background: none; padding: 0; font: inherit; color: var(--a-accent-text); font-weight: 650; cursor: pointer; }
/* the foot stays above the tab bar while the cards scroll under it */
.foot { position: sticky; bottom: 0; z-index: 2; margin-top: auto; display: flex; align-items: center; gap: 14px; padding: 16px 0 18px;
        background: linear-gradient(transparent, var(--a-bg) 16px); }
.fw { flex: 1; min-width: 0; display: grid; gap: 2px; }
.fw b { font-size: 17px; } .fw span { color: var(--a-ink-3); font-size: 16px; }
.fback, .fgo { width: auto; flex: none; height: 62px; font-size: 21px; padding: 0 30px; text-decoration: none; }
.fgo { padding: 0 34px; }
.fgo .short { display: none; }
/* four across, or two beside the move sheet: the rows give the names their room */
@container (max-width: 330px) {
  .mrow { gap: 5px; } .mopen { gap: 8px; } .mpic { width: 40px; height: 34px; } .mpic img { max-height: 30px; }
  .mt b { font-size: 15px; } .mt span { font-size: 12px; }
  .cstep { width: 32px; height: 32px; font-size: 17px; } .n { font-size: 17px; min-width: 22px; }
  .how { padding: 7px 10px; } .how .hv { font-size: 13.5px; } .how .hk { font-size: 11px; }
  .cnote { font-size: 13.5px; } .plate { transform: scale(.82); margin-top: auto; margin-bottom: -6px; }
  .cost b { font-size: 17px; } .cost span { font-size: 13px; }
}
@media (max-width: 1100px) { .cards { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); } }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 0; gap: 10px; }
  .bpage.moving { padding-right: 16px; }
  .say { font-size: 25px; margin-top: 4px; }
  .rule, .strip, .free, .plate { display: none; }
  .sline { display: flex; align-items: baseline; gap: 8px; margin: -4px 0 0; color: var(--a-amber-text); font-size: 14px; }
  .sline i { width: 9px; height: 9px; border-radius: 50%; background: var(--a-amber); flex: none; transform: translateY(-1px); }
  .split { flex-wrap: wrap; gap: 8px; padding: 10px 12px; } .split p { font-size: 14px; flex-basis: 100%; } .keep { height: 40px; font-size: 14px; }
  .cards { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .card { padding: 14px 14px 12px; border-radius: 18px; gap: 4px; }
  .ch h2 { font-size: 20px; } .fil { font-size: 13.5px; } .blabel { font-size: 11px; margin-top: 4px; }
  .mpic { width: 46px; height: 38px; } .mt b { font-size: 15px; } .mt span { font-size: 12px; }
  .cstep { width: 36px; height: 36px; font-size: 18px; } .n { font-size: 17px; min-width: 22px; }
  .how .hv { font-size: 14px; } .how .hk { font-size: 11px; }
  .hpick { grid-template-columns: 84px minmax(0, 1fr) 16px; padding: 12px 16px; gap: 10px; }
  .hpick .k { font-size: 14px; } .hpick .v b { font-size: 17px; } .hpick .v span { font-size: 13.5px; }
  .cnote { font-size: 13px; } .cost { margin-top: 4px; } .cost b { font-size: 16px; } .cost span { font-size: 13px; }
  .foot { padding: 12px 0 14px; gap: 10px; }
  .fw b { font-size: 14px; } .fw span { font-size: 12.5px; }
  .fback { display: none; } .fgo { height: 52px; font-size: 17px; padding: 0 24px; }
  .fgo .long { display: none; } .fgo .short { display: inline; }
}
</style>
