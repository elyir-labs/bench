<template>
  <!-- Getting ready, drawn (design/now-illustrated/, A): the bed at an angle and what PRINT_START is
       doing to it. Positions, temperatures, the levelling range and the mesh are the printer's own;
       the small motions (heat rising, a probe tapping) run only while the printer works. -->
  <svg class="step-art" viewBox="0 0 200 200" role="img" :aria-label="label">
    <!-- the chamber, warming: a box of air around the bed -->
    <g v-if="art.stage === 'soaking'">
      <defs>
        <linearGradient :id="`air-${uid}`" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" class="heat-stop" stop-opacity=".28" />
          <stop :offset="0.3 + 0.55 * chamberWarm" class="heat-stop" stop-opacity=".08" />
          <stop offset="1" class="heat-stop" stop-opacity="0" />
        </linearGradient>
      </defs>
      <polygon :points="P(box.back)" :fill="`url(#air-${uid})`" />
      <polyline :points="P(box.edges)" class="dash" />
      <line :x1="box.post[0][0]" :y1="box.post[0][1]" :x2="box.post[1][0]" :y2="box.post[1][1]" class="dash" />
      <circle v-for="(d, i) in drift" :key="i" :cx="d[0]" :cy="d[1]" r="2" class="heat" :opacity="d[2]" />
    </g>

    <!-- the bed -->
    <polygon :points="P(slab.front)" class="side" />
    <polygon :points="P(slab.right)" class="side right" />
    <polygon :points="P(slab.top)" class="bed" :style="{ fill: bedFill }" />

    <!-- mesh: a cell lights once the head has been over it -->
    <g v-if="art.stage === 'mesh' && art.mesh">
      <template v-for="(c, i) in cells" :key="i">
        <polygon v-if="c.lit" :points="P(c.poly)" class="cell" />
        <circle v-else :cx="c.center[0]" :cy="c.center[1]" r="1.8" class="dot" />
      </template>
    </g>

    <!-- heat rising off the plate -->
    <g v-if="art.stage === 'warming'">
      <path v-for="(s, i) in shimmer" :key="i" :d="s.d" class="wave" :opacity="s.o" />
    </g>

    <!-- the purge line, as far as the head has drawn it -->
    <g v-if="art.stage === 'prime'">
      <line :x1="purge.a[0]" :y1="purge.a[1]" :x2="purge.b[0]" :y2="purge.b[1]" class="purge-edge" />
      <line :x1="purge.a[0]" :y1="purge.a[1]" :x2="purge.b[0]" :y2="purge.b[1]" class="purge" :style="{ stroke: filament || '#8A8D91' }" />
    </g>

    <!-- levelling: the gantry, tilted by the last pass's range, flat and ticked once in tolerance -->
    <g v-if="art.stage === 'level'">
      <line :x1="gantry.a[0]" :y1="gantry.a[1]" :x2="gantry.b[0]" :y2="gantry.b[1]" class="gantry" />
      <g v-if="gantry.tilt > 0.5" class="arrows">
        <path :d="`M${gantry.a[0]} ${gantry.a[1] + 22}v-12m-5 5l5-5 5 5`" />
        <path :d="`M${gantry.b[0]} ${gantry.b[1] - 22}v12m-5-5l5 5 5-5`" />
      </g>
      <path v-else class="ticks" :d="`M${gantry.a[0] - 5} ${gantry.a[1] + 16}l4 4 7-8M${gantry.b[0] - 5} ${gantry.b[1] + 16}l4 4 7-8`" />
    </g>

    <!-- the toolhead -->
    <g class="head" :style="{ transform: `translate(${tip[0]}px, ${tip[1]}px)` }">
      <circle v-if="glow > 0" r="1" :transform="`scale(${7 + glow * 6})`" class="heat" :opacity="0.18 + glow * 0.3" />
      <rect x="-13" y="-30" width="26" height="20" rx="5" class="head-body" />
      <path d="M-6 -10h12l-4 9h-4z" class="nozzle" :class="{ hot: glow > 0.3 }" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentArt } from '@/intent/types'
import { iso, bedPoint, headAt, warmth, tilt, meshCells, pts } from '@/art/ringArt'
import { useArtClock } from '@/art/useArtClock'

const props = defineProps<{
  art: IntentArt
  bed: { temperature: number; target: number }
  nozzle: { temperature: number; target: number }
  chamber?: { temperature: number } | null
  /** The colour coming out of the nozzle, for the purge line. */
  filament?: string | null
  /** The printer is working (not paused): the small motions run. */
  moving: boolean
}>()

const uid = Math.random().toString(36).slice(2, 8)
const clock = useArtClock(() => props.moving)
const P = pts

const LABELS: Record<string, string> = {
  warming: 'The bed warming up', soaking: 'Warm air settling around the bed', home: 'The head finding home',
  level: 'The gantry being squared', mesh: 'The head mapping the bed', heating: 'The nozzle heating', prime: 'The nozzle priming',
}
const label = computed(() => LABELS[props.art.stage ?? ''] ?? 'Getting ready')

// the bed: its top, and two sides for thickness
const C = [iso(-1, -1), iso(1, -1), iso(1, 1), iso(-1, 1)]
const down = (p: [number, number]): [number, number] => [p[0], p[1] + 7]
const slab = { top: C, front: [C[3], C[2], down(C[2]), down(C[3])], right: [C[2], C[1], down(C[1]), down(C[2])] }
const up = (p: [number, number]): [number, number] => [p[0], p[1] - 92]
const box = { back: [C[3], C[0], C[1], up(C[1]), up(C[0]), up(C[3])], edges: [C[3], up(C[3]), up(C[0]), up(C[1]), C[1]], post: [up(C[0]), C[0]] }

// warm: the bed takes on heat up to its target; after warming it stays warm
const bedWarm = computed(() => warmth(props.bed.temperature, props.bed.target || 60))
const bedFill = computed(() => props.art.stage === 'mesh'
  ? 'var(--a-surface-2)'
  : `color-mix(in srgb, #e8743b ${Math.round(bedWarm.value * 42)}%, var(--a-surface-2))`)
const chamberWarm = computed(() => Math.min(1, Math.max(0, ((props.chamber?.temperature ?? 24) - 24) / 16)))

const shimmer = computed(() => [0, 1, 2].map((i) => {
  const ph = (clock.value * 0.45 + i / 3) % 1, x = 62 + i * 38, y = 116 - ph * 46
  return { d: `M${x} ${y}q6 -7 0 -14q-6 -7 0 -14`, o: (Math.sin(ph * Math.PI) * Math.min(1, bedWarm.value * 1.3)).toFixed(2) }
}))
const drift = computed(() => Array.from({ length: 9 }, (_, i) => {
  const ph = (clock.value * 0.09 + i * 0.37) % 1
  const [x, y] = iso(-0.8 + (i % 3) * 0.8, -0.8 + Math.floor(i / 3) * 0.8, ph * 1.4)
  return [x, y, +(Math.sin(ph * Math.PI) * 0.7).toFixed(2)] as const
}))

const cells = computed(() => (props.art.mesh ? meshCells(props.art.mesh) : []))

const gantry = computed(() => {
  const t = tilt(props.art.level), a = iso(-1.15, 0, 0.95), b = iso(1.15, 0, 0.95)
  return { tilt: t, a: [a[0], a[1] - t] as const, b: [b[0], b[1] + t] as const }
})

// a probe touching down, while levelling or meshing
const tap = computed(() => (['level', 'mesh'].includes(props.art.stage ?? '') ? Math.max(0, Math.sin(clock.value * 9)) * 4 : 0))

// where the nozzle tip is: the printer's own position when it's sent, else where the stage leaves it
const tip = computed<[number, number]>(() => {
  const s = props.art.stage, h = props.art.head
  if (h) {
    const [x, y] = headAt(h)
    return [x, y + tap.value]
  }
  if (s === 'level') {   // no position: under the gantry, in the middle
    const g = gantry.value
    return [(g.a[0] + g.b[0]) / 2, (g.a[1] + g.b[1]) / 2 + 34 + tap.value]
  }
  if (s === 'heating') return iso(0, 0, 0.55)
  if (s === 'prime') return iso(-0.9, 0.92)
  if (s === 'home') return iso(1, -1, 0.35)
  return iso(0.75, -0.75, 0.85)   // parked, out of the way, while the bed heats
})

const purge = computed(() => {
  const a = iso(-0.9, 0.92)
  const h = props.art.head
  const b = h ? iso(Math.max(-0.9, bedPoint(h[0], h[1])[0]), 0.92) : a
  return { a, b }
})

const glow = computed(() => {
  if (props.art.stage !== 'heating') return 0
  const w = warmth(props.nozzle.temperature, props.nozzle.target || 200, 150)
  return 0.4 + 0.6 * w * (0.75 + 0.25 * Math.sin(clock.value * 3))
})
</script>

<style scoped>
.step-art { display: block; width: 100%; height: 100%; overflow: visible; }
.side { fill: var(--a-ink-3); opacity: .22; }
.side.right { opacity: .15; }
.bed { stroke: var(--a-ink-3); stroke-width: 1.2; stroke-linejoin: round; transition: fill 1s linear; }
.cell { fill: color-mix(in srgb, var(--a-accent) 55%, var(--a-surface-2)); stroke: var(--a-bg); stroke-width: .8; }
.dot { fill: var(--a-ink-3); }
.heat { fill: #e8743b; }
.heat-stop { stop-color: #e8743b; }
.wave { fill: none; stroke: #e8743b; stroke-width: 2.2; stroke-linecap: round; }
.dash { fill: none; stroke: var(--a-ink-3); stroke-width: 1; stroke-dasharray: 3 4; }
.gantry { stroke: var(--a-ink-2); stroke-width: 7; stroke-linecap: round; }
.arrows path { fill: none; stroke: var(--a-accent); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.ticks { fill: none; stroke: var(--a-green); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.purge-edge { stroke: var(--a-bg); stroke-width: 6; stroke-linecap: round; opacity: .6; }
.purge { stroke-width: 3.4; stroke-linecap: round; }
.head { transition: transform 300ms linear; }
.head-body { fill: var(--a-surface-2); stroke: var(--a-ink-3); stroke-width: 1.2; }
.nozzle { fill: var(--a-ink-2); }
.nozzle.hot { fill: #e8743b; }
</style>
