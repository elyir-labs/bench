<template>
  <!-- How far, around the job's picture; the bed alone when there's nothing on it -->
  <span class="bring" :class="{ small }" :style="{ '--d': d + 'px' }">
    <svg :viewBox="`0 0 ${d} ${d}`" aria-hidden="true">
      <circle :cx="d / 2" :cy="d / 2" :r="r" fill="var(--a-surface)" stroke="var(--a-surface-2)" :stroke-width="w" />
      <circle v-if="tile.frac" :cx="d / 2" :cy="d / 2" :r="r" fill="none" :stroke="color" :stroke-width="w" stroke-linecap="round"
              :stroke-dasharray="`${L * Math.min(tile.frac, 1)} ${L}`" :transform="`rotate(-90 ${d / 2} ${d / 2})`" />
    </svg>
    <!-- a picture that doesn't load (from away only png, jpg and webp pass the door): the bed instead of a broken image -->
    <img v-if="src && failed !== src" :src="src" alt="" @error="failed = src" />
    <span v-else class="bed"></span>
    <span v-if="!small && d >= 100 && label" class="lab a-num" :class="'tone-' + tile.tone">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Tile } from '../bench'
import { fileOf, type LiveBenchPrinter } from '../live'
import { sizeFor } from '../bench'
import { bench } from '../live'

const props = defineProps<{ tile: Tile; printer: LiveBenchPrinter; small?: boolean }>()
const on = computed(() => bench.printers.filter((p) => p.live).length)
const d = computed(() => (props.small ? 44 : window.innerWidth < 600 ? 52 : sizeFor(on.value) === 'big' ? 196 : 112))
const w = computed(() => Math.max(5, Math.round(d.value / 20)))
const r = computed(() => d.value / 2 - w.value)
const L = computed(() => 2 * Math.PI * r.value)
const color = computed(() => (props.tile.tone === 'amber' ? 'var(--a-amber)' : props.tile.tone === 'red' ? 'var(--a-red)' : 'var(--a-accent)'))
const src = computed(() => fileOf(props.printer, props.tile.thumbnail))
const failed = ref<string | null>(null)
const label = computed(() => (props.tile.word === 'Needs you' ? 'Paused' : props.tile.tone === 'blue' && props.tile.frac ? `${Math.round(props.tile.frac * 100)}%` : ''))
</script>

<style scoped>
.bring { position: relative; width: var(--d); height: var(--d); display: grid; place-items: center; flex: none; }
.bring svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.bring img { position: relative; width: 62%; height: 62%; object-fit: contain; border-radius: 50%; }
.bed { position: relative; width: 52%; height: 22%; background: var(--a-surface-2); transform: skewX(-30deg) rotate(-8deg); border-radius: 3px; }
.lab { position: absolute; left: 50%; bottom: -8px; transform: translateX(-50%); border-radius: 999px; padding: 4px 12px; font-size: 16px; font-weight: 700; }
.lab.tone-blue { background: var(--a-accent); color: var(--a-accent-ink); }
.lab.tone-amber { background: color-mix(in srgb, var(--a-amber) 30%, var(--a-surface)); color: var(--a-amber-text); }
</style>
