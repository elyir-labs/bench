<template>
  <!-- Drawn pictures of the units and their boards (design/unit-setup/, B): shapes only, no photos or logos -->
  <svg :viewBox="'0 0 140 70'" class="uart" aria-hidden="true">
    <template v-if="kind === 'box_turtle'">
      <rect x="6" y="40" width="128" height="20" rx="6" class="body" />
      <circle v-for="(c, i) in four" :key="i" :cx="22 + i * 32" cy="38" r="11" :fill="c" class="spool" />
      <circle v-for="(c, i) in four" :key="'h' + i" :cx="22 + i * 32" cy="38" r="3.5" class="hub" />
    </template>
    <template v-else-if="kind === 'night_owl'">
      <rect x="10" y="44" width="120" height="18" rx="6" class="body" />
      <circle cx="46" cy="34" r="20" fill="#e5534b" class="spool" /><circle cx="46" cy="34" r="6" class="hub" />
      <circle cx="94" cy="34" r="20" fill="#e9ebef" class="spool" /><circle cx="94" cy="34" r="6" class="hub" />
    </template>
    <template v-else-if="kind === 'ercf_v2'">
      <rect x="6" y="50" width="128" height="5" rx="2" class="body" />
      <g v-for="(c, i) in eight" :key="i">
        <line :x1="20 + i * 14" y1="6" :x2="20 + i * 14" y2="42" class="fil" />
        <rect :x="16 + i * 14" y="40" width="8" height="12" rx="1.5" :fill="c" />
      </g>
    </template>
    <template v-else-if="kind === 'tradrack'">
      <rect x="20" y="38" width="100" height="20" rx="5" class="body" />
      <g v-for="(c, i) in eight" :key="i">
        <line :x1="32 + i * 11" y1="12" :x2="32 + i * 11" y2="36" class="fil" />
        <rect :x="29 + i * 11" y="32" width="6" height="6" rx="1" :fill="c" />
      </g>
    </template>
    <template v-else-if="kind === 'other'">
      <rect x="45" y="12" width="50" height="46" rx="10" class="ask" />
      <text x="70" y="44" text-anchor="middle" class="q">?</text>
    </template>
    <template v-else>
      <!-- a board: its color by family -->
      <rect x="30" y="12" width="80" height="48" rx="4" :fill="boardColor" />
      <rect x="62" y="28" width="16" height="16" rx="1.5" fill="#1d1f24" />
      <circle cx="100" cy="20" r="2.5" fill="#f2c94c" />
      <rect v-for="i in 4" :key="'p' + i" :x="34 + (i - 1) * 10" y="52" width="6" height="5" fill="#e9ebef" opacity=".85" />
      <rect v-for="i in 3" :key="'r' + i" x="86" :y="30 + (i - 1) * 8" width="14" height="4" fill="#e9ebef" opacity=".75" />
    </template>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ kind: string }>()
const four = ['#e5534b', '#e9ebef', '#26282d', '#3b82f6']
const eight = ['#e5534b', '#e9ebef', '#26282d', '#3b82f6', '#f2c94c', '#e9ebef', '#7c3aed', '#16a34a']
const BOARD: Record<string, string> = { mmb: '#2f7d4f', easy_brd: '#2f3a8f', erb: '#8f2f3a', afc_lite: '#3a3f4a', afc_pro: '#4a3f6a' }
const boardColor = computed(() => BOARD[props.kind] ?? '#3a3f4a')
</script>

<style scoped>
.uart { width: 100%; height: 100%; display: block; }
.body { fill: var(--a-ink-3); opacity: .45; }
.spool { stroke: var(--a-swatch-edge, rgba(0,0,0,.15)); stroke-width: 2; }
.hub { fill: var(--a-surface); }
.fil { stroke: var(--a-ink-3); stroke-width: 1.4; opacity: .7; }
.ask { fill: none; stroke: var(--a-ink-3); stroke-width: 2; stroke-dasharray: 5 4; }
.q { font-size: 26px; font-weight: 700; fill: var(--a-ink-3); font-family: var(--a-display); }
</style>
