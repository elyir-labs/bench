<template>
  <!-- tiles: off the panel, three labelled tiles inside Now instead of a line in the top bar -->
  <div class="tiles a-num" v-if="tiles && show" aria-label="Temperatures">
    <div class="tile"><small>Nozzle</small><b>{{ Math.round(p.nozzle.temperature) }}°<span class="to" v-if="heading(p.nozzle)">→ {{ heading(p.nozzle) }}°</span></b></div>
    <div class="tile"><small>Bed</small><b>{{ Math.round(p.bed.temperature) }}°<span class="to" v-if="heading(p.bed)">→ {{ heading(p.bed) }}°</span></b></div>
    <div class="tile" v-if="p.chamber"><small>Chamber</small><b>{{ Math.round(p.chamber.temperature) }}°</b></div>
  </div>
  <div class="vitals a-num" v-else-if="show" aria-label="Temperatures">
    <span class="v" title="Nozzle">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 2h6v5l-2 3v2H7v-2L5 7V2z" fill="currentColor"/><path d="M7.5 13h1v1.5h-1z" fill="currentColor"/></svg>
      <span>{{ fmt(p.nozzle) }}</span>
    </span>
    <span class="v" title="Bed">
      <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="10" width="12" height="3" rx="1" fill="currentColor"/><path d="M5 8c0-1.5 1.2-1.5 1.2-3S5 3.5 5 2M8 8c0-1.5 1.2-1.5 1.2-3S8 3.5 8 2M11 8c0-1.5 1.2-1.5 1.2-3S11 3.5 11 2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
      <span>{{ fmt(p.bed) }}</span>
    </span>
    <span class="v" v-if="p.chamber" title="Chamber">
      <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="3.5" width="11" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2.5 7h11" stroke="currentColor" stroke-width="1.4"/></svg>
      <span>{{ Math.round(p.chamber.temperature) }}°</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Intent } from '@/intent/types'

const props = defineProps<{ intent: Intent; tiles?: boolean }>()
const p = computed(() => props.intent.printer)

// Shown while the printer is doing something, or while anything is still warm.
const show = computed(() => {
  const s = props.intent.state
  if (s !== 'ready') return true
  return p.value.nozzle.temperature > 45 || p.value.bed.temperature > 35 || p.value.nozzle.target > 0 || p.value.bed.target > 0
})

/** The target while it's still getting there, else null. */
function heading(h: { temperature: number; target: number }): number | null {
  return h.target > 0 && Math.abs(h.temperature - h.target) > 2 ? Math.round(h.target) : null
}

function fmt(h: { temperature: number; target: number }): string {
  const to = heading(h)
  return to === null ? `${Math.round(h.temperature)}°` : `${Math.round(h.temperature)} → ${to}°`
}
</script>

<style scoped>
.vitals { display: inline-flex; align-items: center; gap: calc(14 * var(--u) + 6px); color: var(--a-ink-2); font-size: calc(14 * var(--u) + 5px); font-weight: 500; }
.v { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.v svg { width: calc(13 * var(--u) + 5px); height: calc(13 * var(--u) + 5px); color: var(--a-ink-3); flex: none; }
.tiles { display: flex; gap: 8px; }
.tile { flex: 1; min-width: 0; background: color-mix(in srgb, var(--a-surface) 75%, transparent); border-radius: 14px; padding: 9px 12px; display: flex; flex-direction: column; gap: 1px; }
.tile small { font-size: 12px; font-weight: 600; color: var(--a-ink-3); }
.tile b { font-size: 18px; font-weight: 700; display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 5px; }
.tile .to { font-size: 14px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; }
</style>
