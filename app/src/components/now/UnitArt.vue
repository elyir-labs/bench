<template>
  <!-- The filament unit, drawn for swapping a spool (design/slots/, B): four spools in a box, the
       slot being swapped marked, and which way the filament goes. Amber is a person's turn. -->
  <svg class="unit-art" viewBox="0 0 120 120" role="img" :aria-label="label">
    <rect x="14" y="52" width="92" height="42" rx="10" class="box" />
    <line v-if="art !== 'insert'" :x1="x" y1="52" :x2="x" :y2="art === 'still' ? 30 : 50" class="fil" :style="{ stroke: color || 'var(--a-ink-3)' }" />
    <template v-for="(cx, i) in XS" :key="i">
      <circle :cx="cx" cy="72" r="8" :class="['spool', { mark: i === pos, you }]" :style="i === pos && color && art !== 'insert' ? { fill: color } : {}" />
      <circle :cx="cx" cy="72" r="2.4" class="hub" />
    </template>
    <g v-if="art === 'back' || art === 'insert'" :class="['arrow', { you }]">
      <path :d="`M${x} 18v30`" />
      <path :d="`M${x - 7} 40l7 8 7-8`" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ art: string; slot: number; color?: string | null; you?: boolean }>()
const XS = [30, 50, 70, 90]
const pos = computed(() => ((props.slot % 4) + 4) % 4)
const x = computed(() => XS[pos.value])
const label = computed(() => (props.art === 'back' ? 'Pulling the filament back into the unit'
  : props.art === 'insert' ? 'Push the new spool\'s end into the slot' : 'The filament unit'))
</script>

<style scoped>
.unit-art { width: 100%; height: 100%; display: block; }
.box { fill: var(--a-surface-2); stroke: var(--a-line); }
.fil { stroke-width: 2.5; stroke-linecap: round; }
.spool { fill: color-mix(in srgb, var(--a-ink-3) 45%, var(--a-surface-2)); stroke: var(--a-line); stroke-width: 1; }
.spool.mark { stroke: var(--a-accent); stroke-width: 2.5; }
.spool.mark.you { stroke: var(--a-amber); }
.hub { fill: var(--a-bg); }
.arrow path { fill: none; stroke: var(--a-accent); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.arrow.you path { stroke: var(--a-amber); }
@media (prefers-reduced-motion: no-preference) {
  .arrow { animation: nudge 1.4s ease-in-out infinite; }
  @keyframes nudge { 50% { transform: translateY(4px); } }
}
</style>
