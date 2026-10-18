<template>
  <!-- The bed from above, seen from the front of the printer (front at the bottom), each part its real
       outline from Klipper with its number (design/skip-objects/, A). The one printing now pulses. -->
  <svg :viewBox="viewBox" class="map" role="img" :aria-label="`Map of the bed: ${parts.total} parts`">
    <rect :x="b[0]" :y="0" :width="w" :height="h" rx="6" class="bed" />
    <path :d="grid" class="grid" />
    <g v-for="it in parts.items" :key="it.name" class="part" :class="[it.state, { sel: it.name === selected }]"
       @click="pickable && emit('pick', it.name)">
      <polygon :points="points(it)" />
      <template v-if="numbers">
        <circle :cx="it.center[0] - b[0]" :cy="flip(it.center[1])" :r="r" class="badge" />
        <text :x="it.center[0] - b[0]" :y="flip(it.center[1]) + r * 0.42" :font-size="r * 1.2" text-anchor="middle">{{ it.n }}</text>
      </template>
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentPart, IntentParts } from '@/intent/types'

const props = withDefaults(defineProps<{ parts: IntentParts; selected?: string | null; numbers?: boolean; pickable?: boolean }>(),
  { selected: null, numbers: true, pickable: true })
const emit = defineEmits<{ pick: [name: string] }>()
const b = computed(() => props.parts.bed)
const w = computed(() => b.value[2] - b.value[0])
const h = computed(() => b.value[3] - b.value[1])
// Zoomed to the parts with room around them (a few small parts aren't specks on a 350 mm bed), square, kept
// on the bed; a full plate shows the whole bed.
const viewBox = computed(() => {
  const pts = props.parts.items.flatMap(it => (it.polygon.length ? it.polygon : [it.center]))
  if (!pts.length) return `${-6} ${-6} ${w.value + 12} ${h.value + 12}`
  const xs = pts.map(p => p[0] - b.value[0]), ys = pts.map(p => flip(p[1]))
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const side = Math.min(Math.max(w.value, h.value) + 12, Math.max(120, Math.max(x1 - x0, y1 - y0) * 1.35 + 30))
  const clamp = (c: number, span: number) => Math.min(Math.max(c - side / 2, -6), span + 6 - side)
  const vx = side >= w.value + 12 ? -6 : clamp((x0 + x1) / 2, w.value)
  const vy = side >= h.value + 12 ? -6 : clamp((y0 + y1) / 2, h.value)
  return `${vx} ${vy} ${side} ${side}`
})
// numbers sized to the parts: a quarter of the smallest part's width, readable but inside it
const r = computed(() => {
  const ws = props.parts.items.map(it => { const xs = it.polygon.map(p => p[0]); return xs.length ? Math.max(...xs) - Math.min(...xs) : 20 })
  return Math.max(5, Math.min(12, Math.min(...ws) * 0.26))
})
const flip = (y: number) => b.value[3] - y
const points = (it: IntentPart) => (it.polygon.length ? it.polygon : [[it.center[0] - 5, it.center[1] - 5], [it.center[0] + 5, it.center[1] - 5], [it.center[0] + 5, it.center[1] + 5], [it.center[0] - 5, it.center[1] + 5]])
  .map(p => `${p[0] - b.value[0]},${flip(p[1])}`).join(' ')
const grid = computed(() => {
  const d: string[] = []
  for (let v = 0; v <= w.value; v += 10) d.push(`M${v} 0V${h.value}`)
  for (let v = 0; v <= h.value; v += 10) d.push(`M0 ${v}H${w.value}`)
  return d.join('')
})
</script>

<style scoped>
.map { display: block; width: 100%; height: 100%; }
.bed { fill: var(--a-surface-2); stroke: var(--a-line); stroke-width: 1.5; }
.grid { stroke: var(--a-line); stroke-width: 0.5; fill: none; }
.part polygon { fill: #33c24d; stroke: #1f8a34; stroke-width: 0.8; cursor: pointer; }
.part.printing polygon { stroke: var(--a-accent); stroke-width: 3; animation: pulse 1.4s ease-in-out infinite; }
.part.sel polygon { fill: var(--a-red); stroke: var(--a-red); stroke-width: 3; animation: none; }
.part.skipped polygon { fill: var(--a-surface); stroke: var(--a-ink-3); stroke-dasharray: 3 2; cursor: default; }
.badge { fill: var(--a-surface); opacity: 0.95; pointer-events: none; }
.part.skipped .badge { opacity: 0.6; }
text { font-weight: 700; font-family: inherit; fill: var(--a-ink); pointer-events: none; }
.part.skipped text { fill: var(--a-ink-3); }
@keyframes pulse { 0%, 100% { stroke-opacity: 1 } 50% { stroke-opacity: 0.25 } }
@media (prefers-reduced-motion: reduce) { .part.printing polygon { animation: none; } }
</style>
