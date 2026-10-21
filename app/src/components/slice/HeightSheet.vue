<template>
  <!-- A change at a height (design/paint-and-height/, A "a line you drag"): the model drawn in the two colors as the
       slider moves, the height and its layer, a layer down or up, and the color above it. The model, not the slice,
       so it's instant. -->
  <SliceSheet :open="open" wide :title="at >= 0 ? 'Change at a height' : 'Change color at a height'"
              sub="Everything above the height prints in the new color." @close="$emit('close')">
    <div class="stage">
      <ModelPicture :tris="tris" :color="colorOf(own)" :runs="runs" alt="The model in its two colors" plate turnable class="pic" />
      <span class="readout"><b class="a-num">{{ mm(snap.z) }}</b> · from layer {{ snap.n }} of {{ snap.of }}</span>
      <input v-model.number="z" class="slider" type="range" :min="layer.first" :max="Math.max(layer.first, top - layer.height)" :step="layer.height"
             aria-label="The height the color changes at" :style="{ '--k': fraction, '--below': colorOf(own), '--above': colorOf(above) }" />
    </div>
    <div class="steps">
      <button type="button" class="step" aria-label="One layer down" :disabled="snap.z <= layer.first" @click="z = Math.max(layer.first, snap.z - layer.height)">−</button>
      <span>One layer down or up</span>
      <button type="button" class="step" aria-label="One layer up" :disabled="snap.z >= top - layer.height" @click="z = snap.z + layer.height">+</button>
    </div>
    <p class="lbl">Above it</p>
    <SpoolTray :choices="choices" :on="pickK" label="The color above it" @pick="k => (pickK = k)" @hand="hand" />
    <div class="acts">
      <button v-if="at >= 0" type="button" class="a-btn ghost" @click="$emit('remove', at)">Remove it</button>
      <button v-else type="button" class="a-btn ghost" @click="$emit('close')">Cancel</button>
      <button type="button" class="a-btn accent" :disabled="pickK < 0" @click="add">{{ at >= 0 ? 'Change it' : 'Add the change' }}</button>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, watch } from 'vue'
import SliceSheet from './SliceSheet.vue'
import ModelPicture from './ModelPicture.vue'
import SpoolTray from './SpoolTray.vue'
import { drawRuns, heightColors, mm, snapToLayer, type Height } from '@/slice/paint'
import { colorWord, type PlateSpool } from '@/slice/colors'

// tris: the part as it prints (laid, not scaled); choices: the spools to pick from, the plate's first;
// start: where the slider opens (a height already set, or a flat top Bench spotted); at: which change is edited
const props = defineProps<{ open: boolean; tris: Float32Array | null; scale: number; own: number; heights: Height[]; choices: PlateSpool[]
  layer: { first: number; height: number }; start?: number | null; at: number; startSpool?: number }>()
const emit = defineEmits<{ close: []; add: [z: number, s: PlateSpool, at: number]; remove: [at: number] }>()

const top = computed(() => {
  let lo = Infinity, hi = -Infinity
  const t = props.tris
  if (t) for (let i = 2; i < t.length; i += 3) { lo = Math.min(lo, t[i]); hi = Math.max(hi, t[i]) }
  return hi > lo ? (hi - lo) * props.scale : 10
})
const z = ref(0)
const pickK = ref(-1)
const extra = ref<PlateSpool | null>(null)
const choices = computed(() => (extra.value ? [...props.choices, extra.value] : props.choices))
watch(() => props.open, (o) => {
  if (!o) return
  extra.value = null
  z.value = props.start ?? Math.round((top.value / 2) / props.layer.height) * props.layer.height
  pickK.value = props.startSpool ?? props.choices.findIndex((_, k) => k !== props.own)
}, { immediate: true })
const snap = computed(() => snapToLayer(z.value, top.value, props.layer.first, props.layer.height))
const above = computed(() => (pickK.value >= 0 ? pickK.value : props.own))
const fraction = computed(() => Math.min(1, Math.max(0, (snap.value.z - props.layer.first) / Math.max(0.01, top.value - props.layer.height - props.layer.first))))
const colorOf = (k: number) => choices.value[k]?.color || '#8A8D91'
const runs = computed(() => {
  if (!props.tris) return null
  const rest = props.heights.filter((_, i) => i !== props.at)
  const states = heightColors(props.tris, [...rest, { z: snap.value.z, spool: above.value }], props.scale, props.own)
  return markRaw(drawRuns(states, s => colorOf(s - 1)))
})
function hand(hex: string) {
  const material = props.choices[0]?.material ?? 'PLA'
  extra.value = { slot: null, material, color: hex, name: `${colorWord(hex)} ${material}`, hand: true }
  pickK.value = props.choices.length
}
function add() {
  const s = choices.value[pickK.value]
  if (s) emit('add', snap.value.z, s, props.at)
}
</script>

<style scoped>
.stage { position: relative; height: min(46vh, 380px); }
.pic { position: absolute; inset: 0; }
.readout { position: absolute; left: 12px; top: 12px; height: 34px; display: inline-flex; align-items: center; padding: 0 14px; border-radius: 99px;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); font-size: 14.5px; font-weight: 600; color: var(--a-ink-2); pointer-events: none; }
.readout b { color: var(--a-ink); margin-right: 4px; }
/* the slider stands up the right of the picture, the top of the model at the top; its track in the two colors */
.slider { position: absolute; right: 8px; top: 56px; bottom: 20px; width: 36px; margin: 0; writing-mode: vertical-lr; direction: rtl;
  appearance: none; -webkit-appearance: none; background: none; cursor: pointer; touch-action: none; }
.slider::-webkit-slider-runnable-track { width: 8px; border-radius: 4px; box-shadow: 0 0 0 1px var(--a-swatch-edge);
  background: linear-gradient(to top, var(--below) calc(var(--k) * 100%), var(--above) calc(var(--k) * 100%)); }
.slider::-moz-range-track { width: 8px; border-radius: 4px; background: linear-gradient(to top, var(--below) calc(var(--k) * 100%), var(--above) calc(var(--k) * 100%)); }
.slider::-webkit-slider-thumb { -webkit-appearance: none; width: 30px; height: 30px; margin-left: -11px; border-radius: 50%; background: var(--a-surface);
  border: 3px solid var(--a-accent); box-shadow: var(--a-card-shadow); }
.slider::-moz-range-thumb { width: 24px; height: 24px; border-radius: 50%; background: var(--a-surface); border: 3px solid var(--a-accent); }
.slider:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; border-radius: 8px; }
.steps { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.steps span { flex: 1; text-align: center; font-size: 14px; color: var(--a-ink-3); }
.step { appearance: none; border: 0; font: inherit; cursor: pointer; width: 44px; height: 44px; border-radius: 50%; background: var(--a-surface);
  box-shadow: var(--a-card-shadow); font-size: 22px; font-weight: 600; color: var(--a-ink-2); }
.step:disabled { opacity: 0.4; cursor: default; }
.lbl { font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--a-ink-3); margin: 16px 2px 6px; }
.acts { display: flex; gap: 10px; margin-top: 18px; }
.acts .a-btn { flex: 1; height: 54px; font-size: 18px; border-radius: 18px; }
.acts .a-btn.accent { flex: 1.4; }
</style>
