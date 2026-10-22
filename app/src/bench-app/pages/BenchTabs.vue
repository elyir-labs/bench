<template>
  <!-- The box's one tab bar (design/bench-box/, D): the printers, printing on whichever is free, every spool,
       every printer's care. A dot when something there needs a person. A guest from away gets Printers and Print. -->
  <nav class="btabs" aria-label="Bench">
    <router-link v-for="t in tabs" :key="t.to" :to="t.to" class="tab" :class="{ on: t.on(route.path), dot: dots[t.to] }">
      <span class="icon" aria-hidden="true" v-html="t.icon"></span>{{ t.label }}
    </router-link>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { bench } from '../live'
import { ordered } from '../bench'
import { careRows, spoolCards } from '../tabs'
import { here } from '../here'
import { tabsFor } from '../away'

const route = useRoute()
const TABS = [
  { to: '/', label: 'Printers', on: (p: string) => p === '/' || p.startsWith('/p/'),
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="4" width="8" height="9" rx="1.5"/><rect x="13" y="4" width="8" height="9" rx="1.5"/><rect x="8" y="14.5" width="8" height="6.5" rx="1.5"/></svg>' },
  { to: '/print', label: 'Print', on: (p: string) => p.startsWith('/print'),
    icon: '<svg viewBox="0 0 24 24"><path d="M7 8V4.5h10V8M6 16H4.5v-5.5A2.5 2.5 0 0 1 7 8h10a2.5 2.5 0 0 1 2.5 2.5V16H18M7 13h10v6.5H7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>' },
  { to: '/spools', label: 'Spools', on: (p: string) => p === '/spools',
    icon: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>' },
  { to: '/care', label: 'Care', on: (p: string) => p === '/care',
    icon: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.6-7.5-10A4.2 4.2 0 0 1 12 8a4.2 4.2 0 0 1 7.5 2.5c0 5.4-7.5 10-7.5 10z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>' },
]
const tabs = computed(() => TABS.filter((t) => tabsFor(here).includes(t.to)))
const dots = computed<Record<string, boolean>>(() => ({
  '/': ordered(bench.printers).some((t) => t.rank <= 1),
  '/spools': spoolCards(bench.printers).some((c) => c.short),
  '/care': careRows(bench.printers).some((r) => r.due && !r.snoozed),
}))
</script>

<style scoped>
.btabs { flex: none; height: 86px; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; border-top: 1px solid var(--a-line);
         background: color-mix(in srgb, var(--a-bg) 80%, transparent); backdrop-filter: blur(10px); padding-bottom: env(safe-area-inset-bottom); }
.tab { position: relative; display: grid; place-items: center; align-content: center; gap: 4px; color: var(--a-ink-3); font-size: 18px; font-weight: 650; text-decoration: none; }
.tab.on { color: var(--a-ink); }
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
