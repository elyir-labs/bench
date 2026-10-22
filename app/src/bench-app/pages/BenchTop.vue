<template>
  <!-- The box's top row on the bench's own pages: who it is, and the time. At home, who is watching from away
       (design/bench-remote/, C: guests only); away, the Away or Watching chip in place of the time. -->
  <header class="btop">
    <span class="who"><i></i><b>{{ title }}</b></span>
    <span class="right">
      <span v-if="seen" class="seen"><svg viewBox="0 0 24 24" aria-hidden="true" v-html="EYE"></svg>{{ seen }}</span>
      <AwayChip />
      <slot />
      <span v-if="!here.away" class="clock a-num">{{ clock }}</span>
    </span>
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { here, watching } from '../here'
import { watchingLine } from '../away'
import AwayChip, { EYE } from './AwayChip.vue'

defineProps<{ title: string }>()
const seen = computed(() => (here.away ? null : watchingLine(watching.names)))
const clock = ref('')
const tick = () => { clock.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase() }
tick()
const timer = window.setInterval(tick, 10000)
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.btop { display: flex; justify-content: space-between; align-items: center; gap: 12px; color: var(--a-ink-3); font-size: 22px; }
.who { display: inline-flex; align-items: center; gap: 10px; }
.who i { width: 11px; height: 11px; border-radius: 50%; background: var(--a-green); box-shadow: 0 0 0 4px var(--a-tint-green); }
.who b { color: var(--a-ink); font-size: 17px; letter-spacing: .06em; text-transform: uppercase; }
.right { display: inline-flex; align-items: center; gap: 24px; min-width: 0; }
.clock { white-space: nowrap; }
.seen { display: inline-flex; align-items: center; gap: 8px; color: var(--a-accent-text); font-size: 19px; font-weight: 550; white-space: nowrap; }
.seen svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; }
@media (max-width: 599px) {
  .btop { font-size: 16px; }
  .right { gap: 14px; }
  .seen { font-size: 14px; } .seen svg { width: 17px; height: 17px; }
}
@media (max-height: 540px) and (min-width: 600px) {
  .btop { font-size: 17px; }
  .who b { font-size: 15px; }
  .right { gap: 16px; }
}
</style>
