<template>
  <!-- The toolhead, drawn: what's in it and which way it's moving (design/change-filament/, B).
       Amber arrows are a person's turn, blue ones the printer's. -->
  <svg class="head-art" viewBox="-6 -26 172 232" role="img" :aria-label="label">
    <circle v-if="hot" cx="80" cy="160" r="38" class="glow" />
    <rect x="70" y="-24" width="20" height="82" rx="5" class="tube" />
    <rect x="28" y="54" width="104" height="88" rx="18" class="body" />
    <circle cx="62" cy="96" r="11" class="gear" /><circle cx="98" cy="96" r="11" class="gear" />
    <rect x="57" y="142" width="46" height="22" rx="5" :class="hot ? 'block hot' : 'block'" />
    <path d="M67 164h26l-8 16h-10z" :class="hot ? 'nozzle hot' : 'nozzle'" />

    <template v-if="fil">
      <line x1="80" :y1="fil.y1" x2="80" :y2="fil.y2" class="fil-edge" />
      <line x1="80" :y1="fil.y1" x2="80" :y2="fil.y2" class="fil" :style="{ stroke: fil.c }" />
    </template>
    <template v-if="art === 'purge'">
      <path d="M80 184q-16 4-9 13q9 6 17-1q5-8-6-8" class="fil-edge thin" />
      <path d="M80 184q-16 4-9 13q9 6 17-1q5-8-6-8" class="fil thin" :style="{ stroke: inColor }" />
    </template>
    <g v-if="arrow" :class="['arrow', { you }]">
      <path :d="`M132 ${arrow.from}V${arrow.to}`" />
      <path :d="`M120 ${arrow.to + arrow.d * 13}L132 ${arrow.to}L144 ${arrow.to + arrow.d * 13}`" />
    </g>
    <g v-if="art === 'done'">
      <circle cx="128" cy="56" r="17" class="ok" />
      <path d="M120 56l6 6 10-11" class="tick" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  art: 'still' | 'heat' | 'out' | 'pull' | 'push' | 'purge' | 'done'
  out?: string | null
  in?: string | null
  you?: boolean
}>()

const outColor = computed(() => props.out || '#8A8D91')
const inColor = computed(() => props.in || '#8A8D91')
const hot = computed(() => ['heat', 'out', 'purge', 'done'].includes(props.art))

const fil = computed(() => {
  switch (props.art) {
    case 'still': case 'heat': return { c: outColor.value, y1: 2, y2: 170 }
    case 'out': return { c: outColor.value, y1: 2, y2: 104 }
    case 'pull': return { c: outColor.value, y1: -20, y2: 34 }
    case 'push': return { c: inColor.value, y1: -20, y2: 50 }
    case 'purge': return { c: inColor.value, y1: 2, y2: 172 }
    case 'done': return { c: inColor.value, y1: 2, y2: 170 }
  }
  return null
})

const arrow = computed(() => {
  switch (props.art) {
    case 'out': return { from: 130, to: 70, d: 1 }
    case 'pull': return { from: 110, to: 22, d: 1 }
    case 'push': return { from: 16, to: 96, d: -1 }
  }
  return null
})

const label = computed(() => ({
  still: 'The toolhead', heat: 'The nozzle warming up', out: 'Filament coming out of the head',
  pull: 'Pull the filament up out of the head', push: 'Push the new filament down into the head',
  purge: 'New filament coming out of the nozzle', done: 'New filament loaded',
}[props.art]))
</script>

<style scoped>
.head-art { display: block; width: 100%; height: 100%; overflow: visible; }
.glow { fill: var(--a-amber); opacity: .16; }
.tube { fill: none; stroke: var(--a-ink-3); stroke-opacity: .6; stroke-width: 2; }
.body { fill: var(--a-surface-2); }
.gear { fill: var(--a-bg); opacity: .55; }
.block { fill: var(--a-surface-2); }
.block.hot { fill: #d9643a; }
.nozzle { fill: var(--a-ink-3); }
.nozzle.hot { fill: #e8743b; }
.fil-edge { stroke: rgba(127, 127, 127, .55); stroke-width: 11; stroke-linecap: round; fill: none; }
.fil { stroke-width: 7; stroke-linecap: round; fill: none; }
.fil-edge.thin { stroke-width: 10; }
.fil.thin { stroke-width: 6; }
.arrow path { stroke: var(--a-accent); stroke-width: 7; stroke-linecap: round; stroke-linejoin: round; fill: none; }
.arrow.you path { stroke: var(--a-amber); }
.ok { fill: var(--a-green); }
.tick { stroke: var(--a-green-ink); stroke-width: 4.5; fill: none; stroke-linecap: round; stroke-linejoin: round; }
</style>
