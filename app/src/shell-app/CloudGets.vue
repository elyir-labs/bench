<template>
  <ul class="gets" :class="{ lines }">
    <li v-for="g in GETS" :key="g.title">
      <span class="gi" aria-hidden="true" v-html="ICONS[g.icon]"></span>
      <b>{{ g.title }}</b>
      <small v-if="lines">{{ g.line }}</small>
    </li>
  </ul>
</template>

<script setup lang="ts">
import { GETS } from './you'

defineProps<{ lines?: boolean }>()

const ICONS: Record<string, string> = {
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5c-2.6-2.4-3.8-5.2-3.8-8.5S9.4 5.9 12 3.5z"/></svg>',
  reload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M19 12a7 7 0 1 1-2.1-5M19 4.5V8h-3.5"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 18.5h3"/></svg>',
}
</script>

<style scoped>
.gets { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.gets.lines { gap: 14px; }
li { display: grid; grid-template-columns: auto 1fr; gap: 2px 14px; align-items: center; }
.lines li { align-items: start; }
.gi { grid-row: 1 / span 2; width: 36px; height: 36px; border-radius: 12px; display: grid; place-items: center;
  color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 14%, transparent); }
.gi :deep(svg) { width: 20px; height: 20px; }
b { font-size: 16px; font-weight: 650; line-height: 1.25; }
small { font-size: 14px; color: var(--a-ink-3); line-height: 1.35; }
li:not(:has(small)) b { grid-row: 1 / span 2; }
</style>
