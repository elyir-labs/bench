<template>
  <!-- On Now when the print has more than one part (design/skip-objects/, A): one quiet row that opens the
       map. It says what's been skipped, and on Finished what was printed. -->
  <button class="partsrow" type="button" @click="emit('open')">
    <span class="mini"><PartsMap :parts="parts" :numbers="false" :pickable="false" /></span>
    <span class="t">
      <b>{{ title }}</b>
      <span :class="{ amber: parts.skipped.length }">{{ note }}</span>
    </span>
    <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentParts } from '@/intent/types'
import PartsMap from './PartsMap.vue'

const props = defineProps<{ parts: IntentParts; finished?: boolean }>()
const emit = defineEmits<{ open: [] }>()
const skipped = computed(() => props.parts.skipped)
const title = computed(() => {
  if (!skipped.value.length) return `${props.parts.total} parts on the plate`
  return `${props.parts.left} of ${props.parts.total} ${props.finished ? 'printed' : 'printing'}`
})
const note = computed(() => {
  if (!skipped.value.length) return props.finished ? 'All of them printed' : 'Skip one that fails'
  const names = skipped.value.length <= 2 ? skipped.value.join(' and ') : `${skipped.value.length} parts`
  return `${names} ${props.finished ? (skipped.value.length === 1 ? 'was' : 'were') : ''} skipped`.replace('  ', ' ')
})
</script>

<style scoped>
.partsrow { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; width: 100%; max-width: 460px;
  display: flex; align-items: center; gap: 12px; background: var(--a-surface); border-radius: 18px; padding: 8px 12px 8px 8px;
  margin-top: calc(8 * var(--u) + 6px); box-shadow: var(--a-card-shadow); }
.partsrow:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.mini { width: 52px; height: 52px; border-radius: 12px; overflow: hidden; flex: none; }
.t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.t b { font-size: calc(10 * var(--u) + 7px); }
.t span { font-size: calc(8 * var(--u) + 6px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.t span.amber { color: var(--a-amber-text); font-weight: 600; }
.chev { width: 22px; height: 22px; color: var(--a-ink-3); flex: none; }
</style>
