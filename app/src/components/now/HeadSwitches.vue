<template>
  <!-- Where the filament has got to, beside a load or unload (design/filament-units/, A): a light at the extruder
       (its switch before the gears) and one at the hotend (its switch after them), only where the printer has that switch. Named for the place, not the
       part: green is filament there, red is where it stopped. -->
  <svg class="head-switches" viewBox="0 0 236 330" role="img" :aria-label="look.label">
    <rect x="119" y="0" width="12" height="236" rx="4" class="tube" />
    <rect v-if="reachY" x="122" y="0" width="6" :height="reachY" rx="3" class="fil" :style="{ fill: color }" />
    <text x="140" y="22" class="note">from the unit</text>

    <!-- the left gear turns clockwise to pull filament down between them, the right one the other way -->
    <g :class="['gears', look.gears]">
      <g class="gear cw"><circle cx="106" cy="160" r="13" class="teeth" /><circle cx="106" cy="160" r="4" class="hub" /></g>
      <g class="gear ccw"><circle cx="144" cy="160" r="13" class="teeth" /><circle cx="144" cy="160" r="4" class="hub" /></g>
    </g>
    <text x="164" y="165" class="note">gears</text>

    <rect x="108" y="236" width="34" height="56" rx="5" class="hotend" />
    <path d="M114 292h22l-11 18z" class="nozzle" />

    <g v-for="sw in switches" :key="sw.name">
      <rect x="142" :y="sw.y - 11" width="22" height="22" rx="6" :class="['switch', sw.look]" />
      <text x="172" :y="sw.y + 5" class="name">{{ sw.title }}</text>
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentHeadSwitches } from '@/intent/types'
import { headSwitchesLook } from './headSwitches'

const props = defineProps<{ switches: IntentHeadSwitches }>()

const look = computed(() => headSwitchesLook(props.switches))
const color = computed(() => props.switches.color || '#cfd5df')
const reachY = computed(() => ({ none: 0, extruder: 150, hotend: 250 }[look.value.reach]))
const switches = computed(() => [
  { name: 'extruder', title: 'Extruder', y: 110, look: look.value.extruder },
  ...(look.value.hotend ? [{ name: 'hotend', title: 'Hotend', y: 205, look: look.value.hotend }] : []),
])
</script>

<style scoped>
.head-switches { display: block; width: 100%; height: 100%; overflow: visible; }
.tube { fill: var(--a-surface-2); }
.fil { stroke: rgba(127, 127, 127, .55); stroke-width: 1; }
.teeth { fill: none; stroke: var(--a-ink-3); stroke-width: 4; stroke-dasharray: 4 3.2; }
.hub { fill: var(--a-ink-3); }
.gear { transform-box: fill-box; transform-origin: center; }
.gears.in .teeth, .gears.out .teeth { stroke: var(--a-accent); }
.gears.in .cw, .gears.out .ccw { animation: turn 1.2s linear infinite; }
.gears.in .ccw, .gears.out .cw { animation: turn 1.2s linear infinite reverse; }
@keyframes turn { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .gear { animation: none !important; } }
.hotend { fill: var(--a-surface-2); stroke: var(--a-amber); stroke-width: 2; }
.nozzle { fill: var(--a-amber); }
.switch { stroke-width: 2; }
.switch.dark { fill: var(--a-surface-2); stroke: var(--a-ink-3); }
.switch.lit { fill: var(--a-green); stroke: var(--a-green); }
.switch.bad { fill: var(--a-red); stroke: var(--a-red); }
.name { fill: var(--a-ink); font: 700 14px var(--a-font); }
.note { fill: var(--a-ink-3); font: 12px var(--a-font); }
</style>
