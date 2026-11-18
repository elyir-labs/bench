<template>
  <!-- Where supports go (design/supports-where/, A "tap the places", picked 2 November 2026): the part seen from
       below, each place that points down in its color (blue gets supports, faded leans but Orca skips it, striped
       gray "not here"), and the same places as a list with switches. A tap on a place, or its switch, changes it.
       Round 2 (C): the choice is this part's own, and None takes supports off it alone. Nothing is sliced until Done. -->
  <Teleport to="body">
    <div v-if="open" class="where" role="dialog" aria-modal="true" :aria-label="`Where supports go on ${name}`">
      <div class="top">
        <button type="button" class="ib" aria-label="Back, without changing" @click="$emit('close')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7" /></svg>
        </button>
        <span class="ttl">Where supports go<span>{{ name }}</span></span>
        <button type="button" class="a-btn accent done" @click="$emit('done', marks, where)">Done</button>
      </div>
      <div class="body">
        <div class="stage">
          <ModelPicture :tris="tris" :color="color" :runs="runs" alt="The model seen from below, its places marked" below turnable zoomable paintable
                        class="pic" @pick="tap" />
          <span v-if="said" class="said" :style="{ left: `${said.x}px`, top: `${said.y}px` }">{{ said.text }}</span>
          <span class="hint">Seen from below · tap a place · drag to turn</span>
        </div>
        <div class="side">
          <div class="seg" role="radiogroup" :aria-label="`Where supports go on ${name}`">
            <button v-for="[w, label] in WHERES" :key="w" type="button" role="radio" :aria-checked="where === w" :class="{ on: where === w }"
                    @click="where = w">{{ label }}</button>
          </div>
          <p class="say">{{ SAY[where] }}</p>
          <div v-if="found.length && where !== 'none'" class="legend" aria-hidden="true">
            <span><i class="on"></i>Supports</span><span><i class="lean"></i>Leans, none</span><span><i class="not"></i>Not here</span>
          </div>
          <div v-if="found.length" class="places" :class="{ faded: where === 'none' }" :inert="where === 'none'">
            <div v-for="(p, k) in found" :key="k" class="place">
              <i class="mk" :class="markOf(p)"></i>
              <span class="t"><b>{{ placeName(p) }}</b><span>{{ placeSize(p) }} · <em :class="{ you: isOn(p, marks) !== p.auto }">{{ placeWho(p, isOn(p, marks)) }}</em></span></span>
              <button type="button" role="switch" class="sw" :class="{ on: where !== 'none' && isOn(p, marks) }" :aria-checked="where !== 'none' && isOn(p, marks)"
                      :aria-label="`${placeName(p)}, ${placeSize(p)}: supports`" @click="flip(p)"></button>
            </div>
          </div>
          <p v-else-if="where !== 'none'" class="none">Nothing on {{ name }} points down far enough to need supports.</p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, shallowRef, watch } from 'vue'
import ModelPicture from './ModelPicture.vue'
import { drawRuns } from '@/slice/paint'
import { isOn, placeName, places, placeSize, placeWho, turned, type PartWhere, type Place } from '@/slice/places'

// angle: how far from flat a face may lean and still get supports on this printer (Orca's support_threshold_angle)
const props = defineProps<{ open: boolean; name: string; tris: Float32Array | null; scale: number; color: string
  marks: Uint8Array | null; where: PartWhere; angle?: number }>()
defineEmits<{ close: []; done: [marks: Uint8Array, where: PartWhere] }>()

const WHERES: [PartWhere, string][] = [['needed', "Where it's needed"], ['only', 'Where I say'], ['none', 'None']]

const BLUE = '#1f6fe0', PALE = '#9dbcf2', GRAY = '#a4a8b0'
const marks = shallowRef<Uint8Array>(new Uint8Array(0))
const where = ref<PartWhere>('needed')
const SAY = computed<Record<PartWhere, string>>(() => ({
  needed: 'Orca adds what it needs. Switch a place to change its mind.',
  only: 'Only the places switched on get supports.',
  none: `No supports on ${props.name}. The other parts keep theirs.`,
}))
const said = ref<{ x: number; y: number; text: string } | null>(null)
let saidTimer = 0

const found = computed<Place[]>(() => (props.tris ? places(props.tris, props.scale, props.angle ?? 30) : []))
const n = () => (props.tris?.length ?? 0) / 9

watch(() => props.open, (o) => {
  if (!o) return
  marks.value = props.marks?.length === n() ? props.marks.slice() : new Uint8Array(n())
  where.value = props.where
}, { immediate: true })

const markOf = (p: Place) => (where.value === 'none' ? 'not' : isOn(p, marks.value) ? 'on' : p.auto ? 'not' : 'lean')
// 0 the part's own color, then on, leaning, not here
const runs = computed(() => {
  const shown = new Uint8Array(n())
  for (const p of found.value) { const m = markOf(p), s = m === 'on' ? 1 : m === 'lean' ? 2 : 3; for (const t of p.tris) shown[t] = s }
  return markRaw(drawRuns(shown, s => [props.color, BLUE, PALE, GRAY][s]))
})

function flip(p: Place, at?: { x: number; y: number }) {
  const on = !isOn(p, marks.value)
  marks.value = turned(p, marks.value, n(), on)
  if (!at) return
  said.value = { ...at, text: on ? 'Supports here' : p.auto ? 'Not here' : 'No supports' }
  clearTimeout(saidTimer)
  saidTimer = window.setTimeout(() => { said.value = null }, 1400)
}
function tap(t: number, x: number, y: number) {
  if (where.value === 'none') return
  const p = t < 0 ? undefined : found.value.find(q => q.tris.includes(t))
  if (p) flip(p, { x, y })
}
</script>

<style scoped>
.where { position: fixed; inset: 0; z-index: 60; background: var(--a-bg); display: flex; flex-direction: column; padding-top: var(--safe-t, 0px); }
.top { display: flex; align-items: center; gap: 10px; padding: 10px 16px; }
.ttl { flex: 1; font-size: 18px; font-weight: 700; display: grid; line-height: 1.2; min-width: 0; }
.ttl span { font-size: 12.5px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ib { appearance: none; border: 0; cursor: pointer; width: 42px; height: 42px; border-radius: 50%; background: var(--a-surface); box-shadow: var(--a-card-shadow);
  display: grid; place-items: center; color: var(--a-ink-2); flex: none; }
.ib svg { width: 20px; height: 20px; }
.done { height: 42px; font-size: 16px; border-radius: 14px; padding: 0 18px; min-width: 0; flex: none; }
.body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.stage { position: relative; flex: 1; min-height: 180px; }
.pic { position: absolute; inset: 0; border-radius: 0; }
.hint { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); white-space: nowrap; height: 32px; display: inline-flex; align-items: center;
  padding: 0 13px; border-radius: 99px; background: var(--a-surface); box-shadow: var(--a-card-shadow); font-size: 13.5px; font-weight: 600; color: var(--a-ink-2); pointer-events: none; }
.said { position: absolute; transform: translate(-50%, -150%); background: #1f2430; color: #fff; font-size: 13.5px; font-weight: 600; padding: 7px 11px;
  border-radius: 10px; white-space: nowrap; pointer-events: none; }
.side { background: var(--a-bg); border-radius: 24px 24px 0 0; box-shadow: 0 -10px 30px rgba(16, 24, 40, 0.12); padding: 14px 18px calc(18px + var(--safe-b, 0px));
  display: grid; grid-auto-rows: max-content; gap: 10px; max-height: 52vh; overflow: auto; overscroll-behavior: contain; }
.seg { display: grid; grid-template-columns: repeat(3, 1fr); background: var(--a-surface-2); border-radius: 12px; padding: 3px; gap: 3px; }
.seg button { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 4px; border-radius: 9px; color: var(--a-ink-2); }
.seg button.on { background: var(--a-surface); color: var(--a-ink); box-shadow: 0 1px 3px rgba(16, 24, 40, 0.14); }
.say { margin: 0; font-size: 13.5px; color: var(--a-ink-3); line-height: 1.35; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12.5px; color: var(--a-ink-3); font-weight: 600; }
.legend i, .mk { display: inline-block; width: 12px; height: 12px; border-radius: 4px; vertical-align: -1px; margin-right: 5px; }
.on { background: #1f6fe0; }
.lean { background: color-mix(in srgb, #1f6fe0 40%, transparent); border: 1.5px dashed #1f6fe0; }
.not { background: repeating-linear-gradient(135deg, #a4a8b0 0 3px, #c9ccd2 3px 6px); }
.places { background: var(--a-surface); border-radius: 16px; box-shadow: var(--a-card-shadow); overflow: hidden; }
.places.faded { opacity: 0.45; }
.place { display: flex; align-items: center; gap: 11px; padding: 10px 12px; border-top: 1px solid var(--a-line); }
.place:first-child { border-top: 0; }
.place .mk { width: 28px; height: 28px; border-radius: 9px; margin: 0; flex: none; }
.place .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.place .t b { font-size: 15.5px; }
.place .t > span { font-size: 12.5px; color: var(--a-ink-3); line-height: 1.3; }
.place em { font-style: normal; }
.place em.you { color: var(--a-accent-text); font-weight: 600; }
.sw { appearance: none; border: 0; cursor: pointer; width: 46px; height: 28px; border-radius: 99px; background: var(--a-surface-2); position: relative; flex: none; }
.sw::after { content: ''; position: absolute; left: 3px; top: 3px; width: 22px; height: 22px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(16, 24, 40, 0.25); transition: left 0.15s; }
.sw.on { background: var(--a-accent); }
.sw.on::after { left: 21px; }
.none { margin: 0; font-size: 14.5px; color: var(--a-ink-2); }
/* the printer's own screen, and any wide one: the picture left, the list in a column on the right */
@media (min-aspect-ratio: 5/4) {
  .body { flex-direction: row; }
  .side { width: min(340px, 42vw); max-height: none; border-radius: 0; box-shadow: none; border-left: 1px solid var(--a-line); align-content: start; }
}
</style>
