<template>
  <!-- Which side down? (the printer's own design/orientation/, on the box 11 October 2026): every side a part can rest
       on, drawn lying so, from the model page's Lying tile and the plan's move sheet. A model of several parts lists
       them first. Each pick is kept with the model at once; Done only closes. -->
  <HowSheet :open="open" title="Which side down?" :model="name" :kept="kept" :sub="sub" @close="$emit('close')">
    <p v-if="!view" class="none muted">Reading its sides…</p>
    <template v-else-if="part == null">
      <button v-for="p in view.parts" :key="p.n" class="pick" @click="at = p.n">
        <span class="ppic"><ModelPicture v-if="laid[p.n]" :tris="laid[p.n]" :color="color" alt="" plate /></span>
        <span class="t"><b>{{ partName(p.name) }}</b><span>{{ partWords(p, view.from).value }}<template v-if="partWords(p, view.from).line"> · {{ partWords(p, view.from).line }}</template></span></span>
        <span class="go" aria-hidden="true">›</span>
      </button>
    </template>
    <div v-else class="sides">
      <button v-if="view.parts.length > 1" class="back" @click="at = null">‹ All {{ view.parts.length }} parts</button>
      <SidePicks v-if="file && options.length > 1" :options="options" :file="file" :color="color" :time="time" :time-note="timeNote" @pick="(n) => $emit('pick', part!.n, n)" />
      <p v-else-if="!file && tris?.length" class="none muted">The box can't draw this file, so it prints as the file has it.</p>
      <p v-else-if="!file" class="none muted">Reading the model…</p>
      <p v-else class="none muted">It only sits one way.</p>
    </div>
  </HowSheet>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, watch } from 'vue'
import ModelPicture from '@/components/slice/ModelPicture.vue'
import SidePicks from '@/components/slice/SidePicks.vue'
import { layOn } from '@/slice/stl'
import { partName, partOptions, partWords, type SidesView } from '../sides'
import HowSheet from './HowSheet.vue'

const props = withDefaults(defineProps<{ open: boolean; view: SidesView | null; tris: (Float32Array | null)[] | null; color: string; name: string
  time?: string; timeNote?: string }>(), { time: '', timeNote: 'set up' })
defineEmits<{ close: []; pick: [part: number, normal: number[] | null] }>()

const at = ref<number | null>(null)
watch(() => props.open, (o) => { if (o) at.value = null })
const part = computed(() => (props.view?.parts.length === 1 ? props.view.parts[0] : props.view?.parts.find((p) => p.n === at.value) ?? null))
const file = computed(() => (part.value ? props.tris?.[part.value.n] ?? null : null))
const options = computed(() => (part.value && props.view ? partOptions(part.value, props.view.from) : []))
// each part in the list, lying the way it's down now
const laid = computed(() => (props.view?.parts ?? []).map((p) => {
  const t = props.tris?.[p.n]
  return t ? markRaw(p.normal ? layOn(t, p.normal) : t) : null
}))
const sub = computed(() => (part.value == null ? 'Each part rests on a side of its own. Tap one to pick it.'
  : `${props.view && props.view.parts.length > 1 ? `${partName(part.value.name)}: tap` : 'Tap'} the side that goes on the plate. It's sliced once you pick.`))
const kept = computed(() => `Kept with ${props.name || 'the model'}: next time, and on whichever printer takes it, it lies this way.`)
</script>

<style scoped>
.muted { color: var(--a-ink-3); }
.none { margin: 0; padding: 14px 22px; border-top: 1px solid var(--a-line); font-size: 16px; }
.pick { appearance: none; border: 0; border-top: 1px solid var(--a-line); width: 100%; font: inherit; color: inherit; text-align: left; cursor: pointer;
        display: flex; gap: 14px; align-items: center; padding: 10px 22px; background: none; }
.pick:focus-visible, .back:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.ppic { width: 84px; height: 64px; flex: none; border-radius: 12px; overflow: hidden; background: var(--a-surface-2); }
.ppic > * { width: 100%; height: 100%; }
.t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.t b { font-size: 20px; } .t span { color: var(--a-ink-3); font-size: 15px; }
.go { color: var(--a-ink-3); font-size: 26px; }
.sides { display: grid; gap: 10px; padding: 4px 18px 18px; border-top: 1px solid var(--a-line); }
.back { appearance: none; border: 0; background: none; font: inherit; font-size: 16px; font-weight: 650; color: var(--a-accent-text); cursor: pointer;
        justify-self: start; padding: 10px 0 0; }
.sides > .none { border-top: 0; padding: 10px 4px; }
@media (max-width: 599px) {
  .pick { padding: 10px 16px; } .t b { font-size: 17px; } .t span { font-size: 13.5px; }
  .ppic { width: 68px; height: 52px; }
  .sides { padding: 4px 12px 14px; }
}
</style>
