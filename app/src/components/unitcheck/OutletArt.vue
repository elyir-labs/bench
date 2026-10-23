<template>
  <!-- The unit's outlet side on, the filament through it (design/unit-setup/ boards gb-mark, gb-ruler, gb-pad):
       2 units per mm along the filament, the outlet's edge at x=150. -->
  <svg :viewBox="vb.join(' ')" class="outlet" aria-hidden="true">
    <line x1="40" :y1="Y" :x2="F" :y2="Y" class="fil" stroke-width="7" opacity=".35" />
    <rect x="10" :y="Y - 50" width="112" height="100" rx="14" class="unit" />
    <text x="66" :y="Y - 28" text-anchor="middle" class="name">{{ unit }}</text>
    <template v-if="ruler">
      <rect :x="F - 8" :y="Y + 10" :width="2 * ruler + 16" height="36" rx="3" class="ruler" />
      <line v-for="v in ruler + 1" :key="'t' + v" :x1="at(v - 1)" :y1="Y + 10" :x2="at(v - 1)" :y2="Y + 10 + tick(v - 1)"
            class="tick" :stroke-width="(v - 1) % 10 === 0 ? 1.4 : 0.9" />
      <text v-for="v in labels" :key="'n' + v" :x="at(v)" :y="Y + 40" text-anchor="middle" class="rn">{{ v }}</text>
    </template>
    <line v-if="tip" :x1="F" :y1="Y" :x2="at(tip)" :y2="Y" class="fil" stroke-width="7" />
    <rect x="122" :y="Y - 17" width="20" height="34" rx="4" class="fitting" />
    <rect x="142" :y="Y - 13" width="8" height="26" rx="2" class="collar" />
    <template v-if="tubeOff">
      <path :d="tubePath" fill="none" class="tube" stroke-width="18" stroke-linecap="round" />
      <path :d="tubePath" fill="none" class="tube-edge" stroke-width="1.5" />
      <path :d="`M154 ${Y - 20} Q 158 ${Y - 40} 172 ${Y - 44}`" fill="none" class="arrow" stroke-width="3" stroke-linecap="round" />
      <path :d="`M168 ${Y - 52} L 180 ${Y - 44} L 167 ${Y - 37} z`" class="arrow-head" />
      <text x="250" :y="Y - 40" class="lbl quiet">The tube, off</text>
    </template>
    <rect v-if="mark != null" :x="at(mark) - 2" :y="Y - 11" width="4" height="22" rx="1" class="mark" />
    <template v-if="markLabel && mark != null">
      <path :d="`M${at(mark)} ${Y + 14} v18`" class="ink" stroke-width="2" />
      <text :x="at(mark) - 6" :y="Y + 50" class="lbl strong">{{ markLabel }}</text>
    </template>
    <template v-if="zero">
      <line :x1="F" :y1="Y - 22" :x2="F" :y2="Y + 52" class="accent" stroke-width="2.5" />
      <text :x="F + 4" :y="Y + 70" text-anchor="end" class="lbl acc">0 at the outlet’s edge</text>
    </template>
    <template v-if="read && mark != null">
      <path :d="`M${at(mark)} ${Y + 48} v18`" class="accent" stroke-width="2.5" />
      <path :d="`M${at(mark) - 6} ${Y + 56} L ${at(mark)} ${Y + 47} L ${at(mark) + 6} ${Y + 56}`" fill="none" class="accent" stroke-width="2.5" />
      <text :x="at(mark)" :y="Y + 84" text-anchor="middle" class="lbl acc">Read it at your mark</text>
    </template>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  unit: string
  tubeOff?: boolean
  /** mm of filament out past the outlet's edge */
  tip?: number
  /** the pen line, mm from the edge */
  mark?: number | null
  markLabel?: string
  /** a ruler this many mm long, its 0 at the edge */
  ruler?: number
  zero?: boolean
  read?: boolean
  /** the crop: x, y, width, height */
  view?: [number, number, number, number]
}>(), { tubeOff: false, tip: 0, mark: null, markLabel: '', ruler: 0, zero: false, read: false })

const F = 150
const Y = 100
const at = (mm: number) => F + 2 * mm
const tick = (v: number) => (v % 10 === 0 ? 14 : v % 5 === 0 ? 9 : 5)
const vb = computed(() => props.view ?? [0, 0, 440, 210])
const labels = computed(() => Array.from({ length: Math.floor(props.ruler / 20) + 1 }, (_, i) => i * 20))
const tubePath = `M182 ${Y - 44} C 230 ${Y - 66}, 300 ${Y - 84}, 430 ${Y - 88}`
</script>

<style scoped>
.outlet { display: block; width: 100%; height: 100%; }
.unit { fill: var(--a-ink-3); opacity: 0.42; }
.name { font-size: 13px; font-weight: 700; fill: var(--a-ink); font-family: var(--a-display); }
.fil { stroke: #df4b45; }
.fitting { fill: var(--a-ink-3); opacity: 0.85; }
.collar { fill: #e0a63a; }
.ruler { fill: #f2cf5b; }
.tick { stroke: #3a2c00; }
.rn { font-size: 11px; font-weight: 700; fill: #3a2c00; font-family: var(--a-display); }
.tube { stroke: var(--a-surface-2); }
.tube-edge { stroke: var(--a-ink-3); opacity: 0.45; }
.arrow, .accent { stroke: var(--a-accent); }
.arrow-head { fill: var(--a-accent); }
.mark { fill: #15171c; }
.ink { stroke: var(--a-ink); }
.lbl { font-size: 14px; font-weight: 700; font-family: var(--a-display); }
.lbl.quiet { font-size: 13px; fill: var(--a-ink-3); }
.lbl.strong { fill: var(--a-ink); }
.lbl.acc { fill: var(--a-accent-text); }
</style>
