<template>
  <!-- Painting (design/paint-and-height/, A "tap to fill, everywhere", picked 21 October 2026): the part full screen
       with the spools along the bottom. A tap paints from where it lands up to the next sharp edge (or just a spot);
       a drag turns it, a pinch zooms. Nothing is sliced until Done. -->
  <Teleport to="body">
    <div v-if="open" class="paint" role="dialog" aria-modal="true" :aria-label="`Paint ${name}`">
      <div class="top">
        <button type="button" class="ib" aria-label="Back, without painting" @click="$emit('close')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7" /></svg>
        </button>
        <span class="ttl">Paint<span>{{ name }}</span></span>
        <button type="button" class="ib" aria-label="Undo" :disabled="!undo.length" @click="back">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 7L4 12l5 5" /><path d="M4 12h10a6 6 0 010 12" transform="translate(0,-6)" /></svg>
        </button>
        <button type="button" class="a-btn accent done" @click="finish">Done</button>
      </div>
      <div class="body">
        <div class="stage">
          <ModelPicture :tris="tris" :color="colorOf(own)" :runs="runs" alt="The model, painted" plate turnable zoomable paintable class="pic" @pick="tap" />
          <span v-if="said" class="said" :style="{ left: `${said.x}px`, top: `${said.y}px` }">{{ said.text }}</span>
          <span class="hint">Tap to paint · drag to turn · pinch to zoom</span>
        </div>
        <div class="side">
          <p class="lbl">Paint with</p>
          <SpoolTray :choices="palette" :on="pen" label="Paint with" @pick="k => (pen = k)" @hand="hand" />
          <div class="seg" role="radiogroup" aria-label="How far a tap paints">
            <button type="button" role="radio" :aria-checked="mode === 'edge'" :class="{ on: mode === 'edge' }" @click="mode = 'edge'">Up to an edge</button>
            <button type="button" role="radio" :aria-checked="mode === 'spot'" :class="{ on: mode === 'spot' }" @click="mode = 'spot'">Just a spot</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, shallowRef, watch } from 'vue'
import ModelPicture from './ModelPicture.vue'
import SpoolTray from './SpoolTray.vue'
import { drawRuns, fillFrom, neighbours, spotFrom } from '@/slice/paint'
import { colorWord, type PlateSpool } from '@/slice/colors'

// tris: the part as it prints; paint: its colors so far (0 its own, k choices[k - 1]); own: its own color in choices
const props = defineProps<{ open: boolean; name: string; tris: Float32Array | null; paint: Uint8Array | null; own: number; choices: PlateSpool[] }>()
const emit = defineEmits<{ close: []; done: [states: Uint8Array, palette: PlateSpool[]] }>()

const states = shallowRef<Uint8Array>(new Uint8Array(0))
const undo = ref<Uint8Array[]>([])
const extra = ref<PlateSpool[]>([])
const palette = computed(() => [...props.choices, ...extra.value])
const pen = ref(0)
const mode = ref<'edge' | 'spot'>('edge')
const said = ref<{ x: number; y: number; text: string } | null>(null)
let near: Int32Array | null = null
let saidTimer = 0

watch(() => props.open, (o) => {
  if (!o || !props.tris) return
  const n = props.tris.length / 9
  states.value = props.paint?.length === n ? props.paint.slice() : new Uint8Array(n)
  undo.value = []
  extra.value = []
  near = null
  pen.value = palette.value.findIndex((_, k) => k !== props.own)
  if (pen.value < 0) pen.value = 0
}, { immediate: true })

const colorOf = (k: number) => palette.value[k]?.color || '#8A8D91'
const runs = computed(() => markRaw(drawRuns(states.value, s => colorOf(s ? s - 1 : props.own))))

function tap(t: number, x: number, y: number) {
  if (t < 0 || !props.tris) return
  near ??= neighbours(props.tris)
  const area = mode.value === 'edge' ? fillFrom(props.tris, near, t) : spotFrom(props.tris, near, t)
  const to = pen.value === props.own ? 0 : pen.value + 1
  if (area.every(i => states.value[i] === to)) return
  undo.value = [...undo.value.slice(-29), states.value]
  const next = states.value.slice()
  for (const i of area) next[i] = to
  states.value = next
  const word = colorWord(palette.value[pen.value]?.color)
  said.value = { x, y, text: mode.value === 'edge' ? `${word} up to the edge` : `A spot of ${word.toLowerCase()}` }
  clearTimeout(saidTimer)
  saidTimer = window.setTimeout(() => { said.value = null }, 1600)
}
function back() {
  const last = undo.value[undo.value.length - 1]
  if (!last) return
  undo.value = undo.value.slice(0, -1)
  states.value = last
}
function hand(hex: string) {
  const material = props.choices[0]?.material ?? 'PLA'
  extra.value = [...extra.value, { slot: null, material, color: hex, name: `${colorWord(hex)} ${material}`, hand: true }]
  pen.value = palette.value.length - 1
}
function finish() { emit('done', states.value, palette.value) }
</script>

<style scoped>
.paint { position: fixed; inset: 0; z-index: 60; background: var(--a-bg); display: flex; flex-direction: column;
  padding-top: var(--safe-t, 0px); }
.top { display: flex; align-items: center; gap: 10px; padding: 10px 16px; }
.ttl { flex: 1; font-size: 18px; font-weight: 700; display: grid; line-height: 1.2; }
.ttl span { font-size: 12.5px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ib { appearance: none; border: 0; cursor: pointer; width: 42px; height: 42px; border-radius: 50%; background: var(--a-surface); box-shadow: var(--a-card-shadow);
  display: grid; place-items: center; color: var(--a-ink-2); flex: none; }
.ib svg { width: 20px; height: 20px; }
.ib:disabled { opacity: 0.4; cursor: default; }
.done { height: 42px; font-size: 16px; border-radius: 14px; padding: 0 18px; }
.body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.stage { position: relative; flex: 1; min-height: 0; }
.pic { position: absolute; inset: 0; border-radius: 0; }
.hint { position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); white-space: nowrap; height: 34px; display: inline-flex; align-items: center;
  padding: 0 14px; border-radius: 99px; background: var(--a-surface); box-shadow: var(--a-card-shadow); font-size: 14px; font-weight: 600; color: var(--a-ink-2); pointer-events: none; }
.said { position: absolute; transform: translate(-50%, -150%); background: #1f2430; color: #fff; font-size: 13.5px; font-weight: 600; padding: 7px 11px;
  border-radius: 10px; white-space: nowrap; pointer-events: none; }
.side { background: var(--a-bg); border-radius: 24px 24px 0 0; box-shadow: 0 -10px 30px rgba(16, 24, 40, 0.12); padding: 14px 18px calc(18px + var(--safe-b, 0px));
  display: grid; gap: 10px; }
.lbl { margin: 0; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--a-ink-3); }
.seg { display: grid; grid-template-columns: 1fr 1fr; background: var(--a-surface-2); border-radius: 12px; padding: 3px; gap: 3px; }
.seg button { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 4px; border-radius: 9px; color: var(--a-ink-2); }
.seg button.on { background: var(--a-surface); color: var(--a-ink); box-shadow: 0 1px 3px rgba(16, 24, 40, 0.14); }
/* the printer's own screen, and any wide one: the picture left, the spools in a column on the right */
@media (min-aspect-ratio: 5/4) {
  .body { flex-direction: row; }
  .side { width: min(300px, 38vw); border-radius: 0; box-shadow: none; border-left: 1px solid var(--a-line); align-content: start; overflow: auto; }
  .side :deep(.tray) { flex-wrap: wrap; overflow: visible; }
}
</style>
