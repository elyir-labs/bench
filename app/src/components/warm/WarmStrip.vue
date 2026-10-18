<template>
  <!-- Warming up, seen from Print (design/warm-up/, D: C's strip) -->
  <div v-if="warm?.active" class="warm-strip" role="status">
    <span class="dot" :class="{ done: warm.warm }"></span>
    <span class="w">
      <b>{{ warm.warm ? 'Warm' : 'Warming up' }} for {{ warm.material }}</b>
      <span class="a-num">{{ line }}</span>
    </span>
    <button v-if="allowedHere('cool_down')" class="a-btn ghost" :disabled="!!store.busyAction" @click="store.act('cool_down')">
      {{ store.busyAction === 'cool_down' ? '…' : 'Cool down' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import { allowedHere } from '@/door'

const store = useIntentStore()
const warm = computed(() => store.intent?.warm ?? null)
const line = computed(() => {
  const w = warm.value
  if (!w) return ''
  if (w.warm) return 'Print whenever you like.'
  const parts = []
  if (w.bed) parts.push(`Bed ${w.bed.temperature}° of ${w.bed.target}°`)
  if (w.chamber) parts.push(`chamber ${w.chamber.temperature}° of ${w.chamber.target}°`)
  if (w.minutes) parts.push(`about ${w.minutes} min`)
  return parts.join(' · ')
})
</script>

<style scoped>
.warm-strip {
  display: flex; align-items: center; gap: calc(10 * var(--u) + 4px);
  padding: calc(8 * var(--u) + 2px) calc(10 * var(--u) + 2px) calc(8 * var(--u) + 2px) calc(14 * var(--u) + 4px);
  border-radius: calc(14 * var(--u) + 4px); margin-bottom: calc(10 * var(--u) + 4px);
  background: color-mix(in srgb, #e8743b 18%, var(--a-surface));
}
.dot { width: 10px; height: 10px; border-radius: 50%; background: #e8743b; box-shadow: 0 0 0 4px rgba(232, 116, 59, .25); flex: none; }
.dot.done { background: var(--a-green); box-shadow: 0 0 0 4px color-mix(in srgb, var(--a-green) 25%, transparent); }
.w { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.w b { font-size: calc(14 * var(--u) + 4px); }
.w span { font-size: calc(11 * var(--u) + 3.5px); color: var(--a-ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.a-btn { flex: none; font-size: calc(13 * var(--u) + 4px); padding: calc(6 * var(--u) + 3px) calc(14 * var(--u) + 4px); min-height: 40px; }
</style>
