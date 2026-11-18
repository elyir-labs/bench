<template>
  <!-- The box's bar (design/bench-box/, D): the printers, printing on whichever is free, every spool, every printer's
       care. A dot when something there needs a person. A guest from away gets Printers and Print. Inside a printer the
       printer's own sections take its place (design/bench-7in/, A). -->
  <TabBar :items="items" label="Bench" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { bench } from '../live'
import { ordered } from '../bench'
import { careRows, spoolCards } from '../tabs'
import { here } from '../here'
import { tabsFor } from '../away'
import TabBar, { type TabItem } from './TabBar.vue'
import { boxInfo } from '../box'
import { updateDot } from '@/intent/update'

const route = useRoute()
// the box's own newer version (design/updates/): looked at now and then, not on every tick
const boxDot = ref(false)
let boxTimer = 0
async function lookAtBox() {
  const b = here.away ? null : await boxInfo()
  boxDot.value = !!b && !b.os && updateDot(b.app)
}
onMounted(() => { void lookAtBox(); boxTimer = window.setInterval(lookAtBox, 5 * 60_000) })
onBeforeUnmount(() => window.clearInterval(boxTimer))
const items = computed<TabItem[]>(() => {
  const p = route.path
  const all: TabItem[] = [
    { key: '/', to: '/', label: 'Printers', icon: 'printers', on: p === '/', dot: ordered(bench.printers).some((t) => t.rank <= 1) },
    { key: '/print', to: '/print', label: 'Print', icon: 'print', on: p.startsWith('/print') },
    { key: '/spools', to: '/spools', label: 'Spools', icon: 'spools', on: p === '/spools', dot: spoolCards(bench.printers).some((c) => c.short) },
    { key: '/care', to: '/care', label: 'Care', icon: 'care', on: p === '/care', dot: boxDot.value || careRows(bench.printers).some((r) => r.due && !r.snoozed) },
  ]
  return all.filter((t) => tabsFor(here).includes(t.key))
})
</script>
