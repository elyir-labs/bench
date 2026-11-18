<template>
  <!-- The one bar at the bottom (design/bench-7in/, A): the box's sections, or inside a printer that printer's.
       An item with `to` is a link; one without is a button that says which was picked. -->
  <nav class="btabs" :aria-label="label">
    <component :is="t.to ? RouterLink : 'button'" v-for="t in items" :key="t.key" v-bind="t.to ? { to: t.to } : { type: 'button' }"
               class="tab" :class="{ on: t.on, dot: t.dot }" :aria-current="t.on ? 'page' : undefined" @click="!t.to && emit('pick', t.key)">
      <span class="icon" aria-hidden="true" v-html="ICONS[t.icon]"></span>{{ t.label }}
    </component>
  </nav>
</template>

<script lang="ts">
export interface TabItem { key: string; label: string; icon: keyof typeof ICONS; on: boolean; to?: string; dot?: boolean }
const S = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"'
const ICONS = {
  printers: `<svg viewBox="0 0 24 24" ${S}><rect x="3" y="4" width="8" height="9" rx="1.5"/><rect x="13" y="4" width="8" height="9" rx="1.5"/><rect x="8" y="14.5" width="8" height="6.5" rx="1.5"/></svg>`,
  print: `<svg viewBox="0 0 24 24" ${S}><path d="M7 8V4.5h10V8M6 16H4.5v-5.5A2.5 2.5 0 0 1 7 8h10a2.5 2.5 0 0 1 2.5 2.5V16H18M7 13h10v6.5H7z"/></svg>`,
  spools: `<svg viewBox="0 0 24 24" ${S}><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.2"/></svg>`,
  care: `<svg viewBox="0 0 24 24" ${S}><path d="M12 20.5s-7.5-4.6-7.5-10A4.2 4.2 0 0 1 12 8a4.2 4.2 0 0 1 7.5 2.5c0 5.4-7.5 10-7.5 10z"/></svg>`,
  now: `<svg viewBox="0 0 24 24" ${S}><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none"/></svg>`,
  materials: `<svg viewBox="0 0 24 24" ${S}><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.2"/><path d="M12 3.5v4.3"/></svg>`,
}
</script>

<script setup lang="ts">
import { RouterLink } from 'vue-router'

defineProps<{ items: TabItem[]; label: string }>()
const emit = defineEmits<{ pick: [key: string] }>()
</script>

<style scoped>
.btabs { flex: none; height: 86px; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; border-top: 1px solid var(--a-line);
         background: color-mix(in srgb, var(--a-bg) 80%, transparent); backdrop-filter: blur(10px); padding-bottom: env(safe-area-inset-bottom); }
.tab { position: relative; display: grid; place-items: center; align-content: center; gap: 4px; color: var(--a-ink-3); font: inherit; font-size: 18px; font-weight: 650;
       text-decoration: none; appearance: none; border: 0; background: none; padding: 0; cursor: pointer; }
.tab.on { color: var(--a-ink); }
.tab.on::before { content: ''; position: absolute; top: -1px; left: 30%; right: 30%; height: 3px; border-radius: 0 0 3px 3px; background: var(--a-accent); }
.icon { width: 30px; height: 30px; display: block; }
.icon :deep(svg) { width: 100%; height: 100%; display: block; }
.tab.dot::after { content: ''; position: absolute; top: 14px; right: calc(50% - 24px); width: 9px; height: 9px; border-radius: 50%; background: var(--a-amber); }
@media (max-width: 599px) {
  .btabs { height: 64px; } .tab { font-size: 12px; gap: 2px; } .icon { width: 24px; height: 24px; }
  .tab.dot::after { top: 8px; right: calc(50% - 18px); width: 8px; height: 8px; }
}
@media (max-height: 540px) and (min-width: 600px) {
  .btabs { height: 60px; } .tab { font-size: 14px; gap: 2px; } .icon { width: 24px; height: 24px; }
  .tab.dot::after { top: 7px; right: calc(50% - 18px); width: 8px; height: 8px; }
}
</style>
