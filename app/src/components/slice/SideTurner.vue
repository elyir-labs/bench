<template>
  <!-- Any side down (design/any-side/, C): the part as it would lie. Tap a side and it lights up and asks; the turn
       buttons follow the picture's angle; Undo steps back; the slicer's own sides stay below as shortcuts. Nothing is
       sliced until Done. -->
  <div ref="root" class="turner">
    <ModelPicture ref="pic" :tris="shown.tris" :color="shown.color" :runs="shown.runs" :alt="nowTitle" plate turnable paintable
                  class="big" @pick="tap">
      <span v-if="!asking && !history.length" class="hint" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11m0-1.5a1.5 1.5 0 0 1 3 0V11m0-.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-.6a5 5 0 0 1-3.9-1.9L4.6 15.4a1.5 1.5 0 0 1 2.3-1.9L9 15" /></svg>
        Tap a side to put it down
      </span>
      <button v-if="history.length" type="button" class="undo" @click="undo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></svg>Undo
      </button>
    </ModelPicture>

    <div class="turns">
      <button type="button" class="tb wide" @click="go('flip')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 4v13M3.5 13.5 7 17l3.5-3.5M17 20V7M13.5 10.5 17 7l3.5 3.5" /></svg>Flip over
      </button>
      <button v-for="t in TURNS" :key="t.k" type="button" class="tb" :aria-label="t.label" :title="t.label" @click="go(t.k)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="t.d" /></svg>
      </button>
    </div>

    <div class="now" :class="{ ask: asking }" aria-live="polite">
      <template v-if="asking">
        <span class="t"><b>That side down</b><span>{{ standWords(asking.stand) }}</span></span>
        <button type="button" class="a-btn ghost cancel" @click="asking = null">Cancel</button>
        <button type="button" class="a-btn accent put" @click="putDown">Put it down</button>
      </template>
      <template v-else>
        <span class="t"><b>{{ nowTitle }}</b><span>{{ nowNote }}</span></span>
        <span v-if="changed" class="tm later">{{ laterNote }}</span>
        <span v-else-if="time" class="tm a-num"><b>{{ time }}</b><span>{{ timeNote }}</span></span>
      </template>
    </div>

    <template v-if="options.length">
      <p class="lbl">Suggested</p>
      <div class="sugg">
        <button v-for="o in tiles" :key="o.key" type="button" class="sg" :class="{ on: o.key === match?.key }" @click="choose(o.normal)">
          <ModelPicture :tris="o.tris" :color="color" :alt="o.title" plate class="tile" />
          <span class="t"><b>{{ o.title }}<i v-for="tag in o.tags" :key="tag" class="tag">{{ tag }}</i></b><span>{{ o.note }}</span></span>
        </button>
      </div>
    </template>

    <button v-if="ownDone" type="button" class="a-btn accent done" @click="$emit('pick', chosen())">Done</button>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onMounted, ref, shallowRef } from 'vue'
import { layOn } from '@/slice/stl'
import { area, sameSide, type SideOption } from '@/slice/sides'
import { downOf, faceAt, lit, onto, poseOf, posed, settle, standing, turn, type Pose, type Turn } from '@/slice/turn'
import ModelPicture from './ModelPicture.vue'

// cur: the side down now (null: as in the file); time: the slice's time, shown while that's still the side down.
// ownDone false: the sheet around it has its own Done, and reads chosen() as it closes (the Bench Box).
const props = withDefaults(defineProps<{ options: SideOption[]; file: Float32Array; color: string; cur: number[] | null
  time?: string; timeNote?: string; laterNote?: string; ownDone?: boolean }>(),
{ time: '', timeNote: 'the plate', laterNote: 'Sliced on Done', ownDone: true })
defineEmits<{ pick: [normal: number[] | null] }>()

const TURNS: { k: Turn; label: string; d: string }[] = [
  { k: 'rollLeft', label: 'Roll left', d: 'M19 16a7 7 0 0 0-14 0M2.5 13 5 16l3-2.5' },
  { k: 'rollRight', label: 'Roll right', d: 'M5 16a7 7 0 0 1 14 0M21.5 13 19 16l-3-2.5' },
  { k: 'tipForward', label: 'Tip towards you', d: 'M16 5a7 7 0 0 0 0 14M13 21.5 16 19l-2.5-3' },
  { k: 'tipBack', label: 'Tip away', d: 'M16 19a7 7 0 0 1 0-14M13 2.5 16 5l-2.5 3' },
]

const root = ref<HTMLElement | null>(null)
const pic = ref<InstanceType<typeof ModelPicture> | null>(null)
const accent = ref('#1f6fe0')
onMounted(() => { if (root.value) accent.value = getComputedStyle(root.value).getPropertyValue('--a-accent').trim() || accent.value })

const pose = shallowRef<Pose>(poseOf(props.cur))
const history = shallowRef<Pose[]>([])
const laid = computed(() => markRaw(posed(props.file, pose.value)))
const asking = shallowRef<{ normal: number[]; members: number[]; base: Float32Array; stand: { tall: number; touches: number } } | null>(null)

const shown = computed(() => {
  const a = asking.value
  if (!a) return { tris: laid.value, color: props.color, runs: null }
  const l = lit(a.base, a.members)
  return { tris: markRaw(l.tris), color: accent.value, runs: [{ end: l.end, color: props.color }] }
})

const down = computed(() => downOf(pose.value))
const isDown = (n: number[] | null) => (n == null ? down.value == null : sameSide(n, down.value))
const changed = computed(() => !isDown(props.cur))
const stand = computed(() => standing(laid.value))
// a round wall is one suggestion, but any of its facets can be down: those match it by how it stands
const match = computed(() => props.options.find(o => isDown(o.normal)) ?? props.options.find(o => o.contact != null && o.tall != null
  && Math.round(o.tall) === Math.round(stand.value.tall) && Math.abs(o.contact - stand.value.touches) <= 0.1 * o.contact))
const nowTitle = computed(() => match.value?.title ?? `${Math.round(stand.value.tall)} mm tall`)
const nowNote = computed(() => match.value?.note ?? standWords(stand.value, false))
function standWords(s: { tall: number; touches: number }, tall = true) {
  const t = tall ? ` · ${Math.round(s.tall)} mm tall` : ''
  return s.touches < 1 ? `On an edge or a corner${t}` : `Touches ${area(s.touches)}${t}`
}

const tiles = computed(() => props.options.map(o => ({ ...o, tris: o.normal ? markRaw(layOn(props.file, o.normal)) : props.file })))

function to(p: Pose) {
  asking.value = null
  if (JSON.stringify(p) === JSON.stringify(pose.value)) return
  history.value = [...history.value, pose.value]
  pose.value = p
}
function go(t: Turn) { to(settle(turn(pose.value, t, pic.value?.angle() ?? -0.6), props.file)) }
function choose(n: number[] | null) { if (!isDown(n)) to(poseOf(n)) }
function undo() {
  asking.value = null
  const h = history.value
  if (!h.length) return
  pose.value = h[h.length - 1]
  history.value = h.slice(0, -1)
}
function tap(t: number) {
  const base = shown.value.tris
  const f = t >= 0 ? faceAt(base, t) : null
  if (!f || f.normal[2] < -0.99) { asking.value = null; return }
  asking.value = { ...f, base, stand: standing(posed(props.file, onto(pose.value, f.normal))) }
}
function putDown() { if (asking.value) to(onto(pose.value, asking.value.normal)) }

/** The side that goes down as the sheet stands now. */
const chosen = () => down.value
defineExpose({ chosen })
</script>

<style scoped>
.turner { display: grid; gap: 10px; }
.big { height: 210px; border-radius: 20px; }
.hint { position: absolute; left: 10px; bottom: 10px; display: inline-flex; gap: 6px; align-items: center; background: var(--a-surface); border-radius: 16px; padding: 6px 11px; font-size: 13px; font-weight: 600; color: var(--a-ink-2); box-shadow: var(--a-card-shadow); pointer-events: none; }
.hint svg { width: 16px; height: 16px; }
.undo { appearance: none; border: 0; font: inherit; cursor: pointer; position: absolute; right: 10px; top: 10px; display: inline-flex; gap: 6px; align-items: center; background: var(--a-surface); color: var(--a-ink); border-radius: 16px; padding: 7px 12px; font-size: 14px; font-weight: 600; box-shadow: var(--a-card-shadow); }
.undo svg { width: 15px; height: 15px; }
.turns { display: flex; gap: 8px; }
.tb { appearance: none; border: 0; font: inherit; cursor: pointer; height: 46px; width: 46px; flex: none; border-radius: 23px; background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); display: inline-flex; align-items: center; justify-content: center; gap: 7px; font-size: 15px; font-weight: 600; }
.tb.wide { flex: 1; width: auto; }
.tb svg { width: 21px; height: 21px; }
.tb:active, .sg:active, .undo:active { transform: scale(0.97); }
.tb:focus-visible, .sg:focus-visible, .undo:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.now { display: flex; align-items: center; gap: 10px; padding: 12px 14px; background: var(--a-surface); border-radius: 16px; box-shadow: var(--a-card-shadow); }
.now.ask { box-shadow: 0 0 0 2px var(--a-accent), var(--a-card-shadow); }
.now .t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.now .t b { font-size: 16.5px; }
.now .t span { font-size: 13px; color: var(--a-ink-3); line-height: 1.3; }
.now .tm { text-align: right; display: grid; gap: 1px; flex: none; }
.now .tm b { font-size: 16.5px; }
.now .tm span { font-size: 12.5px; color: var(--a-ink-3); }
.now .later { font-size: 13.5px; font-weight: 600; color: var(--a-ink-3); }
.now .a-btn { height: 40px; padding: 0 14px; font-size: 15px; flex: none; }
.now .cancel { border: 0; background: none; padding: 0 6px; }
.lbl { margin: 6px 0 0; font-size: 11.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--a-ink-3); }
.sugg { display: grid; gap: 7px; }
.sg { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px; background: var(--a-surface); border-radius: 14px; padding: 6px 12px 6px 6px; border: 2px solid transparent; box-shadow: var(--a-card-shadow); }
.sg.on { border-color: var(--a-accent); }
.sg .tile { width: 68px; height: 51px; border-radius: 9px; flex: none; }
.sg .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.sg .t b { font-size: 15px; }
.sg .t b .tag { white-space: nowrap; display: inline-block; font-style: normal; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-accent-text); margin-left: 6px; vertical-align: 1px; }
.sg .t span { font-size: 12.5px; color: var(--a-ink-3); line-height: 1.3; }
.done { width: 100%; height: 52px; font-size: 17px; margin-top: 6px; }
</style>
