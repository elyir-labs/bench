<template>
  <span v-if="chip" class="awaychip" :class="chip.icon"><svg viewBox="0 0 24 24" aria-hidden="true" v-html="chip.icon === 'eye' ? EYE : LOCK"></svg>{{ chip.label }}</span>
</template>

<script lang="ts">
export const EYE = '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'
export const LOCK = '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>'
</script>

<script setup lang="ts">
import { computed } from 'vue'
import { here } from '../here'
import { chipFor } from '../away'

const chip = computed(() => chipFor(here))
</script>

<style scoped>
.awaychip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 14px; border-radius: 999px; font-size: 17px; font-weight: 650;
            background: color-mix(in srgb, var(--a-accent) 16%, transparent); color: var(--a-accent-text); white-space: nowrap; }
.awaychip svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linejoin: round; }
@media (max-width: 599px) { .awaychip { font-size: 14px; padding: 4px 11px; gap: 6px; } .awaychip svg { width: 15px; height: 15px; } }
</style>
