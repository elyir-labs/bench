<template>
  <div class="spoolrow" v-if="shown.length">
    <div class="icons">
      <span
        v-for="s in shown"
        :key="s.slot"
        class="spool"
        :class="[s.status, { match: isMatch(s), 'a-spool-ring': s.in_use, turning: s.in_use && feeding, guess: s.direct && (s.source === 'guess' || s.changed) }]"
        :style="{ '--c': s.color || 'transparent' }"
        :title="title(s)"
      ></span>
    </div>
    <span class="caption" v-if="note">{{ note }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentSpool } from '@/intent/types'

const props = defineProps<{
  spools: IntentSpool[]
  highlight?: string[]
  onlyInUse?: boolean
  hideEmpty?: boolean
  note?: string
  /** filament is moving right now: the in-use ring turns */
  feeding?: boolean
}>()

function dist(a: string, b: string): number {
  const p = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
  const [r1, g1, b1] = p(a), [r2, g2, b2] = p(b)
  return Math.hypot(r1 - r2, g1 - g2, b1 - b2)
}
function isMatch(s: IntentSpool): boolean {
  if (!props.highlight?.length || !s.color || s.status === 'empty') return false
  return props.highlight.some(h => dist(h.toUpperCase(), s.color!.toUpperCase()) < 70)
}
const shown = computed(() => {
  const list = props.spools.filter(s => s.status !== 'unknown' || s.color)
  if (props.onlyInUse) return list.filter(s => s.in_use || isMatch(s))
  if (props.hideEmpty) return list.filter(s => s.status !== 'empty')
  return list
})
const note = computed(() => {
  if (props.note !== undefined) return props.note
  // One spool and no unit: Ready already says what's loaded; while printing, name it.
  // It can't know how much is left (only Spoolman can), so it never says "plenty".
  const one = props.spools.length === 1 && props.spools[0].direct ? props.spools[0] : null
  if (one) return props.onlyInUse && !one.changed && one.source !== 'guess' ? (one.name ?? '') : ''
  const empty = props.spools.filter(s => s.status === 'empty').length
  const low = props.spools.filter(s => s.status === 'low')
  if (props.onlyInUse) {
    const l = shown.value.filter(s => s.status === 'low')
    if (l.length) return l.length === 1 ? 'One spool is running low' : 'Some spools are running low'
    return shown.value.length === 1 ? 'Plenty on the spool' : shown.value.length === 2 ? 'Plenty on both spools' : 'Plenty on every spool'
  }
  const parts: string[] = []
  if (low.length) parts.push(`${low.length} running low`)
  if (empty) parts.push(`${empty} empty`)
  return parts.join(' · ')
})
function title(s: IntentSpool) {
  return `Slot ${s.slot + 1}: ${s.material ?? ''} ${s.status}${s.grams ? `, ${s.grams} g` : ''}`
}
</script>

<style scoped>
/* Icons in a row, one caption underneath. The highlight ring is a shadow, so the
   row carries its own padding and the parent's clip box must leave room for it. */
.spoolrow { display: flex; flex-direction: column; gap: calc(4 * var(--u) + 1px); align-items: flex-start; }
.icons { display: flex; align-items: center; gap: calc(12 * var(--u) + 4px); flex-wrap: wrap; padding: 9px 2px; }
.spool {
  width: calc(30 * var(--u) + 10px);
  height: calc(30 * var(--u) + 10px);
  border-radius: 50%;
  background: var(--c);
  border: 3px solid var(--a-swatch-edge);
  box-sizing: border-box;
  position: relative;
  flex: none;
}
.spool.empty { background: transparent; border-style: dashed; border-color: var(--a-swatch-empty); }
.spool.low { border-color: var(--a-amber); }
.spool.guess { border-style: dashed; border-color: var(--a-ink-3); }
.spool.match { box-shadow: 0 0 0 4px var(--a-bg), 0 0 0 6px var(--a-accent); }
.spool.a-spool-ring.match { box-shadow: none; }
.caption { color: var(--a-ink-3); font-size: calc(13 * var(--u) + 4px); }
</style>
