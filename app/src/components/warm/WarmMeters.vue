<template>
  <!-- Bed and chamber on their way to what the material wants (design/warm-up/, D) -->
  <div class="meters" :class="{ done: warm.warm }">
    <div v-if="warm.bed" class="meter">
      <span class="k">Bed</span>
      <span class="bar"><i :style="{ width: pct(warm.bed.temperature, warm.bed.target, 22) }"></i></span>
      <span class="v a-num"><b>{{ warm.bed.temperature }}°</b> of {{ warm.bed.target }}°</span>
    </div>
    <div v-if="warm.chamber" class="meter">
      <span class="k">Chamber</span>
      <span class="bar"><i :style="{ width: pct(warm.chamber.temperature, warm.chamber.target, 22) }"></i></span>
      <span class="v a-num"><b>{{ warm.chamber.temperature }}°</b> of {{ warm.chamber.target }}°</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { IntentWarm } from '@/intent/types'
defineProps<{ warm: IntentWarm }>()
// from room temperature to the target, so the bar starts empty
function pct(t: number, target: number, room: number): string {
  const f = target > room ? (t - room) / (target - room) : 1
  return `${Math.round(Math.max(0.03, Math.min(1, f)) * 100)}%`
}
</script>

<style scoped>
.meters { display: grid; gap: calc(6 * var(--u) + 4px); max-width: calc(300 * var(--u) + 60px); }
.meter { display: grid; grid-template-columns: calc(56 * var(--u) + 18px) 1fr auto; align-items: center; gap: calc(8 * var(--u) + 2px); font-size: calc(12 * var(--u) + 4px); color: var(--a-ink-2); }
.bar { height: calc(5 * var(--u) + 3px); border-radius: 99px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: inherit; background: var(--a-heat, #e8743b); transition: width 800ms linear; }
.done .bar i { background: var(--a-green); }
.v b { color: var(--a-ink); font-weight: 600; }
</style>
